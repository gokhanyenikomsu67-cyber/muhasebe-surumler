"""Hesap seçmeden ekstre yükleme: hesap dosyadaki IBAN'dan bulunur, yoksa banka adı ve IBAN'la açılır (sentetik veri)."""
import uuid

from tests.test_api import client, yeni_kullanici


def iban(banka_kodu: str, hesap: str) -> str:
    """Geçerli (mod 97) sentetik TR IBAN'ı."""
    bban = banka_kodu + "0" + hesap.rjust(16, "0")
    sayi = int("".join(str(int(c, 36)) for c in bban + "TR00"))
    return f"TR{98 - sayi % 97:02d}{bban}"


def halkbank_csv(ib: str, hesap_no: str = "10000001") -> bytes:
    satirlar = [
        "Şube Kodu:                    ;1000                    ;;;;;",
        "Şube Ad:                      ;DENEME ŞUBESİ           ;;;;;",
        f"Hesap No:                     ;{hesap_no}              ;;;;;",
        f"IBAN No:                      ;{ib}                    ;;;;;",
        "Sorgu Başlangıç Tarihi:       ;2026-09-01              ;;;;;",
        ";;;;;;;;;;;;;;;;;;;;",
        "İŞLEM TARİHİ;BİM REF                   ;TUTAR                        ;B/A;BAKİYE                   ;AÇIKLAMA",
        "01.09.2026  ;2026-09-01-10.00.00.000001;                 1.000,00    ;A  ;                 1.000,00;DENEME MÜŞTERİ TAHSİLAT",
        "02.09.2026  ;2026-09-02-10.00.00.000002;                   250,00    ;B  ;                   750,00;DENEME TEDARİKÇİ ÖDEME",
    ]
    return "\r\n".join(satirlar).encode("iso-8859-9")


def test_hesap_yoksa_iban_ve_banka_adiyla_acilir_varsa_ona_yuklenir():
    h = yeni_kullanici(f"{uuid.uuid4().hex}@ornek.com")
    ib = iban("00012", "1234567")  # 00012 = Halkbank
    r = client.post("/api/ekstre-yukle", files={"dosya": ("HESAPEKSTRE_1.CSV", halkbank_csv(ib), "text/csv")}, headers=h)
    assert r.status_code == 200, r.text
    v = r.json()
    assert v["eklenen"] == 2 and v["yeni_hesap"][0].startswith("Halkbank") and "Yeni banka hesabı açıldı" in v["notlar"]
    hesaplar = client.get("/api/banka-hesaplari", headers=h).json()
    assert [(b["banka"], b["iban"]) for b in hesaplar] == [("Halkbank", ib)]
    # İkinci hesabın ekstresi ayrı hesap açar; aynı hesabın ekstresi yeniden yüklenince hesap açılmaz, satır tekrarlanmaz
    ib2 = iban("00012", "7654321")
    assert client.post("/api/ekstre-yukle", files={"dosya": ("b.csv", halkbank_csv(ib2), "text/csv")}, headers=h).json()["eklenen"] == 2
    v = client.post("/api/ekstre-yukle", files={"dosya": ("a.csv", halkbank_csv(ib), "text/csv")}, headers=h).json()
    assert v["eklenen"] == 0 and not v.get("yeni_hesap")
    assert len(client.get("/api/banka-hesaplari", headers=h).json()) == 2


def test_ibansiz_dosyada_birden_fazla_hesap_varsa_sorulur():
    h = yeni_kullanici(f"{uuid.uuid4().hex}@ornek.com")
    for ad in ("A Bankası", "B Bankası"):
        client.post("/api/banka-hesaplari", json={"ad": ad}, headers=h)
    veri = "\n".join(["Tarih;Açıklama;Tutar;Bakiye", "01.09.2026;DENEME TAHSİLAT;1.000,00;1.000,00"]).encode()
    r = client.post("/api/ekstre-yukle", files={"dosya": ("e.csv", veri, "text/csv")}, headers=h)
    assert r.status_code == 409 and "hangi hesaba" in r.json()["detail"]
    hid = client.get("/api/banka-hesaplari", headers=h).json()[1]["id"]
    r = client.post(f"/api/ekstre-yukle?hesap_id={hid}", files={"dosya": ("e.csv", veri, "text/csv")}, headers=h)
    assert r.status_code == 200 and r.json()["eklenen"] == 1, r.text
