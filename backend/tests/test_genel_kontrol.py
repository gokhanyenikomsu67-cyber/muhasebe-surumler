"""Genel kod kontrolünde bulunan hataların testleri."""
import io
import uuid

from openpyxl import Workbook

from app import kural
from app.routers.banka import eskiden_yeniye
from tests.test_api import client, yeni_kullanici


def yeni():
    return yeni_kullanici(f"{uuid.uuid4().hex}@ornek.com")


BASLIK = ";;;;;\nİŞLEM TARİHİ;BİM REF   ;TUTAR   ;B/A;BAKİYE   ;AÇIKLAMA\n"


def ekstre_yukle(h, hesap_id, satirlar, iban="TR980001200999900010101594"):
    metin = f"IBAN No:   ;{iban};;;;;\n" + BASLIK + satirlar
    return client.post(f"/api/banka-hesaplari/{hesap_id}/ekstre?yontem=kural",
                       files={"dosya": ("e.csv", metin.encode("cp1254"), "text/csv")}, headers=h).json()


def test_kasadaki_nakit_cekim_karsiligi_tek_basina_silinmez():
    """Bankadaki nakit çekimin kasadaki karşılığı tek başına silinip değiştirilemez (kasa bankayla çelişmesin);
    bankadaki hareket silinince kasadaki de gider."""
    h = yeni()
    a = client.post("/api/banka-hesaplari", json={"ad": "Halkbank 94", "banka": "Halkbank"}, headers=h).json()
    ekstre_yukle(h, a["id"], "03.10.2026;r3;200,00;B;500,00;NAKİT ÇEKİLEN\n")
    taslak = client.get("/api/hareketler?durum=taslak", headers=h).json()
    client.post("/api/hareketler/onayla", json={"idler": [x["id"] for x in taslak]}, headers=h)
    kasa = client.get("/api/kasa", headers=h).json()
    assert kasa["bakiye"] == 200
    karsilik = kasa["hareketler"][0]
    assert client.delete(f"/api/hareketler/{karsilik['id']}", headers=h).status_code == 400
    v = {a: karsilik[a] for a in ("tarih", "yon", "tur", "tutar")}
    assert client.put(f"/api/hareketler/{karsilik['id']}", json={**v, "tutar": 1}, headers=h).status_code == 400
    r = client.post("/api/hareketler/toplu-sil", json={"idler": [karsilik["id"]]}, headers=h).json()
    assert r["silinen"] == 0 and len(r["silinmeyen"]) == 1
    assert client.get("/api/kasa", headers=h).json()["bakiye"] == 200
    # Bankadaki hareketle birlikte seçilince ikisi de silinir
    banka_hareketi = client.get(f"/api/hareketler?banka_hesap_id={a['id']}", headers=h).json()[0]
    r = client.post("/api/hareketler/toplu-sil", json={"idler": [karsilik["id"], banka_hareketi["id"]]}, headers=h).json()
    assert r["silinmeyen"] == []
    assert client.get("/api/kasa", headers=h).json() == {"bakiye": 0, "hareketler": []}
    assert client.get(f"/api/hareketler?banka_hesap_id={a['id']}", headers=h).json() == []


def test_ekstreden_ayni_adli_cari_ikinci_kez_acilmaz():
    """Açıklamadaki ad birden çok cariye benzediğinde (eşleştirme belirsiz) aynı adlı cari varsa ona işlenir."""
    h = yeni()
    var = client.post("/api/cariler", json={"unvan": "Gelen Firma Ltd"}, headers=h).json()
    client.post("/api/cariler", json={"unvan": "Gelen Firma Beton Ltd"}, headers=h)
    a = client.post("/api/banka-hesaplari", json={"ad": "Halkbank 94"}, headers=h).json()
    r = ekstre_yukle(h, a["id"], "01.10.2026;r1;1.000,00;A;1.000,00;Gelen Firma Ltd,GELEN FİRMA LTD 'DAN ödeme\n")
    assert r["eklenen"] == 1 and r["yeni_cari"] == 0, r
    assert client.get("/api/hareketler?durum=taslak", headers=h).json()[0]["cari_id"] == var["id"]
    assert len(client.get("/api/cariler", headers=h).json()) == 2


def test_ayni_gun_yeniden_eskiye_ekstre_bakiyesi_dogru():
    """Tek günlük ekstre yeniden eskiye sıralıysa son bakiye en yeni satırdan alınır (sahte mutabakat farkı çıkmaz)."""
    satirlar = [{"tarih": "2026-10-05", "tutar": -100, "bakiye": 900}, {"tarih": "2026-10-05", "tutar": 1000, "bakiye": 1000}]
    assert eskiden_yeniye(satirlar) == satirlar[::-1]
    assert eskiden_yeniye(satirlar[::-1]) == satirlar[::-1]
    h = yeni()
    a = client.post("/api/banka-hesaplari", json={"ad": "Halkbank 94"}, headers=h).json()
    ekstre_yukle(h, a["id"], "05.10.2026;r2;100,00;B;900,00;EFT MASRAFI\n"
                             "05.10.2026;r1;1.000,00;A;1.000,00;Gelen Firma Ltd,GELEN FİRMA LTD 'DAN ödeme\n")
    client.post("/api/hareketler/onayla", json={"idler": [x["id"] for x in client.get("/api/hareketler?durum=taslak", headers=h).json()]},
                headers=h)
    b = next(x for x in client.get("/api/banka-hesaplari", headers=h).json() if x["id"] == a["id"])
    assert (b["ekstre_bakiye"], b["bakiye"], b["mutabakat_farki"]) == (900, 900, 0)


def test_tireli_yazilan_iban_ayni_hesap_sayilir():
    """Hesap kartına IBAN tire/boşlukla yazılmışsa ekstre başka (yeni açılan) hesaba işlenmez."""
    assert kural.iban_uyar("TR98-0001-2009-9990-0010-1015-94", "TR980001200999900010101594")
    h = yeni()
    a = client.post("/api/banka-hesaplari", json={"ad": "Halkbank 94", "iban": "TR98-0001-2009-9990-0010-1015-94"}, headers=h).json()
    r = ekstre_yukle(h, a["id"], "01.10.2026;r1;1.000,00;A;1.000,00;Gelen Firma Ltd,GELEN FİRMA LTD 'DAN ödeme\n")
    assert r["hesap"] == "Halkbank 94" and r["yeni_hesap"] == []
    assert len(client.get("/api/banka-hesaplari", headers=h).json()) == 1


def test_kendi_firmamiza_bagli_eski_taslak_onaylanmaz():
    h = yeni()
    c = client.post("/api/cariler", json={"unvan": "Bir Firma", "vkn": "9999999999"}, headers=h).json()
    f = client.post("/api/faturalar", json={"yon": "gelen", "fatura_no": "F1", "cari_id": c["id"],
                                           "kalemler": [{"aciklama": "x", "birim_fiyat": 100}]}, headers=h).json()
    client.put("/api/sirket", json={"unvan": "Test İnşaat", "vkn": "9999999999"}, headers=h)
    r = client.post(f"/api/faturalar/{f['id']}/onayla", headers=h)
    assert r.status_code == 400 and "Kendi firmanız" in r.json()["detail"]
    assert client.post("/api/faturalar/toplu-onayla", json={"idler": [f["id"]]}, headers=h).json()["onaylanan"] == 0


def test_cari_duzenlenirken_baska_carinin_vknsi_verilemez():
    h = yeni()
    client.post("/api/cariler", json={"unvan": "Birinci Ltd", "vkn": "1111111111"}, headers=h)
    b = client.post("/api/cariler", json={"unvan": "İkinci Ltd"}, headers=h).json()
    r = client.put(f"/api/cariler/{b['id']}", json={"unvan": "İkinci Ltd", "vkn": "1111111111"}, headers=h)
    assert r.status_code == 409 and "Birinci Ltd" in r.json()["detail"]
    assert client.put(f"/api/cariler/{b['id']}", json={"unvan": "İkinci Ltd", "vkn": "2222222222"}, headers=h).status_code == 200


def test_excelden_cari_yuklemede_tekrar_ve_kendi_firmamiz_eklenmez():
    h = yeni()
    client.put("/api/sirket", json={"unvan": "Test İnşaat", "vkn": "9999999999"}, headers=h)
    client.post("/api/cariler", json={"unvan": "Yılmaz Beton Ltd. Şti."}, headers=h)
    wb = Workbook()
    ws = wb.active
    ws.append(["Ünvan", "Tür", "VKN/TCKN"])
    for satir in (["YILMAZ BETON LTD", None, None], ["Kendimiz", None, "9999999999"], ["Yeni Firma", "musteri", "3333333333"],
                  ["Yeni Firma Kopya", None, "3333333333"], ["Usta Ali", "bilinmeyen", None]):
        ws.append(satir)
    tampon = io.BytesIO()
    wb.save(tampon)
    r = client.post("/api/excel/cariler/yukle", files={"dosya": ("c.xlsx", tampon.getvalue())}, headers=h).json()
    assert (r["eklenen"], r["atlanan"]) == (2, 3)
    cariler = {c["unvan"]: c for c in client.get("/api/cariler", headers=h).json()}
    assert set(cariler) == {"Yılmaz Beton Ltd. Şti.", "Yeni Firma", "Usta Ali"}
    assert cariler["Usta Ali"]["tur"] == "tedarikci"


def test_sonraki_onarimlarda_kullanicinin_verdigi_cari_adi_degismez():
    """Şirket eki taşımayan cari adını belgeden düzeltme yalnız ilk onarımda yapılır; kullanıcının verdiği ad sonra korunur."""
    from app import onarim
    from app.db import SessionLocal
    from app.models import Fatura, Sirket
    from tests.test_efatura import pdf_olustur
    h = yeni()
    client.put("/api/sirket", json={"unvan": "Deneme İnşaat Ltd.", "vkn": "9999999999"}, headers=h)
    c = client.post("/api/cariler", json={"unvan": "Elektrikçi Hasan", "vkn": "1234567890"}, headers=h).json()
    pdf = pdf_olustur(["ORNEK GRUP ELEKTRIK", "TEKS.SAN.TIC.LTD.STI.", "VKN: 1234567890", "SAYIN", "DENEME INSAAT LTD",
                       "VKN: 9999999999", "Fatura No: NVC2026000000019", "Fatura Tarihi: 03-08-2026",
                       "Sira No Mal Hizmet Miktar Birim Fiyat KDV Orani KDV Tutari Mal Hizmet Tutari",
                       "1 PIGTAIL 15MT 25 Adet 95,000000TL %20,00 475,00TL 2.375,00TL", "Mal Hizmet Toplam Tutari 2.375,00TL",
                       "Hesaplanan KDV(%20) 475,00TL", "Odenecek Tutar 2.850,00TL"])
    f = client.post("/api/faturalar/oku", files={"dosya": ("n.pdf", pdf, "application/pdf")}, headers=h).json()[0]
    assert f["cari_id"] == c["id"]
    with SessionLocal() as db:
        rapor = onarim.onar(db, db.get(Sirket, db.get(Fatura, f["id"]).sirket_id), eski_surum=12)
    assert rapor["duzelen_cariler"] == []
    assert next(x for x in client.get("/api/cariler", headers=h).json() if x["id"] == c["id"])["unvan"] == "Elektrikçi Hasan"


def test_ayni_firmanin_faturalari_ayni_anda_yuklenince_cari_bir_kez_acilir(monkeypatch):
    """Toplu yüklemede dosyalar aynı anda okunur; aynı firmanın iki faturası tek cariye işlenir, hata vermez."""
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from tests.test_efatura import ubl
    gercek = kural.efatura_xml_oku
    bekle = threading.Barrier(2, timeout=5)

    def yavas(*a, **k):  # iki dosya da okunmuş olsun, sonra ikisi birden kaydetmeye çalışsın
        sonuc = gercek(*a, **k)
        bekle.wait()
        return sonuc
    monkeypatch.setattr(kural, "efatura_xml_oku", yavas)
    h = yeni()
    client.put("/api/sirket", json={"unvan": "Test İnşaat", "vkn": "9999999999"}, headers=h)
    yukle = lambda no: client.post("/api/faturalar/oku", files={"dosya": (f"{no}.xml", ubl(no=no), "application/xml")},  # noqa: E731
                                   headers=h)
    with ThreadPoolExecutor(2) as havuz:
        sonuclar = list(havuz.map(yukle, ["ORN2026000000101", "ORN2026000000102"]))
    assert [r.status_code for r in sonuclar] == [200, 200], [r.text for r in sonuclar]
    cariler = client.get("/api/cariler", headers=h).json()
    assert len(cariler) == 1
    assert {f["cari_id"] for f in client.get("/api/faturalar?durum=taslak", headers=h).json()} == {cariler[0]["id"]}


def test_eski_yedeklerden_her_ayin_sonuncusu_kalir(tmp_path):
    import os
    import time

    from app import yedek
    eski = time.time() - 90 * 86400
    adlar = ["muhasebe-yedek-20260701-090000.zip", "muhasebe-yedek-20260715-090000.zip", "muhasebe-yedek-20260731-180000.zip",
             "muhasebe-yedek-20260802-090000.zip"]
    for ad in adlar:
        (tmp_path / ad).write_bytes(b"x")
        os.utime(tmp_path / ad, (eski, eski))
    yeni_yedek = tmp_path / "muhasebe-yedek-20261019-090000.zip"
    yeni_yedek.write_bytes(b"x")
    yedek.eskileri_sil(tmp_path)
    assert sorted(d.name for d in tmp_path.iterdir()) == [adlar[2], adlar[3], yeni_yedek.name]


def test_onarimdan_once_yedek_alinir(monkeypatch, tmp_path):
    from app import onarim, yedek
    h = yeni()
    client.post("/api/faturalar", json={"yon": "gelen", "fatura_no": "Y1", "kalemler": [{"aciklama": "x", "birim_fiyat": 1}]}, headers=h)
    alinan, sira = [], []
    monkeypatch.setattr(yedek, "yedek_al", lambda: (alinan.append(1), sira.append("yedek")))
    monkeypatch.setattr(onarim, "RAPOR", tmp_path / "onarim-raporu.json")
    gercek = onarim.onar
    monkeypatch.setattr(onarim, "onar", lambda *a: (sira.append("onar"), gercek(*a))[1])
    onarim.baslangicta_onar()
    assert alinan and sira[0] == "yedek" and "onar" in sira
    # Yedek alınamazsa onarım yapılmaz, sonraki açılışa kalır
    (tmp_path / "onarim-raporu.json").unlink()
    sira.clear()

    def hata():
        raise OSError("disk dolu")
    monkeypatch.setattr(yedek, "yedek_al", hata)
    onarim.baslangicta_onar()
    assert sira == [] and not (tmp_path / "onarim-raporu.json").exists()


def test_dovizli_fatura_raporlara_tl_karsiligiyla_girer():
    h = yeni()
    c = client.post("/api/cariler", json={"unvan": "Avrupa Makine GmbH"}, headers=h).json()
    veri = {"yon": "gelen", "fatura_no": "EUR1", "tarih": "2026-10-01", "cari_id": c["id"], "para_birimi": "EUR",
            "gider_turu": "Makine kiralama", "kalemler": [{"aciklama": "Kiralama", "birim_fiyat": 1000, "kdv_orani": 20}]}
    f = client.post("/api/faturalar", json=veri, headers=h).json()
    r = client.post(f"/api/faturalar/{f['id']}/onayla", headers=h)
    assert r.status_code == 400 and "kur" in r.json()["detail"]
    client.put(f"/api/faturalar/{f['id']}", json={**veri, "kur": 35.5}, headers=h)
    assert client.post(f"/api/faturalar/{f['id']}/onayla", headers=h).status_code == 200
    bakiye = next(x for x in client.get("/api/raporlar/cari-bakiye", headers=h).json() if x["id"] == c["id"])
    assert bakiye["bakiye"] == -42600  # 1.200 EUR x 35,5
    ekim = client.get("/api/raporlar/kdv?yil=2026", headers=h).json()["aylar"][9]
    assert (ekim["alis_matrah"], ekim["indirilecek"]) == (35500, 7100)
    gg = client.get("/api/raporlar/gelir-gider?yil=2026", headers=h).json()
    assert gg["gider_toplam"][9] == 35500
    assert client.get("/api/raporlar/ba-bs?yil=2026&ay=10", headers=h).json()["ba"][0]["tutar"] == 35500


def test_dovizli_xml_faturanin_kuru_okunur():
    from tests.test_efatura import ubl
    x = ubl().decode().replace("<cbc:DocumentCurrencyCode>TRY</cbc:DocumentCurrencyCode>",
                      "<cbc:DocumentCurrencyCode>USD</cbc:DocumentCurrencyCode><cac:PricingExchangeRate>"
                      "<cbc:SourceCurrencyCode>USD</cbc:SourceCurrencyCode><cbc:TargetCurrencyCode>TRY</cbc:TargetCurrencyCode>"
                      "<cbc:CalculationRate>41.25</cbc:CalculationRate></cac:PricingExchangeRate>").encode()
    h = yeni()
    f = client.post("/api/faturalar/oku", files={"dosya": ("d.xml", x, "application/xml")}, headers=h).json()[0]
    assert (f["para_birimi"], f["kur"]) == ("USD", 41.25)


def test_iade_faturasi_raporlarda_ters_islenir():
    """Müşteriden gelen iade satışı ve hesaplanan KDV'yi azaltır, satış geliri sayılmaz."""
    h = yeni()
    m = client.post("/api/cariler", json={"unvan": "Müşteri Ltd", "tur": "musteri"}, headers=h).json()
    def fatura(yon, no, tutar, tip=None):
        f = client.post("/api/faturalar", json={"yon": yon, "fatura_no": no, "tarih": "2026-10-05", "cari_id": m["id"], "fatura_tipi": tip,
                                                "kalemler": [{"aciklama": "Daire", "birim_fiyat": tutar, "kdv_orani": 20}]}, headers=h).json()
        assert client.post(f"/api/faturalar/{f['id']}/onayla", headers=h).status_code == 200
        return f
    fatura("giden", "S1", 10000)
    fatura("gelen", "IADE1", 1000, "iade")
    ekim = client.get("/api/raporlar/kdv?yil=2026", headers=h).json()["aylar"][9]
    assert (ekim["satis_matrah"], ekim["hesaplanan"], ekim["alis_matrah"], ekim["indirilecek"]) == (9000, 1800, 0, 0)
    gg = client.get("/api/raporlar/gelir-gider?yil=2026", headers=h).json()
    assert gg["gelir"][9] == 9000 and gg["gider_toplam"][9] == 0
    # Cari bakiye: müşteri 12.000 borçlu, iade 1.200 düşer
    assert next(x for x in client.get("/api/raporlar/cari-bakiye", headers=h).json() if x["id"] == m["id"])["bakiye"] == 10800
