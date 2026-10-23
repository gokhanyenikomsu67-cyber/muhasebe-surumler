"""Uçtan uca senaryolar: fatura, tahsilat, ödeme, çekin her adımı ve banka ekstresi.
Her adımdan sonra beklenen bakiyeler ve tüm ekranların aynı bakiyeyi gösterdiği denetlenir."""
import io

import pytest
from openpyxl import Workbook

from app import ai
from tests.test_api import client
from tests.test_cek_banka import kur


def _bos_ekstre():
    wb = Workbook()
    wb.active.append(["Tarih", "Açıklama", "Tutar"])
    tampon = io.BytesIO()
    wb.save(tampon)
    return tampon.getvalue()


def ekstre_yukle(monkeypatch, h, hesap_id, satirlar):
    """Banka ekstresi: okuma kısmı sabit satırlarla taklit edilir, kaydetme/eşleştirme gerçek koddan geçer."""
    monkeypatch.setattr(ai, "ekstre_oku", lambda *a, **k: {"notlar": "", "satirlar": satirlar})
    r = client.post(f"/api/banka-hesaplari/{hesap_id}/ekstre?yontem=ai",
                    files={"dosya": ("ekstre.xlsx", _bos_ekstre(), "application/octet-stream")}, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def onayla_hepsi(h):
    taslak = [t["id"] for t in client.get("/api/hareketler?durum=taslak", headers=h).json()]
    if taslak:
        client.post("/api/hareketler/onayla", json={"sorunlular_dahil": True, "idler": taslak}, headers=h)


def fatura(h, yon, no, cari_id, tutar, tarih="2026-10-01"):
    f = client.post("/api/faturalar", json={"yon": yon, "fatura_no": no, "cari_id": cari_id, "tarih": tarih,
                                            "kalemler": [{"aciklama": "İş", "birim_fiyat": tutar, "kdv_orani": 0}]},
                    headers=h).json()
    assert client.post(f"/api/faturalar/{f['id']}/onayla", headers=h).status_code == 200


def islem(h, cek_id, **veri):
    r = client.post(f"/api/cekler/{cek_id}/islem", json=veri, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def bakiyeler(h) -> tuple[dict, dict]:
    """Bakiye tek kaynaktan: cari kartı/ekstre, cari bakiye raporu, yaşlandırma, Genel Durum, banka ekranı,
    nakit akışı ve yazdırılan ekstre aynı rakamı göstermeli. Farklıysa test hangi ekranın ayrıldığını söyler."""
    rapor = {c["id"]: c["bakiye"] for c in client.get("/api/raporlar/cari-bakiye", headers=h).json()}
    for cari_id, b in rapor.items():
        assert client.get(f"/api/raporlar/cari-ekstre/{cari_id}", headers=h).json()["bakiye"] == b, "cari ekstresi"
        yazili = client.get(f"/api/yazdir/cari-ekstre/{cari_id}", headers=h).text
        assert f"{abs(b):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") in yazili, "yazdırılan ekstre"
    yas = client.get("/api/raporlar/yaslandirma?tarih=2099-12-31", headers=h).json()
    for r in yas["alacak"]:
        assert r["bakiye"] == rapor[r["cari_id"]], "yaşlandırma (alacak)"
    for r in yas["borc"]:
        assert -r["bakiye"] == rapor[r["cari_id"]], "yaşlandırma (borç)"
    assert len(yas["alacak"]) + len(yas["borc"]) == sum(1 for b in rapor.values() if abs(b) >= 0.01)
    banka = {b["id"]: b["bakiye"] for b in client.get("/api/banka-hesaplari", headers=h).json()}
    ozet = client.get("/api/raporlar/ozet", headers=h).json()
    assert ozet["alacak_toplam"] == round(sum(b for b in rapor.values() if b > 0), 2), "Genel Durum alacak"
    assert ozet["borc_toplam"] == round(-sum(b for b in rapor.values() if b < 0), 2), "Genel Durum borç"
    assert ozet["banka_toplam"] == round(sum(banka.values()), 2), "Genel Durum banka"
    return rapor, banka


def test_fatura_tahsilat_cek_ve_ekstre_tek_kez_islenir(monkeypatch):
    h, musteri, tedarikci, banka = kur()  # banka açılış 1.000
    m, t, b = musteri["id"], tedarikci["id"], banka["id"]

    fatura(h, "giden", "S1", m, 10000)
    fatura(h, "gelen", "A1", t, 3000)
    cari, hesap = bakiyeler(h)
    assert (cari[m], cari[t], hesap[b]) == (10000, -3000, 1000)

    # Müşteri 2.000 EFT yaptı, elle girildi
    client.post("/api/hareketler", json={"tarih": "2026-10-05", "yon": "giris", "tur": "tahsilat", "tutar": 2000,
                                         "cari_id": m, "banka_hesap_id": b}, headers=h)
    cari, hesap = bakiyeler(h)
    assert (cari[m], hesap[b]) == (8000, 3000)

    # Müşteriden 4.000 çek: cariden düşer, bankaya henüz girmez
    c = client.post("/api/cekler", json={"yon": "alinan", "tutar": 4000, "vade": "2026-10-20", "cari_id": m,
                                         "cek_no": "1001"}, headers=h).json()
    cari, hesap = bakiyeler(h)
    assert (cari[m], hesap[b]) == (4000, 3000)
    assert client.get("/api/raporlar/ozet", headers=h).json()["portfoy_cek"] == 4000

    islem(h, c["id"], islem="tahsile_ver", tarih="2026-10-15", banka_hesap_id=b)
    cari, hesap = bakiyeler(h)
    assert (cari[m], hesap[b]) == (4000, 3000)  # tahsile vermek para hareketi değildir

    islem(h, c["id"], islem="tahsil", tarih="2026-10-20")
    cari, hesap = bakiyeler(h)
    assert (cari[m], hesap[b]) == (4000, 7000)  # cari değişmez, para bankaya girer

    # Tedarikçiye 1.500 çek verildi, bankadan ödendi
    v = client.post("/api/cekler", json={"yon": "verilen", "tutar": 1500, "vade": "2026-10-25", "cari_id": t}, headers=h).json()
    islem(h, v["id"], islem="ode", tarih="2026-10-25", banka_hesap_id=b)
    cari, hesap = bakiyeler(h)
    assert (cari[t], hesap[b]) == (-1500, 5500)

    # Ekstre gelir: elle girilen EFT, tahsil edilen çek ve ödenen çek bankada da görünür, ayrıca bir masraf var.
    # Okuyucu çek tahsilatını müşteriden tahsilat sanıyor (en kötü durum): yine de ikinci kez yazılmamalı.
    r = ekstre_yukle(monkeypatch, h, b, [
        {"tarih": "2026-10-05", "aciklama": "EFT AHMET YAPI", "tutar": 2000, "bakiye": 3000,
         "onerilen_cari_id": m, "onerilen_tur": "tahsilat"},
        {"tarih": "2026-10-21", "aciklama": "ÇEK TAHSİLATI 1001", "tutar": 4000, "bakiye": 7000,
         "onerilen_cari_id": m, "onerilen_tur": "tahsilat"},
        {"tarih": "2026-10-25", "aciklama": "ÇEK ÖDEMESİ", "tutar": -1500, "bakiye": 5500,
         "onerilen_cari_id": t, "onerilen_tur": "odeme"},
        {"tarih": "2026-10-26", "aciklama": "EFT MASRAFI", "tutar": -10, "bakiye": 5490,
         "onerilen_tur": "banka_masrafi"},
    ])
    assert r["eklenen"] == 1, r
    onayla_hepsi(h)
    cari, hesap = bakiyeler(h)
    assert (cari[m], cari[t], hesap[b]) == (4000, -1500, 5490)
    hesap_satiri = next(x for x in client.get("/api/banka-hesaplari", headers=h).json() if x["id"] == b)
    assert hesap_satiri["mutabakat_farki"] == 0

    # Aynı ekstre tekrar yüklenirse hiçbir şey değişmez
    r = ekstre_yukle(monkeypatch, h, b, [
        {"tarih": "2026-10-21", "aciklama": "ÇEK TAHSİLATI 1001", "tutar": 4000, "bakiye": 7000,
         "onerilen_cari_id": m, "onerilen_tur": "tahsilat"}])
    assert (r["eklenen"], r["atlanan"]) == (0, 1)
    assert bakiyeler(h)[1][b] == 5490


def test_ekstre_once_gelirse_tahsilde_cek_kendiliginden_tahsil_olur(monkeypatch):
    h, musteri, _, banka = kur()
    m, b = musteri["id"], banka["id"]
    c = client.post("/api/cekler", json={"yon": "alinan", "tutar": 2500, "vade": "2026-11-10", "cari_id": m}, headers=h).json()
    islem(h, c["id"], islem="tahsile_ver", tarih="2026-11-01", banka_hesap_id=b)
    r = ekstre_yukle(monkeypatch, h, b, [
        {"tarih": "2026-11-11", "aciklama": "TAHSILAT 0000123", "tutar": 2500, "bakiye": 3500,
         "onerilen_cari_id": m, "onerilen_tur": "tahsilat"}])
    assert r["eklenen"] == 0 and "çekle eşleşti" in r["notlar"]
    cek = client.get(f"/api/cekler/{c['id']}", headers=h).json()
    assert cek["durum"] == "tahsil_edildi"
    cari, hesap = bakiyeler(h)
    assert (cari[m], hesap[b]) == (-2500, 3500)
    # Artık tekrar tahsil edilemez
    assert client.post(f"/api/cekler/{c['id']}/islem", json={"islem": "tahsil", "tarih": "2026-11-11"}, headers=h).status_code == 400


def test_ekstre_cariye_tahsilat_yazdiysa_cek_tahsili_onu_ceke_cevirir(monkeypatch):
    h, musteri, _, banka = kur()
    m, b = musteri["id"], banka["id"]
    # Portföydeki çek bankaya götürüldü ama programda işaretlenmedi; ekstrede "çek" kelimesi yok
    c = client.post("/api/cekler", json={"yon": "alinan", "tutar": 700, "vade": "2026-11-10", "cari_id": m}, headers=h).json()
    r = ekstre_yukle(monkeypatch, h, b, [
        {"tarih": "2026-11-10", "aciklama": "GELEN EFT AHMET YAPI", "tutar": 700, "bakiye": 1700,
         "onerilen_cari_id": m, "onerilen_tur": "tahsilat"}])
    assert r["eklenen"] == 1  # kelime yoksa tahmin edilmez: tahsilat olarak gelir
    onayla_hepsi(h)
    assert bakiyeler(h)[0][m] == -1400  # aynı para iki kez: çek + ekstre tahsilatı
    # Kullanıcı çeki "tahsil edildi" yapınca ekstre satırı çekin hareketine dönüşür, çift kayıt kalkar
    islem(h, c["id"], islem="tahsil", tarih="2026-11-10", banka_hesap_id=b)
    cari, hesap = bakiyeler(h)
    assert (cari[m], hesap[b]) == (-700, 1700)
    hs = client.get(f"/api/hareketler?banka_hesap_id={b}", headers=h).json()
    assert len(hs) == 1 and hs[0]["tur"] == "cek_tahsil"
    assert next(x for x in client.get("/api/banka-hesaplari", headers=h).json() if x["id"] == b)["mutabakat_farki"] == 0


def test_ilgisiz_ayni_tutar_ceke_baglanmaz(monkeypatch):
    h, musteri, tedarikci, banka = kur()
    b = banka["id"]
    c = client.post("/api/cekler", json={"yon": "alinan", "tutar": 900, "vade": "2026-11-10", "cari_id": musteri["id"]}, headers=h).json()
    r = ekstre_yukle(monkeypatch, h, b, [
        {"tarih": "2026-11-10", "aciklama": "HAVALE DEMIR LTD", "tutar": 900, "bakiye": 1900,
         "onerilen_cari_id": tedarikci["id"], "onerilen_tur": "tahsilat"}])
    assert r["eklenen"] == 1
    assert client.get(f"/api/cekler/{c['id']}", headers=h).json()["durum"] == "portfoyde"
    onayla_hepsi(h)
    # Başka carinin parası, çek tahsil edilirken ona dokunulmaz
    islem(h, c["id"], islem="tahsil", tarih="2026-11-10", banka_hesap_id=b)
    assert bakiyeler(h)[1][b] == 2800


@pytest.mark.parametrize("islem_adi,yon", [("ciro", "alinan"), ("karsiliksiz", "alinan"), ("iade", "alinan"), ("iade", "verilen")])
def test_cekin_her_adimi_bakiyeleri_tutarli_tutar(islem_adi, yon):
    h, musteri, tedarikci, banka = kur()
    m, t = musteri["id"], tedarikci["id"]
    sahip = m if yon == "alinan" else t
    c = client.post("/api/cekler", json={"yon": yon, "tutar": 1200, "vade": "2026-12-01", "cari_id": sahip}, headers=h).json()
    once = bakiyeler(h)[0]
    assert once[sahip] == (-1200 if yon == "alinan" else 1200)
    veri = {"islem": islem_adi, "tarih": "2026-12-02"}
    if islem_adi == "ciro":
        veri["cari_id"] = t
    islem(h, c["id"], **veri)
    cari, _ = bakiyeler(h)
    beklenen = {("ciro", "alinan"): {m: -1200, t: 1200}, ("karsiliksiz", "alinan"): {m: 0},
                ("iade", "alinan"): {m: 0}, ("iade", "verilen"): {t: 0}}[(islem_adi, yon)]
    for cari_id, tutar in beklenen.items():
        assert cari.get(cari_id, 0) == tutar


def test_mutabakat_ekrani_farkin_nedenini_gosterir(monkeypatch):
    h, musteri, tedarikci, banka = kur()  # açılış 1.000
    m, b = musteri["id"], banka["id"]
    # Elle girilmiş ama bankada olmayan ödeme (yanlış hesap seçilmiş) -> fark
    client.post("/api/hareketler", json={"tarih": "2026-10-03", "yon": "cikis", "tur": "odeme", "tutar": 250,
                                         "cari_id": tedarikci["id"], "banka_hesap_id": b}, headers=h)
    ekstre_yukle(monkeypatch, h, b, [
        {"tarih": "2026-10-01", "aciklama": "EFT AHMET YAPI", "tutar": 600, "bakiye": 1600, "onerilen_cari_id": m, "onerilen_tur": "tahsilat"},
        {"tarih": "2026-10-05", "aciklama": "HAVALE", "tutar": 100, "bakiye": 1700, "onerilen_cari_id": m, "onerilen_tur": "tahsilat"}])
    eft = next(x for x in client.get("/api/hareketler?durum=taslak", headers=h).json() if x["tutar"] == 600)
    client.post("/api/hareketler/onayla", json={"sorunlular_dahil": True, "idler": [eft["id"]]}, headers=h)
    # Vadesi geçmiş, tahsil edilmemiş çek
    client.post("/api/cekler", json={"yon": "alinan", "tutar": 50, "vade": "2020-01-01", "cari_id": m}, headers=h)

    v = client.get("/api/mutabakat?tarih=2026-12-31", headers=h).json()
    bh = next(x for x in v["banka"] if x["id"] == b)
    assert (bh["ekstre_bakiye"], bh["program_bakiye"], bh["fark"]) == (1700, 1350, 350)
    nedenler = sorted((k["tutar"], k["neden"]) for k in bh["kayitlar"])
    assert nedenler == [(100, "Ekstrede var, onay bekliyor"), (250, "Programda var, ekstrede yok")]  # 100 + 250 = 350
    assert [c["tutar"] for c in v["cek"]["vadesi_gecen"]] == [50] and v["cek"]["portfoy"] == 50
    assert v["cek"]["portfoy"] == client.get("/api/raporlar/ozet", headers=h).json()["portfoy_cek"]
    cari = {c["id"]: c["bakiye"] for c in v["cari"]}
    assert cari[m] == bakiyeler(h)[0][m] == -650
    yazi = client.get(f"/api/yazdir/mutabakat-toplu?idler={m},{tedarikci['id']}&tarih=2026-12-31", headers=h).text
    assert yazi.count("CARİ HESAP MUTABAKAT MEKTUBU") == 2 and "650,00 TL" in yazi
