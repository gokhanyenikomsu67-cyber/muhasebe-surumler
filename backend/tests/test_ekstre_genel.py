"""Banka ekstresi okumada genel kurallar: karşı taraf adı/IBAN'ı açıklamadan, kendi hesaplarımız arası virman eşleşmesi,
kendi IBAN'ımız cariye yazılmaz, yeniden yüklemede onaylanmamış satırlar yeniden okunur, cari seçimi öğrenilir,
ek hesaplı (KMH) ekstrede bakiye (sentetik veri)."""
import io
import uuid

from openpyxl import Workbook

from app import kural
from tests.test_api import client
from tests.test_ekstre_otomatik import iban

UNVAN = "DENEME YAPI İNŞAAT LİMİTED ŞİRKETİ"
KENDI = kural.sade(UNVAN).split()[:2]


def _kullanici():
    r = client.post("/api/kayit", json={"sirket_unvan": UNVAN, "ad": "x", "eposta": f"{uuid.uuid4().hex}@ornek.com", "sifre": "gizli123"})
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _csv(ib: str, satirlar: list[tuple]) -> bytes:
    """Halkbank düzeninde CSV: (tarih, tutar, bakiye, açıklama)."""
    bas = [f"IBAN No:                      ;{ib}                    ;;;;;", ";;;;;;",
           "İŞLEM TARİHİ;BİM REF                   ;TUTAR                        ;B/A;BAKİYE                   ;AÇIKLAMA"]
    for i, (t, tutar, bakiye, ac) in enumerate(satirlar):
        tutar_metni = f"{abs(tutar):.2f}".replace(".", ",")
        bas.append(f"{t};2026-09-01-10.00.00.{i:06d};{tutar_metni};{'A' if tutar > 0 else 'B'};{bakiye};{ac}")
    return "\r\n".join(bas).encode("iso-8859-9")


def _yukle(h, ad, veri):
    r = client.post("/api/ekstre-yukle", files={"dosya": (ad, veri, "text/csv")}, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def _taslak(h):
    return client.get("/api/hareketler?durum=taslak", headers=h).json()


def test_aciklamadan_karsi_taraf_adi_ve_iban():
    ib = iban("00062", "5550001")
    # "not,AD,banka/IBAN,..." düzeni: ad ikinci alandır; IBAN adın hemen ardından gelendir
    assert kural.karsi_taraf(f"fatura ödemesi,ÖRNEK BETON SAN. VE TİC. A.Ş.,{ib},{UNVAN}", -500, KENDI) == \
        {"unvan": "ÖRNEK BETON SAN. VE TİC. A.Ş", "iban": ib}
    assert kural.karsi_taraf("ödeme,örnek beton,Garanti BBVA,TRN", -500, KENDI)["unvan"] == "ÖRNEK BETON"
    # "AD*banka kodu*not*no" düzeni ve DBS ödemesi
    assert kural.karsi_taraf("ÖRNEK MALZEME LTD ŞTİ*0062*fatura ödemesi*12345678", 800, KENDI)["unvan"] == "ÖRNEK MALZEME LTD ŞTİ"
    assert kural.karsi_taraf("123456789 REF NOLU ÖRNEK DEMİR LTD DBS", -700, KENDI)["unvan"] == "ÖRNEK DEMİR LTD"
    # Kendi firmamız karşı taraf olmaz; böyle satır virmandır
    ac = f"HESAPLAR ARASI TRANSFER,{UNVAN},TR12******************4321"
    assert kural.karsi_taraf(ac, -300, KENDI) is None and kural.tur_tahmin(-300, ac, None, KENDI) == "virman"
    assert kural.karsi_taraf(f"{UNVAN}*0012*cari geçiş*123456", 300, KENDI) is None
    # Aynı karşı taraf için öğrenme anahtarı açıklamadaki nottan bağımsızdır
    assert kural.ekstre_kalibi("ödeme,ÖRNEK BETON A.Ş.,Garanti BBVA", -1) == kural.ekstre_kalibi("cari,Örnek Beton A.Ş.,Akbank T.A.Ş.,TRN", -9)


def test_banka_kesintileri_ve_cek_odemesi():
    for ac in ("SİGORTA PRİM TAHSİLATI", "GAYRİNAKDİ KOMİSYON", "KMH FAİZİ", "KRED.MEV.VERGİ"):
        assert kural.tur_tahmin(-10, ac, None, KENDI) == "banka_masrafi", ac
    assert kural.tur_tahmin(-1000, "ÇEK ÖDEME 1234567", None, KENDI) == "cek_odeme"


def test_kendi_hesaplar_arasi_virman_eslesir_ve_cift_yazilmaz():
    h = _kullanici()
    a, b = iban("00012", "1000001"), iban("00012", "1000002")
    ib_cari = iban("00062", "5550001")
    _yukle(h, "a.csv", _csv(a, [("01.09.2026", 1000, "1000,00", "GELEN EFT,ÖRNEK MÜŞTERİ A.Ş.,ÖRNEK MÜŞTERİ A.Ş.'DAN"),
                                ("02.09.2026", -300, "700,00", f"HESAPLAR ARASI TRANSFER,{UNVAN},{b[:4]}******************{b[-4:]}"),
                                ("03.09.2026", -200, "500,00", f"ödeme,ÖRNEK BETON A.Ş.,{ib_cari},{UNVAN},{a}")]))
    _yukle(h, "b.csv", _csv(b, [("02.09.2026", 300, "300,00", f"HESAPLAR ARASI TRANSFER,{UNVAN},{a[:4]}******************{a[-4:]}")]))
    ta = _taslak(h)
    hesaplar = {x["id"]: x for x in client.get("/api/banka-hesaplari", headers=h).json()}
    virman = [x for x in ta if x["tur"] == "virman"]
    assert len(virman) == 2 and {hesaplar[x["ai_okuma"]["karsi_hesap_id"]]["iban"] for x in virman} == {a, b}
    cariler = {x["unvan"]: x for x in client.get("/api/cariler", headers=h).json()}
    assert cariler["ÖRNEK BETON A.Ş"]["iban"] == ib_cari  # bizim IBAN'ımız (a) cariye yazılmaz
    assert not any(x["iban"] in (a, b) for x in cariler.values())
    client.post("/api/hareketler/onayla", json={"idler": [x["id"] for x in ta]}, headers=h)
    for x in client.get("/api/banka-hesaplari", headers=h).json():
        assert x["mutabakat_farki"] == 0, x  # transfer iki hesapta da bir kez
    assert not [x for x in client.get("/api/hareketler", headers=h).json() if x.get("kaynak") == "esleme"]


def test_yeniden_yuklemede_onaylanmamis_satirlar_yeniden_okunur_ve_cari_secimi_ogrenilir():
    h = _kullanici()
    ib = iban("00012", "1000003")
    veri = _csv(ib, [("01.09.2026", -100, "-100,00", "MOBİL ÖDEME 4455"), ("02.09.2026", -50, "-150,00", "MOBİL ÖDEME 4455 EK")])
    _yukle(h, "a.csv", veri)
    ta = sorted(_taslak(h), key=lambda x: x["tarih"])
    cari = client.post("/api/cariler", json={"unvan": "Örnek Elektrik Dağıtım"}, headers=h).json()
    r = client.put(f"/api/hareketler/{ta[0]['id']}", json={**ta[0], "cari_id": cari["id"], "tur": "odeme"}, headers=h)
    assert r.status_code == 200, r.text
    v = _yukle(h, "a.csv", veri)
    assert "yeniden okundu" in v["notlar"] and len(_taslak(h)) == 2
    assert any(x["id"] == ta[0]["id"] and x["cari_id"] == cari["id"] for x in _taslak(h))  # elle düzeltilen satır korunur
    # Aynı kalıptaki yeni satır öğrenilen cariye gider
    _yukle(h, "b.csv", _csv(ib, [("10.09.2026", -70, "-220,00", "MOBİL ÖDEME 9911")]))
    yeni = [x for x in _taslak(h) if x["tarih"] == "2026-09-10"]
    assert yeni and yeni[0]["cari_id"] == cari["id"]


def _ek_hesapli_xlsx(ib: str) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(["IBAN", ib])
    ws.append(["Tarih/Saat", "Tutar", "Bakiye", "Ek Hesap Bakiyesi", "İşlem Tipi", "Açıklama"])
    # Yeniden eskiye: ek hesap borcu hesaptaki parayla kapanır (toplam değişmez), sonra yeni ödeme ek hesaptan
    ws.append(["04/09/2026-10:00:00", -300, 0, -800, "EFT", "ÖRNEK TEDARİKÇİ ÖDEME"])
    ws.append(["03/09/2026-20:00:00", -200, 0, -500, "Ek Hesap", "KMH-ANAPARA BORCU TAHSİLATI"])
    ws.append(["03/09/2026-10:00:00", 200, 200, -700, "EFT", "ÖRNEK MÜŞTERİ TAHSİLAT"])
    ws.append(["02/09/2026-10:00:00", -5, 0, -700, "Ücret", "KMH KULLANDIRIM ÜCRETİ"])
    t = io.BytesIO()
    wb.save(t)
    return t.getvalue()


def test_ek_hesapli_ekstrede_bakiye_toplamdir_ic_aktarim_hareket_sayilmaz():
    h = _kullanici()
    ib = iban("00064", "2223334")
    r = client.post("/api/ekstre-yukle", files={"dosya": ("HesapOzeti.xlsx", _ek_hesapli_xlsx(ib), "application/octet-stream")}, headers=h)
    assert r.status_code == 200, r.text
    ta = _taslak(h)
    assert sorted(x["tutar"] for x in ta) == [5, 200, 300] and not any("ANAPARA" in x["aciklama"] for x in ta)
    client.post("/api/hareketler/onayla", json={"idler": [x["id"] for x in ta]}, headers=h)
    hesap = client.get("/api/banka-hesaplari", headers=h).json()[0]
    assert hesap["ekstre_bakiye"] == -800 and hesap["mutabakat_farki"] == 0
