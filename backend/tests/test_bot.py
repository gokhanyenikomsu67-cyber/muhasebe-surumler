"""WhatsApp botu: kalıp sorulara programdaki verilerden cevap, yalnız kayıtlı numaralara (sentetik veri)."""
import uuid
from datetime import date, timedelta

from app import bot, soru
from tests.test_api import client, yeni_kullanici

BUGUN = date.today()


def _kur():
    h = yeni_kullanici(f"{uuid.uuid4().hex}@ornek.com")
    s = client.post("/api/santiyeler", json={"ad": "Gebze Fabrika", "butce": 100000}, headers=h).json()
    client.post("/api/santiyeler", json={"ad": "Kartal Konut"}, headers=h)
    musteri = client.post("/api/cariler", json={"unvan": "Ahmet Yapı Ltd. Şti.", "tur": "musteri", "vkn": "5555555555"}, headers=h).json()
    tedarikci = client.post("/api/cariler", json={"unvan": "Demir Çelik A.Ş.", "vkn": "6666666666"}, headers=h).json()
    client.post("/api/banka-hesaplari", json={"ad": "Halkbank TL", "acilis_bakiyesi": 25000}, headers=h)
    f = client.post("/api/faturalar", json={"yon": "gelen", "fatura_no": "DMR1", "tarih": BUGUN.isoformat(), "cari_id": tedarikci["id"],
                                            "santiye_id": s["id"], "gider_turu": "Demir",
                                            "kalemler": [{"aciklama": "Nervürlü demir", "miktar": 1, "birim_fiyat": 1000, "kdv_orani": 20}]},
                    headers=h).json()
    assert client.post(f"/api/faturalar/{f['id']}/onayla", headers=h).status_code == 200
    client.post("/api/cekler", json={"yon": "alinan", "tutar": 4000, "vade": (BUGUN + timedelta(days=3)).isoformat(),
                                     "cari_id": musteri["id"]}, headers=h)
    client.post("/api/cekler", json={"yon": "verilen", "tutar": 600, "vade": (BUGUN + timedelta(days=40)).isoformat(),
                                     "cari_id": tedarikci["id"]}, headers=h)
    return h


def test_vadesi_gecen_cek_gosterilmez():
    h = _kur()
    client.post("/api/cekler", json={"yon": "alinan", "tutar": 777, "vade": (BUGUN - timedelta(days=300)).isoformat()}, headers=h)
    for soru_ in ("bu hafta çekler", "çekler", "tüm çekler", "genel durum"):
        assert "777,00" not in _sor(h, soru_), soru_
    assert "4.000,00 TL" in _sor(h, "çekler")


def _sor(h, metin):
    return client.get("/api/bot/sor", params={"metin": metin}, headers=h).json()["cevap"]


def test_kalip_sorular():
    h = _kur()
    c = _sor(h, "gebze şantiye harcaması")
    assert "Gebze Fabrika" in c and "1.200,00 TL" in c and "Demir" in c and "Kalan: 98.800,00 TL" in c
    assert "1.200,00 TL" in _sor(h, "GEBZEYE NE KADAR HARCADIK BU AY")
    assert "0,00 TL" in _sor(h, f"gebze harcama ocak {BUGUN.year - 1}")
    c = _sor(h, "demir bakiye")
    assert "Biz Demir Çelik A.Ş. firmasına 600,00 TL borçluyuz" in c and "Açık çek: 1 adet, 600,00 TL" in c
    c = _sor(h, "ahmet yapı borcu ne kadar")  # çek alındı: bakiye -4000 (peşin ödeme gibi)
    assert "Ahmet Yapı" in c
    c = _sor(h, "5 gün içinde çekler")
    assert "4.000,00 TL" in c and "600,00 TL" not in c
    c = _sor(h, "ödenecek çekler bu ay") if (BUGUN + timedelta(days=40)).month == BUGUN.month else _sor(h, "ödenecek çekler 60 gün")
    assert "600,00 TL" in c and "4.000,00 TL" not in c
    c = _sor(h, "banka bakiyeleri")
    assert "Halkbank TL: 25.000,00 TL" in c and "Nakit Kasa" in c
    assert "Demir Çelik" in _sor(h, "kime borçluyuz")
    assert "Genel durum" in _sor(h, "genel durum")
    assert "Şunları sorabilirsiniz" in _sor(h, "yardım")
    assert "Anlayamadım" in _sor(h, "merhaba nasılsınız")


def test_birden_fazla_eslesen_sorulur():
    h = _kur()
    client.post("/api/santiyeler", json={"ad": "Gebze Depo"}, headers=h)
    c = _sor(h, "gebze harcama")
    assert "Birden fazla şantiye" in c and "Gebze Fabrika" in c and "Gebze Depo" in c


def test_donem():
    g = date(2026, 10, 23)
    assert soru.donem("bu ay", g)[:2] == (date(2026, 10, 1), date(2026, 10, 31))
    assert soru.donem("gecen ay", g)[:2] == (date(2026, 9, 1), date(2026, 9, 30))
    assert soru.donem("aralik 2025", g)[:2] == (date(2025, 12, 1), date(2025, 12, 31))
    assert soru.donem("bu hafta", g)[:2] == (date(2026, 10, 19), date(2026, 10, 25))
    assert soru.donem("gebze", g) == (None, None, "")


def test_rakamlar():
    assert bot.rakamlar("0532 123 45 67") == "905321234567"
    assert bot.rakamlar("+90 (532) 123-45-67") == "905321234567"
    assert bot.rakamlar("905321234567:12@s.whatsapp.net") == "905321234567"
    assert bot.rakamlar("123456789012345@lid") == "123456789012345"


def test_kopru_yalniz_kayitli_numaraya_cevap_verir():
    h = _kur()
    ben = next(x for x in client.get("/api/kullanicilar", headers=h).json()["kullanicilar"] if x["ben"])
    r = client.post("/api/bot/numaralar", json={"ad": "Patron 1", "telefon": "0532 111 22 33", "kullanici_id": ben["id"]}, headers=h)
    assert r.status_code == 200 and r.json()["telefon"] == "905321112233"
    anahtar = {"X-Bot-Anahtari": bot.ANAHTAR}
    yol = "/api/bot/mesaj"
    # Anahtarsız olmaz
    assert client.post(yol, json={"gonderen": "905321112233@s.whatsapp.net", "metin": "banka"}).status_code == 401
    # Köprü yalnız bu bilgisayardan kabul edilir (TestClient "testclient" adresinden gelir)
    import app.routers.bot as R
    assert client.post(yol, headers=anahtar, json={"gonderen": "905321112233@s.whatsapp.net", "metin": "banka"}).status_code == 401
    R.YEREL.add("testclient")
    try:
        # Grupta numara yerine gizli kimlik gelir; numara alt kimlikte. Kimlik öğrenilir.
        r = client.post(yol, headers=anahtar, json={"gonderen": "99887766@lid", "gonderen_alt": "905321112233@s.whatsapp.net",
                                                    "metin": "banka bakiyeleri", "grup": "yapay zeka destek bildirimi"})
        assert "Halkbank TL" in r.json()["cevap"]
        r = client.post(yol, headers=anahtar, json={"gonderen": "99887766@lid", "metin": "gebze harcama"})
        assert "Gebze Fabrika" in r.json()["cevap"]
        # Sohbet mesajına karışmaz
        assert client.post(yol, headers=anahtar, json={"gonderen": "99887766@lid", "metin": "tamam sağol"}).json()["cevap"] is None
        assert client.post(yol, headers=anahtar, json={"gonderen": "99887766@lid", "metin": "yarın gebzeye gidiyorum"}).json()["cevap"] is None
        assert "Gebze Fabrika" in client.post(yol, headers=anahtar, json={"gonderen": "99887766@lid", "metin": "gebze?"}).json()["cevap"]
        # Kısa yazı soru sayılır, şantiye yanlış yazılsa da ("santiesi"); anlaşılmayan kısa yazıya "yardım yazın" denir
        for m in ("gebze santiesi", "Gebze", "gebze şantiyesi ne durumda"):
            assert "Gebze Fabrika" in client.post(yol, headers=anahtar, json={"gonderen": "99887766@lid", "metin": m}).json()["cevap"], m
        assert "Demir Çelik" in client.post(yol, headers=anahtar, json={"gonderen": "99887766@lid", "metin": "demir çelik"}).json()["cevap"]
        # Anlaşılmayan yazıya yalnız bota yazılınca (@bahsetme ya da yanıt) "yardım yazın" denir; sohbete karışılmaz
        assert client.post(yol, headers=anahtar, json={"gonderen": "99887766@lid", "metin": "kasım raporu"}).json()["cevap"] is None
        assert client.post(yol, headers=anahtar, json={"gonderen": "99887766@lid", "metin": ".... Yedik"}).json()["cevap"] is None
        assert "yardım" in client.post(yol, headers=anahtar, json={"gonderen": "99887766@lid", "metin": "kasım raporu",
                                                                   "hitap": True}).json()["cevap"]
        c = client.post(yol, headers=anahtar, json={"gonderen": "99887766@lid", "metin": "@123456789 kaç para ödenmemiş çek var",
                                                    "hitap": True}).json()["cevap"]
        assert "600,00 TL" in c and "4.000,00 TL" not in c, c
        assert client.post(yol, headers=anahtar, json={"gonderen": "99887766@lid", "metin": "tamam teşekkürler"}).json()["cevap"] is None
        # Ekranda son gelenler: kim, ne yazdı, ne yapıldı
        son = bot.MESAJLAR[-2:]
        assert son[0]["ad"] == "Patron 1" and son[0]["sonuc"] == "Cevap verildi" and son[1]["sonuc"].startswith("Cevap verilmedi")
        # Tanınmayan kişi: cevap yok, ekranda listelenir
        r = client.post(yol, headers=anahtar, json={"gonderen": "905009998877@s.whatsapp.net", "ad": "Yabancı", "metin": "banka"})
        assert r.json()["cevap"] is None and any(x["ad"] == "Yabancı" and not x["tanindi"] for x in bot.MESAJLAR)
        r = client.post(yol, headers=anahtar, json={"gonderen": "905009998877@s.whatsapp.net", "metin": "banka", "hitap": True})
        assert "iznim yok" in r.json()["cevap"] and "Halkbank" not in r.json()["cevap"]
    finally:
        R.YEREL.discard("testclient")


def test_yetkisiz_bolum_gosterilmez():
    h = _kur()
    eposta = f"{uuid.uuid4().hex}@ornek.com"
    client.post("/api/kullanicilar", json={"ad": "Şantiyeci", "eposta": eposta, "sifre": "gizli123", "rol": "muhasebeci",
                                          "yetkiler": {"santiye": ["gor"]}}, headers=h)
    t = client.post("/api/giris", json={"eposta": eposta, "sifre": "gizli123"}).json()["token"]
    sh = {"Authorization": f"Bearer {t}"}
    assert "yetkiniz yok" in _sor(sh, "banka bakiyeleri")
    assert "yetkiniz yok" in _sor(sh, "demir bakiye")
    assert "Gebze Fabrika" in _sor(sh, "gebze harcama")
    # Numaraları yalnız sahip yönetir
    assert client.get("/api/bot/numaralar", headers=sh).status_code == 403


def test_npm_hatasi_kisa_ve_turkce():
    cikti = ("npm notice New major version of npm available! 11.19.1 -> 12.2.1\nnpm error code 1\n"
             "npm error path C:\\x\\node_modules\\baileys\nnpm error command failed\n"
             "npm error command C:\\Windows\\system32\\cmd.exe /d /s /c node ./engine-requirements.js\n"
             "npm error 'node' is not recognized as an internal or external command,\n"
             "npm error A complete log of this run can be found in: C:\\x.log")
    h = bot.npm_hatasi(cikti)
    assert "notice" not in h and "complete log" not in h and "not recognized" in h
    assert bot.npm_hatasi("npm error code ENOTFOUND\nnpm error network request failed").startswith("İnternete ulaşılamadı")
