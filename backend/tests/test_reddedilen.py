"""Reddedilen faturalar: yüklemede kaydedilmez, listede tutulur, kayıtlı olan iptal edilir (sentetik veri)."""
import io
import zipfile

from app import kural
from tests.test_api import client
from tests.test_efatura import ubl
from tests.test_kural import pdf_olustur, yeni


def red_yaniti(no, uuid, kod="RED"):
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<ApplicationResponse xmlns="urn:oasis:names:specification:ubl:schema:xsd:ApplicationResponse-2"
 xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
 xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
 <cbc:ID>YNT2026000000001</cbc:ID>
 <cac:DocumentResponse><cac:Response><cbc:ReferenceID>x</cbc:ReferenceID><cbc:ResponseCode>{kod}</cbc:ResponseCode>
  <cbc:Description>Fiyat hatalı</cbc:Description></cac:Response>
  <cac:DocumentReference><cbc:ID>{no}</cbc:ID><cbc:UUID>{uuid}</cbc:UUID></cac:DocumentReference>
 </cac:DocumentResponse></ApplicationResponse>""".encode()


def yukle(h, ad, veri, tur="application/pdf", **param):
    q = "&".join(f"{k}={v}" for k, v in param.items())
    return client.post(f"/api/faturalar/oku?{q}", files={"dosya": (ad, veri, tur)}, headers=h)


def test_red_yazisi_taninir_kelime_icindeki_red_sayilmaz():
    assert kural.red_isareti("FATURA\nREDDEDİLDİ\nToplam 100,00")
    assert kural.red_isareti("Bu fatura alıcı tarafından iptal edilmiştir.")
    assert kural.red_isareti("RED")
    assert not kural.red_isareti("EDENRED KURUMSAL ÇÖZÜMLER\nÖdeme: Kredi Kartı\nRet süresi 8 gündür")
    assert kural.ettn_bul("ETTN: A0EB8308-0000-4000-8000-000000000097") == "a0eb8308-0000-4000-8000-000000000097"
    assert kural.red_yanitlari(red_yaniti("ORN1", "U-1")) == {"orn1", "u-1"}
    assert kural.red_yanitlari(red_yaniti("ORN1", "U-1", "KABUL")) == set()
    assert kural.red_yanitlari(ubl()) is None


def test_pdf_ustunde_red_yazisi_varsa_kaydedilmez():
    h = yeni()
    pdf = pdf_olustur(["ORNEK ELEKTRIK MALZEMELERI A.S.", "VKN: 1234567890", "SAYIN DENEME INSAAT", "VKN: 9999999999",
                       "Fatura No: ORN2026000000005", "Fatura Tarihi: 15-09-2026", "Mal Hizmet Toplam Tutari 1.000,00 TL",
                       "Hesaplanan KDV (%20) 200,00 TL", "Odenecek Tutar 1.200,00 TL", "REDDEDILDI"])
    r = yukle(h, "f.pdf", pdf).json()
    assert len(r) == 1 and r[0]["reddedildi"] and r[0]["fatura_no"] == "ORN2026000000005" and r[0]["genel_toplam"] == 1200
    assert client.get("/api/faturalar?yon=gelen&durum=taslak", headers=h).json() == []
    assert [x["fatura_no"] for x in client.get("/api/reddedilen-faturalar", headers=h).json()] == ["ORN2026000000005"]


def test_zipteki_red_yaniti_faturayi_atlatir_digerleri_kaydedilir():
    t = io.BytesIO()
    with zipfile.ZipFile(t, "w") as z:
        z.writestr("ORN1.xml", ubl("ORN2026000000001"))
        z.writestr("ORN2.xml", ubl("ORN2026000000002"))
        z.writestr("yanit.xml", red_yaniti("ORN2026000000002", "3f1c0a2e-0000-4000-8000-026000000002"))
    h = yeni()
    r = yukle(h, "toplu.zip", t.getvalue(), "application/zip").json()
    assert [(f["fatura_no"], bool(f.get("reddedildi"))) for f in r] == [("ORN2026000000001", False), ("ORN2026000000002", True)]
    assert r[1]["cari_unvan"].startswith("Örnek Elektrik")


def test_reddedilenler_yuklenince_sonraki_yuklemede_atlanir_kayitli_olan_iptal_edilir():
    h = yeni()
    # Biri önceden onaylanmış, biri taslakta bekliyor
    onayli = yukle(h, "a.xml", ubl("ORN2026000000011"), "text/xml").json()[0]
    assert client.post(f"/api/faturalar/{onayli['id']}/onayla", headers=h).status_code == 200
    taslak = yukle(h, "b.xml", ubl("ORN2026000000012"), "text/xml").json()[0]
    # Kullanıcı portaldan indirdiği reddedilen faturaları "Reddedilen faturaları yükle" ile verir
    r1 = yukle(h, "a.xml", ubl("ORN2026000000011"), "text/xml", reddedilen="true").json()[0]
    r2 = yukle(h, "b.xml", ubl("ORN2026000000012"), "text/xml", reddedilen="true").json()[0]
    r3 = yukle(h, "c.xml", ubl("ORN2026000000013"), "text/xml", reddedilen="true").json()[0]
    assert r1["reddedildi"] and r1["kayitli_id"] == onayli["id"]
    assert r2["taslak_silindi"] and client.get(f"/api/faturalar/{taslak['id']}", headers=h).status_code == 404
    assert r3["kayitli_id"] is None and not r3["taslak_silindi"]
    # Aynı fatura sonradan normal yüklenirse kaydedilmez
    assert yukle(h, "c.xml", ubl("ORN2026000000013"), "text/xml").json()[0]["reddedildi"]
    assert client.get("/api/faturalar?yon=gelen&durum=taslak", headers=h).json() == []
    liste = client.get("/api/reddedilen-faturalar", headers=h).json()
    assert len(liste) == 3 and next(x for x in liste if x["fatura_no"].endswith("11"))["kayitli_id"] == onayli["id"]
    # Önerilen iptal: bakiyeden düşer, kayıt silinmez
    assert client.post("/api/reddedilen-faturalar/iptal-et", json={"idler": [onayli["id"]]}, headers=h).json()["iptal_edilen"] == 1
    f = client.get(f"/api/faturalar/{onayli['id']}", headers=h).json()
    assert f["durum"] == "iptal" and "reddetti" in f["iptal_nedeni"]
    # Yanlışlıkla listeye giren fatura listeden çıkarılınca normal yüklenir
    c = next(x for x in liste if x["fatura_no"].endswith("13"))
    client.delete(f"/api/reddedilen-faturalar/{c['id']}", headers=h)
    assert not yukle(h, "c.xml", ubl("ORN2026000000013"), "text/xml").json()[0].get("reddedildi")


def test_reddedilen_listesi_firmaya_ozel():
    h1, h2 = yeni(), yeni()
    yukle(h1, "a.xml", ubl("ORN2026000000021"), "text/xml", reddedilen="true")
    assert client.get("/api/reddedilen-faturalar", headers=h2).json() == []
    assert not yukle(h2, "a.xml", ubl("ORN2026000000021"), "text/xml").json()[0].get("reddedildi")
    rid = client.get("/api/reddedilen-faturalar", headers=h1).json()[0]["id"]
    assert client.delete(f"/api/reddedilen-faturalar/{rid}", headers=h2).status_code == 404
