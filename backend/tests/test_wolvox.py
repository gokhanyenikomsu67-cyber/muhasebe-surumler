"""Wolvox'tan bir kerelik geçmiş aktarımı (sentetik veri): gruplar şantiye/depoya eşlenir, faturalar cari ve mali
raporlara karışmaz, stok adlarının yazılış farkları birleşir, aynı faturanın PDF'i ikinci kez kaydedilmez."""
import io
import json
import uuid
from datetime import datetime

from openpyxl import Workbook

from app import ai
from tests.test_api import OKUNAN, client, yeni_kullanici

BASLIK = ["Stok Adı ", "Tarihi ", "Saati ", "Fatura No ", "Ticari Unvanı ", "Birimi ", "Ara Grubu", "Grubu ", "Miktarı",
          "Miktarı 2", "Ort.Fiyat", "Tutarı", "Tutarı (KDV Dahil)", "Miktarı (İade)", "Tutarı (İade)", "Tutarı (KDV Dahil - İade)"]


def _satir(stok, tarih, no, firma, birim, grup, miktar, tutar, dahil, iade=False):
    t = datetime.strptime(tarih, "%d.%m.%Y")
    if iade:
        return [stok, t, None, no, firma, birim, None, grup, None, None, None, None, None, miktar, tutar, dahil]
    return [stok, t, None, no, firma, birim, None, grup, miktar, None, None, tutar, dahil, None, None, None]


def _excel():
    wb = Workbook()
    ws = wb.active
    ws.title = "Temp1"
    ws.append(BASLIK)
    for r in [
        _satir("3x25 NYA KABLO", "05.01.2025", "DNM2025000000001", "Örnek Elektrik Ltd.", "METRE", "DENEME ŞANTİYE", 100, 1000, 1200),
        _satir("3x25 nya kablo-", "05.01.2025", "DNM2025000000001", "Örnek Elektrik Ltd.", "METRE", "TAŞARON USTA DENEME ŞANTİYE", 50, 500, 600),
        _satir("ÇİMENTO 50 KG", "10.02.2025", '="0000123"', "Deneme Yapı Market", "ADET", "DENEME SANTİYE", 10, 900, 1080),
        _satir("Kum", "10.02.2025", '="0000123"', "Deneme Yapı Market", "TON", None, 2, 400, 480),
        _satir("ÇİMENTO 50 KG", "11.02.2025", "AFS2025000000009", "Deneme Yapı Market", "ADET", "DENEME ŞANTİYE", 1, 90, 108, iade=True),
        _satir("BETON C30", "01.03.2025", "XYZ2025000000077", "Örnek Beton A.Ş.", "M3", "BAŞKA İŞ", 5, 10000, 12000),
    ]:
        ws.append(r)
    for c in ws["D"]:
        c.data_type = "s"  # Wolvox fatura no'yu '="0000123"' yazısı olarak verir (formül değil)
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


def test_wolvox_aktarimi(monkeypatch):
    h = yeni_kullanici(f"{uuid.uuid4().hex}@ornek.com")
    dosya = _excel()
    o = client.post("/api/wolvox/onizle", files={"dosya": ("w.xlsx", dosya)}, headers=h).json()
    assert (o["fatura_sayisi"], o["aktarilacak"], o["iade_sayisi"], o["kalem_sayisi"]) == (4, 4, 1, 6)
    gruplar = {g["grup"]: g for g in o["gruplar"]}
    assert gruplar["TAŞARON USTA DENEME ŞANTİYE"]["oneri"] == {"tur": "depo", "ad": "TAŞARON USTA DENEME ŞANTİYE", "santiye": "DENEME ŞANTİYE"}
    assert gruplar["BAŞKA İŞ"]["oneri"]["tur"] == "santiye" and gruplar[""]["oneri"]["tur"] == "yok"
    # "DENEME SANTİYE" ile "DENEME ŞANTİYE" zaten aynı ad sayılır (Türkçe harf farkı); başka grup kullanıcının yazdığı adla birleşir
    kararlar = {"BAŞKA İŞ": {"tur": "santiye", "ad": "Deneme Şantiye", "santiye": ""}}
    r = client.post("/api/wolvox/aktar", files={"dosya": ("w.xlsx", dosya)}, data={"eslesme": json.dumps(kararlar)}, headers=h).json()
    assert (r["fatura_sayisi"], r["atlanan"], r["acilan_santiye"], r["acilan_depo"]) == (4, 0, 1, 1)

    # Cari açılmaz, cari bakiyesine ve faturalar listesine karışmaz; kendi süzgeciyle listelenir
    assert client.get("/api/cariler", headers=h).json() == []
    assert client.get("/api/faturalar?durum=kayitli", headers=h).json() == []
    assert len(client.get("/api/faturalar?yon=gelen", headers=h).json()) == 3  # tüm faturalarda "Wolvox" etiketiyle görünür
    aktarilan = client.get("/api/faturalar?durum=aktarim", headers=h).json()
    assert sorted(f["fatura_no"] for f in aktarilan) == ["0000123", "AFS2025000000009", "DNM2025000000001", "XYZ2025000000077"]
    f1 = next(f for f in aktarilan if f["fatura_no"] == "DNM2025000000001")
    assert f1["genel_toplam"] == 1800 and f1["kalemler"][0]["kdv_orani"] == 20
    assert client.post(f"/api/faturalar/{f1['id']}/onayla", headers=h).status_code == 400

    # Şantiye raporu: aktarılan giderler (iade düşer); depo raporu taşeron grubunu gösterir
    ozet = {s["ad"]: s for s in client.get("/api/raporlar/santiye-ozet", headers=h).json()}
    assert len(ozet) == 1 and ozet["Deneme Şantiye"]["gider"] == 1200 + 600 + 1080 - 108 + 12000
    depo = client.get("/api/raporlar/depo-harcamalari", headers=h).json()
    assert [(x["depo"], x["kaynak"], x["toplam"]) for x in depo] == [("TAŞARON USTA DENEME ŞANTİYE", "Wolvox aktarımı", 600)]
    fs = client.get("/api/raporlar/santiye-faturalari", headers=h).json()
    assert {x["cari"] for x in fs} >= {"Örnek Elektrik Ltd.", "Örnek Beton A.Ş."}

    # Stok adlarının yazılış farkı ("3x25 NYA KABLO" / "3x25 nya kablo-") tek malzeme kartı
    rapor = {x["malzeme"]: x for x in client.get("/api/raporlar/malzeme", headers=h).json()["ozet"]}
    assert rapor["3x25 NYA KABLO"]["miktar"] == 150

    # Aynı dosya ikinci kez aktarılınca hepsi atlanır
    r2 = client.post("/api/wolvox/aktar", files={"dosya": ("w.xlsx", dosya)}, headers=h).json()
    assert (r2["fatura_sayisi"], r2["atlanan"]) == (0, 4)

    # Aynı faturanın PDF'i yüklenince ikinci kez kaydedilmez, cari açılmaz, "zaten var" döner
    monkeypatch.setattr(ai, "fatura_oku", lambda *a, **kw: {**OKUNAN, "fatura_no": "XYZ2025000000077", "tarih": "2025-03-01",
                                                            "genel_toplam": 12000})
    f = client.post("/api/faturalar/oku?yontem=ai", files={"dosya": ("f.pdf", b"%PDF-1.4 w", "application/pdf")}, headers=h).json()[0]
    assert f["zaten_var"] is True and f["durum"] == "aktarim"
    assert client.get("/api/cariler", headers=h).json() == []

    # Geri alma: faturalar ve açılan şantiye/depo silinir
    gecmis = client.get("/api/wolvox/aktarimlar", headers=h).json()
    for a in gecmis:
        client.delete(f"/api/wolvox/aktarimlar/{a['id']}", headers=h)
    assert client.get("/api/faturalar?durum=aktarim", headers=h).json() == []
    assert client.get("/api/santiyeler", headers=h).json() == [] and client.get("/api/depolar", headers=h).json() == []


def test_santiye_birlestirme_ve_depoya_cevirme():
    h = yeni_kullanici(f"{uuid.uuid4().hex}@ornek.com")
    client.post("/api/wolvox/aktar", files={"dosya": ("w.xlsx", _excel())}, headers=h)
    s = {x["ad"].replace("SANTİYE", "ŞANTİYE"): x["id"] for x in client.get("/api/santiyeler", headers=h).json()}
    assert set(s) == {"DENEME ŞANTİYE", "BAŞKA İŞ"}  # "DENEME SANTİYE" ile aynı şantiye
    c = client.post("/api/cariler", json={"unvan": "Deneme Usta"}, headers=h).json()
    hr = client.post("/api/hareketler", json={"tarih": "2025-04-01", "yon": "cikis", "tur": "masraf", "tutar": 50,
                                              "santiye_id": s["BAŞKA İŞ"], "cari_id": c["id"]}, headers=h)
    # "BAŞKA İŞ" taşeron deposu olur: kalemleri depoya, hareketi şantiyeye geçer
    r = client.post(f"/api/santiyeler/{s['BAŞKA İŞ']}/depoya-cevir", json={"santiye_id": s["DENEME ŞANTİYE"]}, headers=h).json()
    assert (r["depo"], r["kalem_sayisi"]) == ("BAŞKA İŞ", 1)
    assert [x["id"] for x in client.get("/api/santiyeler", headers=h).json()] == [s["DENEME ŞANTİYE"]]
    depo = client.get("/api/raporlar/depo-harcamalari", headers=h).json()
    assert {(x["depo"], x["toplam"]) for x in depo} == {("BAŞKA İŞ", 12000), ("TAŞARON USTA DENEME ŞANTİYE", 600)}
    if hr.status_code == 200:
        assert client.get(f"/api/hareketler/{hr.json()['id']}", headers=h).json().get("santiye_id") in (s["DENEME ŞANTİYE"], None)

    # İki şantiye birleşir: kayıtlar hedefe geçer, eski ad saklanır
    yeni = client.post("/api/santiyeler", json={"ad": "Deneme Şantiye 2"}, headers=h).json()
    f = client.get("/api/faturalar?durum=aktarim", headers=h).json()[0]
    kalemler = [{**{k: v for k, v in kl.items() if k != "id"}, "santiye_id": yeni["id"]} for kl in f["kalemler"]]
    client.put(f"/api/faturalar/{f['id']}", json={**{k: f[k] for k in ("yon", "fatura_no", "tarih")}, "kalemler": kalemler}, headers=h)
    m = client.post(f"/api/santiyeler/{s['DENEME ŞANTİYE']}/birlestir", json={"idler": [yeni["id"]]}, headers=h).json()
    assert "Deneme Şantiye 2" in m["eski_adlar"].split("\n")
    assert [x["id"] for x in client.get("/api/santiyeler", headers=h).json()] == [s["DENEME ŞANTİYE"]]
    ozet = client.get("/api/raporlar/santiye-ozet", headers=h).json()
    assert len(ozet) == 1 and ozet[0]["gider"] == 1200 + 600 + 1080 - 108 + 12000 + 50
    # Eski adla açılmak istenen şantiye birleşen kayda gider
    assert client.post("/api/santiyeler", json={"ad": "deneme şantiye 2"}, headers=h).json()["id"] == s["DENEME ŞANTİYE"]


def test_santiye_ve_depo_aktif_pasif():
    h = yeni_kullanici(f"{uuid.uuid4().hex}@ornek.com")
    s = client.post("/api/santiyeler", json={"ad": "Deneme Pasif"}, headers=h).json()
    d = client.post("/api/depolar", json={"ad": "Deneme Usta", "santiye_id": s["id"]}, headers=h).json()
    assert client.post("/api/santiyeler/durum", json={"idler": [s["id"]], "durum": "pasif"}, headers=h).status_code == 200
    assert client.post("/api/depolar/durum", json={"idler": [d["id"]], "durum": "pasif"}, headers=h).status_code == 200
    assert [x["durum"] for x in client.get("/api/santiyeler", headers=h).json()] == ["pasif"]
    assert [x["durum"] for x in client.get("/api/depolar", headers=h).json()] == ["pasif"]
    assert client.post("/api/santiyeler/durum", json={"idler": [s["id"]], "durum": "sil"}, headers=h).status_code == 422
    client.post("/api/santiyeler/durum", json={"idler": [s["id"]], "durum": "aktif"}, headers=h)
    assert client.get("/api/santiyeler", headers=h).json()[0]["durum"] == "aktif"
