import uuid

import pytest

from app import kart
from tests.test_api import client, yeni_kullanici

OZET = ["HALKBANK PARAF KREDİ KARTI HESAP ÖZETİ", "Kart Numarası;5528 79** **** 1234", "Hesap Kesim Tarihi;05.10.2026",
        "Son Ödeme Tarihi;15.10.2026", "Dönem Borcu;{borc}", "Asgari Ödeme Tutarı;1.176,00", "Önceki Dönem Borcu;3.000,00", ""]
EYLUL = ["İşlem Tarihi;Açıklama;Tutar;ParafPara",
         "08.09.2026;HESAPTAN OTOMATİK ÖDEME;-3.000,00;",
         "10.09.2026;MIGROS 4512 GEBZE KOCAELI TR;1.250,00;2,50",
         "12.09.2026;KOÇTAŞ GEBZE 2/6 TAKSİT;1.000,00;",
         "15.09.2026;IYZICO*TRENDYOL ISTANBUL;680,00;",
         "15.09.2026;IYZICO*TRENDYOL ISTANBUL;680,00;",
         "20.09.2026;SHELL ÇAYIROVA KOCAELI;2.000,00;",
         "22.09.2026;MIGROS 4512 GEBZE KOCAELI İADE;-250,00;",
         "25.09.2026;NAKİT AVANS ATM;500,00;",
         "30.09.2026;YILLIK KART ÜCRETİ;195,00;",
         "30.09.2026;BSMV;5,00;"]


def csv(satirlar, borc="6.060,00"):
    return "\n".join(OZET + satirlar).replace("{borc}", borc).encode("cp1254")


def kur():
    h = yeni_kullanici(f"{uuid.uuid4().hex}@ornek.com")
    migros = client.post("/api/cariler", json={"unvan": "MİGROS TİCARET A.Ş."}, headers=h).json()
    banka = client.post("/api/banka-hesaplari", json={"ad": "Halkbank TL", "banka": "Halkbank"}, headers=h).json()
    return h, migros, banka


def hesaplar(h):
    return {b["ad"]: b for b in client.get("/api/banka-hesaplari", headers=h).json()}


def cari_bakiye(h):
    return {c["unvan"]: c["bakiye"] for c in client.get("/api/raporlar/cari-bakiye", headers=h).json()}


def yukle(h, hesap_id, icerik, ad="kart.csv"):
    r = client.post(f"/api/banka-hesaplari/{hesap_id}/ekstre?yontem=kural", files={"dosya": (ad, icerik, "text/csv")}, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def onayla_hepsi(h):
    idler = [x["id"] for x in client.get("/api/hareketler?durum=taslak", headers=h).json()]
    client.post("/api/hareketler/onayla", json={"idler": idler}, headers=h)


def test_isyeri_adi_temizlenir():
    assert kart.isyeri_temizle("MIGROS 4512 GEBZE KOCAELI TR") == "MIGROS"
    assert kart.isyeri_temizle("IYZICO*TRENDYOL ISTANBUL TR") == "TRENDYOL"
    assert kart.isyeri_temizle("PAYTR *HEPSIBURADA.COM ISTANBUL") == "HEPSIBURADA"
    assert kart.isyeri_temizle("SHELL-ANKARA ESKISEHIR YOLU ANKARA") == "SHELL"
    assert kart.isyeri_temizle("Taksitli İşlem: Teknosa 3/12") == "TEKNOSA"
    assert kart.isyeri_temizle("IYZICO ODEME HIZMETLERI") == "IYZICO ODEME HIZMETLERI"
    assert kart.taksit("KOÇTAŞ GEBZE 2/6 TAKSİT") == (2, 6)
    assert kart.taksit("MIGROS 12.10.2026") is None


def test_kart_ekstresi_otomatik_tanınır_ve_carilere_islenir():
    h, migros, banka = kur()
    r = yukle(h, banka["id"], csv(EYLUL))
    assert r["kart"] and r["eklenen"] == 10 and not r["islenemeyen"], r
    kartlar = [b for b in hesaplar(h).values() if b["tur"] == "kredi_karti"]
    assert len(kartlar) == 1 and kartlar[0]["kart_no"].endswith("1234") and kartlar[0]["banka"] == "Halkbank"
    assert kartlar[0]["son_odeme_tarihi"] == "2026-10-15" and kartlar[0]["asgari_odeme"] == 1176
    t = client.get("/api/hareketler?durum=taslak", headers=h).json()
    assert all(x["banka_hesap_id"] == kartlar[0]["id"] for x in t)
    tur = {x["aciklama"]: x for x in t}
    assert tur["MIGROS 4512 GEBZE KOCAELI TR"]["cari_id"] == migros["id"] and tur["MIGROS 4512 GEBZE KOCAELI TR"]["tur"] == "odeme"
    assert tur["MIGROS 4512 GEBZE KOCAELI İADE"]["cari_id"] == migros["id"] and tur["MIGROS 4512 GEBZE KOCAELI İADE"]["yon"] == "giris"
    assert tur["KOÇTAŞ GEBZE 2/6 TAKSİT"]["cari_unvan"] == "KOÇTAŞ" and tur["KOÇTAŞ GEBZE 2/6 TAKSİT"]["tutar"] == 1000
    assert tur["BSMV"]["cari_unvan"] == "MUHTELİF BANKA İŞLEMLERİ" and tur["BSMV"]["tur"] == "banka_masrafi"
    assert tur["NAKİT AVANS ATM"]["tur"] == "nakit_cekim"
    odeme = tur["HESAPTAN OTOMATİK ÖDEME"]  # kartın bankasındaki tek hesaptan ödendi sayılır
    assert odeme["tur"] == "virman" and odeme["ai_okuma"]["karsi_hesap_id"] == banka["id"] and not odeme["sorun"]
    assert sum(1 for x in t if x["cari_unvan"] == "TRENDYOL") == 2  # aynı gün iki ayrı harcama
    onayla_hepsi(h)
    k = hesaplar(h)[kartlar[0]["ad"]]
    assert k["bakiye"] == -6060 and k["mutabakat_farki"] == 0  # açılış = önceki dönem borcu
    b = cari_bakiye(h)
    assert b["MİGROS TİCARET A.Ş."] == 1000 and b["TRENDYOL"] == 1360  # fatura girilince sıfırlanır
    assert client.get("/api/kasa", headers=h).json()["bakiye"] == 500
    ozet = client.get("/api/raporlar/ozet", headers=h).json()
    assert ozet["kart_borcu"] == 6060 and ozet["banka_toplam"] == -3000  # ödeme bankadan çıktı
    akis = client.get("/api/raporlar/nakit-akisi", headers=h).json()
    assert akis["mevcut"] == -3000 + 500  # kart borcu eldeki paradan düşülmez...
    assert [x["tutar"] for x in akis["kalemler"] if x["tur"] == "kart"] == [6060]  # ...son ödeme gününde çıkış olur
    # Aynı ekstre ikinci kez yüklenince satırlar eklenmez
    r = yukle(h, kartlar[0]["id"], csv(EYLUL))
    assert r["eklenen"] == 0 and r["atlanan"] == 10


def test_kart_odemesi_hesabi_bulunamazsa_kirmizi():
    h = yeni_kullanici(f"{uuid.uuid4().hex}@ornek.com")
    r = client.post("/api/kredi-karti-ekstresi", files={"dosya": ("k.csv", csv(EYLUL), "text/csv")}, headers=h)
    assert r.status_code == 200 and r.json()["yeni_hesap"]
    odeme = next(x for x in client.get("/api/hareketler?durum=taslak", headers=h).json() if x["tur"] == "virman")
    assert "hangi banka hesabından" in odeme["sorun"]


def test_donem_borcu_tutmazsa_uyarir():
    h, _, banka = kur()
    r = yukle(h, banka["id"], csv(EYLUL, borc="6.120,00"))
    assert any("60,00 TL tutmuyor" in x for x in r["islenemeyen"])


def test_secilen_cari_ogrenilir():
    h, migros, banka = kur()
    yukle(h, banka["id"], csv(EYLUL))
    koctas_ltd = client.post("/api/cariler", json={"unvan": "KOÇTAŞ YAPI MARKETLERİ TİC. A.Ş.", "vkn": "1111111111"}, headers=h).json()
    x = next(x for x in client.get("/api/hareketler?durum=taslak", headers=h).json() if x["aciklama"].startswith("KOÇTAŞ"))
    v = {a: x[a] for a in ("tarih", "yon", "tur", "tutar", "banka_hesap_id", "aciklama")}
    assert client.put(f"/api/hareketler/{x['id']}", json={**v, "cari_id": koctas_ltd["id"]}, headers=h).status_code == 200
    onayla_hepsi(h)
    ekim = ["İşlem Tarihi;Açıklama;Tutar", "12.10.2026;KOCTAS GEBZE 3/6 TAKSIT;1.000,00"]
    kart_id = next(b["id"] for b in hesaplar(h).values() if b["tur"] == "kredi_karti")
    yukle(h, kart_id, "\n".join(OZET + ekim).replace("{borc}", "7.060,00").encode("cp1254"))
    y = next(x for x in client.get("/api/hareketler?durum=taslak", headers=h).json() if "3/6" in x["aciklama"])
    assert y["cari_id"] == koctas_ltd["id"]


@pytest.mark.parametrize("once_banka", [True, False])
def test_kart_odemesi_bankadan_virman(once_banka):
    h, _, banka = kur()
    kart_hesap = client.post("/api/banka-hesaplari", json={"ad": "Paraf", "tur": "kredi_karti", "kart_no": "5528 79** **** 1234"},
                             headers=h).json()
    banka_ekstre = "\n".join(["Tarih;Açıklama;Tutar;Bakiye", "01.09.2026;GELEN EFT AHMET YAPI LTD;10.000,00;10.000,00",
                              "07.09.2026;KREDİ KARTI ÖDEMESİ 5528********1234;-3.000,00;7.000,00"]).encode("cp1254")
    sira = [(banka["id"], banka_ekstre, "b.csv"), (kart_hesap["id"], csv(EYLUL), "k.csv")]
    for hesap_id, icerik, ad in (sira if once_banka else sira[::-1]):
        yukle(h, hesap_id, icerik, ad)
        onayla_hepsi(h)
    hs = hesaplar(h)
    assert hs["Halkbank TL"]["bakiye"] == 7000 and hs["Halkbank TL"]["mutabakat_farki"] == 0
    assert hs["Paraf"]["bakiye"] == -6060 and hs["Paraf"]["mutabakat_farki"] == 0
    hareketler = client.get("/api/hareketler", headers=h).json()
    virman = [x for x in hareketler if x["tur"] == "virman"]
    assert len(virman) == 2 and all(x["cari_id"] is None for x in virman)
    assert "MUHTELİF BANKA İŞLEMLERİ" not in {x["cari_unvan"] for x in virman}


def test_kart_hesabina_yuklenen_pdf(monkeypatch):
    from tests.test_kural import pdf_olustur
    h, _, _ = kur()
    pdf = pdf_olustur(["PARAF KART HESAP OZETI", "Kart Numarasi: 5528 79** **** 1234",
                       "Hesap Kesim Tarihi Son Odeme Tarihi Donem Borcu Asgari Odeme Tutari",
                       "05.10.2026 15.10.2026 1.680,00 336,00",
                       "Islem Tarihi Aciklama Tutar ParafPara",
                       "10.09.2026 MIGROS 4512 GEBZE KOCAELI 1.250,00 2,50",
                       "12.09.2026 KOCTAS GEBZE 2/6 TAKSIT 6.000,00 1.000,00",
                       "22.09.2026 MIGROS IADE -570,00"])
    r = client.post("/api/kredi-karti-ekstresi", files={"dosya": ("k.pdf", pdf, "application/pdf")}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["eklenen"] == 3 and r.json()["yeni_hesap"] and not r.json()["islenemeyen"]
    t = {x["aciklama"]: x for x in client.get("/api/hareketler?durum=taslak", headers=h).json()}
    assert t["KOCTAS GEBZE 2/6 TAKSIT"]["tutar"] == 1000  # taksit tutarı, toplam değil


HESAP_EKSTRESI = ["Akbank Hesap Ekstresi", "IBAN;TR00 0004 6000 0000 0000 0000 01", "",
                  "Tarih;Açıklama;Tutar;Bakiye",
                  "09.10.2026;NAKİT ÇEKİLEN;-1.000.000,00;500.000,00",
                  "09.10.2026;ÖRNEK YAPI LTD ŞTİ'DAN gelen havale TR46****5509;100.000,00;1.500.000,00",
                  "10.10.2026;FATURA ÖDEMESİ ELEKTRİK;-2.500,00;1.497.500,00"]


def test_hesap_ekstresi_kart_ekranindan_yuklenmez_atlananin_nedeni_yazar():
    h, _, banka = kur()
    veri = "\n".join(HESAP_EKSTRESI).encode("cp1254")
    # Kart ekranından: banka hesap ekstresi kart hesabına işlenmez, hiçbir satır eklenmez
    r = client.post("/api/kredi-karti-ekstresi", files={"dosya": ("HESAPEKSTRE_1.csv", veri, "text/csv")}, headers=h)
    assert r.status_code == 422 and "banka hesap ekstresi" in r.json()["detail"]
    assert not [b for b in hesaplar(h).values() if b.get("tur") == "kredi_karti"]
    assert client.get("/api/hareketler?durum=taslak", headers=h).json() == []
    # Banka hesabına yüklenir; ikinci yüklemede atlananların nedeni yazar
    yol = f"/api/banka-hesaplari/{banka['id']}/ekstre?yontem=kural"
    r1 = client.post(yol, files={"dosya": ("HESAPEKSTRE_1.csv", veri, "text/csv")}, headers=h).json()
    assert r1["eklenen"] == 3
    r2 = client.post(yol, files={"dosya": ("HESAPEKSTRE_1.csv", veri, "text/csv")}, headers=h).json()
    assert r2["eklenen"] == 0 and r2["atlanan"] == 3
    assert "3 satır bu hesaba daha önce yüklenmiş" in r2["atlanan_nedeni"] and "onay bekliyor" in r2["atlanan_nedeni"]
    # Yanlış yüklenen kart ekstresi toplu silinince, onun için kendiliğinden açılan ve başka yerde kullanılmayan
    # cariler de silinir; önceden var olan cari kalır
    client.post("/api/hareketler/toplu-sil", json={"idler": [x["id"] for x in client.get("/api/hareketler?durum=taslak", headers=h).json()]}, headers=h)
    once = {c["unvan"] for c in client.get("/api/cariler", headers=h).json()}
    client.post("/api/kredi-karti-ekstresi", files={"dosya": ("k.csv", csv(EYLUL), "text/csv")}, headers=h)
    acilan = {c["unvan"] for c in client.get("/api/cariler", headers=h).json()} - once
    assert acilan
    taslak = client.get("/api/hareketler?durum=taslak", headers=h).json()
    client.post("/api/hareketler/toplu-sil", json={"idler": [x["id"] for x in taslak]}, headers=h)
    kalan = {c["unvan"] for c in client.get("/api/cariler", headers=h).json()}
    assert not (acilan - {"MUHTELİF BANKA İŞLEMLERİ"}) & kalan and "MİGROS TİCARET A.Ş." in kalan
