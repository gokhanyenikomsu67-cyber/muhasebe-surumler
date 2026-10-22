"""Çek Excel'i: Şantiye sütunundaki açıklama şantiye açtırmaz, Lehtar sütunu okunur, "X firmasına ciro edildi" akıbet
olur (sentetik veri)."""
import io
import uuid

from openpyxl import Workbook

from tests.test_api import client


def _xlsx(satirlar) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(["Yön (Alınan/Verilen)", "Tür (Çek/Senet)", "Çek No", "Banka", "Çeki Yazan Firma", "Tutar", "Vade", "Cari Ünvan",
               "Şantiye", "Açıklama", "Lehtar"])
    for r in satirlar:
        ws.append(r)
    t = io.BytesIO()
    wb.save(t)
    return t.getvalue()


def test_cek_excelinde_santiye_aciklama_lehtar_ve_ciro():
    r = client.post("/api/kayit", json={"sirket_unvan": "DENEME", "ad": "x", "eposta": f"{uuid.uuid4().hex}@ornek.com", "sifre": "gizli123"})
    h = {"Authorization": f"Bearer {r.json()['token']}"}
    client.post("/api/santiyeler", json={"ad": "ÖRNEK GES"}, headers=h)
    client.post("/api/banka-hesaplari", json={"ad": "Akbank Vadesiz", "banka": "Akbank"}, headers=h)
    veri = _xlsx([
        ["Alınan", "Çek", "1000001", "AKBANK", "ÖRNEK YAPI", 1000, "10.01.2026", None, "USTA BORDÜR ÖRNEK GES İÇİN", None, "DENEME LTD"],
        ["Alınan", "Çek", "1000002", "AKBANK", "ÖRNEK YAPI", 2000, "11.01.2026", None, "VİNÇ İÇİN VERİLDİ", None, None],
        ["Alınan", "Çek", "1000003", "AKBANK", "ÖRNEK YAPI", 3000, "12.01.2026", "ÖRNEK KABLO", "YENİSAHA", "Deneme'ye yazıldı, ÖRNEK KABLO firmasına ciro edildi", None],
        ["Alınan", "Çek", "1000004", "AKBANK", "ÖRNEK YAPI", 4000, "13.01.2026", None, None, "AKBANKTA | AKBANK DENEME", None],
    ])
    r = client.post("/api/excel/cekler/onizle?yon=alinan", files={"dosya": ("c.xlsx", veri)}, headers=h)
    assert r.status_code == 200, r.text
    s = r.json()["satirlar"]
    # Var olan şantiyenin adı geçen açıklama o şantiyeye; açıklama gibi yazı açıklamaya; kısa bilinmeyen ad yeni şantiye
    assert [(x["santiye_ad"], x["aciklama"]) for x in s[:3]] == [
        ("ÖRNEK GES", "USTA BORDÜR ÖRNEK GES İÇİN"), (None, "VİNÇ İÇİN VERİLDİ"),
        ("YENİSAHA", "Deneme'ye yazıldı, ÖRNEK KABLO firmasına ciro edildi")]
    assert s[0]["lehtar"] == "DENEME"
    # Ciro edilen firma akıbet olur; Cari sütununa ciro edilen firma yazılmışsa cari çeki yazan firmadır
    cari = next(c for c in client.get("/api/cariler", headers=h).json() if c["unvan"] == "ÖRNEK KABLO")
    assert s[2]["akibet"] == {"islem": "ciro", "cari_id": cari["id"]} and s[2]["cari_unvan"] is None
    hesap = client.get("/api/banka-hesaplari", headers=h).json()[0]
    assert s[3]["akibet"] == {"islem": "tahsile_ver", "banka_hesap_id": hesap["id"]}


def test_verilen_cekte_lehtar_bossa_cari_unvan():
    r = client.post("/api/kayit", json={"sirket_unvan": "DENEME", "ad": "x", "eposta": f"{uuid.uuid4().hex}@ornek.com", "sifre": "gizli123"})
    h = {"Authorization": f"Bearer {r.json()['token']}"}
    veri = _xlsx([["Verilen", "Çek", "Z000001", "AKBANK", "DENEME", 500, "10.01.2026", "ÖRNEK ELEKTRİK", None, "PANO İŞİ", None]])
    s = client.post("/api/excel/cekler/onizle?yon=verilen", files={"dosya": ("c.xlsx", veri)}, headers=h).json()["satirlar"]
    assert (s[0]["lehtar"], s[0]["cari_unvan"], s[0]["santiye_ad"], s[0]["aciklama"]) == ("ÖRNEK ELEKTRİK", "ÖRNEK ELEKTRİK", None, "PANO İŞİ")
    assert "lehtar" not in s[0]["belirsiz"]


def test_toplu_cekte_cari_durumu_kayitli_yeni_benzer():
    r = client.post("/api/kayit", json={"sirket_unvan": "DENEME", "ad": "x", "eposta": f"{uuid.uuid4().hex}@ornek.com", "sifre": "gizli123"})
    h = {"Authorization": f"Bearer {r.json()['token']}"}
    kayitli = client.post("/api/cariler", json={"unvan": "ÖRNEK YAPI LTD ŞTİ"}, headers=h).json()
    benzer = client.post("/api/cariler", json={"unvan": "ÖRNEK ENERJİ"}, headers=h).json()
    satirlar = [{"yon": "alinan", "kesideci": "Örnek Yapı Ltd. Şti."}, {"yon": "alinan", "kesideci": "ÖRNEK ENERJİ ÇELİK SANAYİ"},
                {"yon": "verilen", "lehtar": "DENEME LTD"}, {"yon": "verilen", "lehtar": "YEPYENİ FİRMA"}]
    d = client.post("/api/cekler/cari-durumu", json={"satirlar": satirlar}, headers=h).json()
    assert (d[0]["durum"], d[0]["cari_id"]) == ("kayitli", kayitli["id"])  # ekler yok sayılır, var olana işlenir
    assert d[1]["durum"] == "yeni" and d[1]["benzer"][0]["id"] == benzer["id"]
    assert d[2]["durum"] == "yok"  # lehtar firmamızsa cari belli değil
    assert (d[3]["durum"], d[3]["benzer"]) == ("yeni", [])
