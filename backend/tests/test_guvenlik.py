"""Ağa açık kullanımda: her uçta giriş zorunlu, izleyici hiçbir şeyi değiştiremez, bir firma ötekinin kaydını göremez/kullanamaz."""
import re
import uuid

from app.main import app
from tests.test_api import client, yeni_kullanici

ACIK_UCLAR = {("POST", "/api/kayit"), ("POST", "/api/giris"), ("GET", "/")}


def uclar():
    def gez(routes, onek=""):
        for r in routes:
            alt = getattr(r, "original_router", None)
            if alt is not None:
                yield from gez(alt.routes, onek)
            elif hasattr(r, "dependant"):
                for m in r.methods:
                    yield m, onek + r.path
    return sorted(set(gez(app.routes)))


def doldur(yol):
    return re.sub(r"\{[^}]+\}", "1", yol)


def test_girissiz_hicbir_uc_veri_vermez():
    for m, yol in uclar():
        if (m, yol) in ACIK_UCLAR:
            continue
        r = client.request(m, doldur(yol))
        assert r.status_code == 401, f"{m} {yol} girişsiz {r.status_code}"
        r = client.request(m, doldur(yol), headers={"Authorization": "Bearer yanlis"})
        assert r.status_code == 401, f"{m} {yol} geçersiz oturumla {r.status_code}"


def test_izleyici_hicbir_seyi_degistiremez():
    h = yeni_kullanici(f"{uuid.uuid4().hex}@ornek.com")
    eposta = f"{uuid.uuid4().hex}@ornek.com"
    assert client.post("/api/kullanicilar", json={"ad": "İ", "eposta": eposta, "sifre": "gizli123", "rol": "izleyici"}, headers=h).status_code == 200
    hi = {"Authorization": "Bearer " + client.post("/api/giris", json={"eposta": eposta, "sifre": "gizli123"}).json()["token"]}
    for m, yol in uclar():
        if m == "GET" or (m, yol) in ACIK_UCLAR or yol in ("/api/cikis",):
            continue
        r = client.request(m, doldur(yol), headers=hi, json={})
        assert r.status_code == 403, f"{m} {yol} izleyiciyle {r.status_code}"


def test_firmalar_birbirinin_kaydini_goremez_ve_kullanamaz():
    a = yeni_kullanici(f"{uuid.uuid4().hex}@ornek.com")
    b = yeni_kullanici(f"{uuid.uuid4().hex}@ornek.com")
    iz = "GIZLIFIRMAB"
    cari = client.post("/api/cariler", json={"unvan": f"{iz} Cari", "vkn": "1111111111"}, headers=b).json()
    st = client.post("/api/santiyeler", json={"ad": f"{iz} Şantiye"}, headers=b).json()
    hesap = client.post("/api/banka-hesaplari", json={"ad": f"{iz} Banka"}, headers=b).json()
    f = client.post("/api/faturalar", json={"yon": "gelen", "fatura_no": f"{iz}1", "cari_id": cari["id"], "santiye_id": st["id"],
                                             "kalemler": [{"aciklama": f"{iz} kalem", "birim_fiyat": 100, "kdv_orani": 20}]}, headers=b).json()
    cek = client.post("/api/cekler", json={"yon": "alinan", "cek_no": f"{iz}9", "tutar": 50, "vade": "2026-12-01", "cari_id": cari["id"]}, headers=b).json()
    hr = client.post("/api/hareketler", json={"tarih": "2026-10-01", "yon": "giris", "tur": "tahsilat", "tutar": 10, "cari_id": cari["id"],
                                               "banka_hesap_id": hesap["id"], "aciklama": iz}, headers=b).json()
    # A'nın tüm liste/rapor uçlarında B'nin hiçbir kaydı görünmez
    for m, yol in uclar():
        if m != "GET" or "{" in yol or (m, yol) in ACIK_UCLAR:
            continue
        r = client.get(yol, headers=a)
        assert iz.lower() not in r.text.lower(), f"{yol} B firmasının verisini gösteriyor"
    # Kimlikle erişim: B'nin kayıtları A'ya yok
    for yol in (f"/api/faturalar/{f['id']}", f"/api/cekler/{cek['id']}"):
        assert client.get(yol, headers=a).status_code == 404
    for yol, govde in ((f"/api/cariler/{cari['id']}", {"unvan": "x"}), (f"/api/santiyeler/{st['id']}", {"ad": "x"}),
                       (f"/api/banka-hesaplari/{hesap['id']}", {"ad": "x"}), (f"/api/hareketler/{hr['id']}",
                       {"tarih": "2026-10-01", "yon": "giris", "tur": "tahsilat", "tutar": 1})):
        assert client.put(yol, json=govde, headers=a).status_code in (404, 422), yol
        assert client.delete(yol, headers=a).status_code == 404, yol
    # A, B'nin carisini/şantiyesini/hesabını kendi kaydında kullanamaz
    assert client.post("/api/faturalar", json={"yon": "gelen", "cari_id": cari["id"], "kalemler": []}, headers=a).status_code == 404
    assert client.post("/api/faturalar", json={"yon": "gelen", "santiye_id": st["id"], "kalemler": []}, headers=a).status_code == 404
    assert client.post("/api/cekler", json={"yon": "alinan", "tutar": 5, "vade": "2026-12-01", "cari_id": cari["id"]}, headers=a).status_code == 404
    assert client.post("/api/hareketler", json={"tarih": "2026-10-01", "yon": "giris", "tur": "tahsilat", "tutar": 1,
                                                "banka_hesap_id": hesap["id"]}, headers=a).status_code == 404
    acek = client.post("/api/cekler", json={"yon": "alinan", "tutar": 5, "vade": "2026-12-01"}, headers=a).json()
    assert client.post(f"/api/cekler/{acek['id']}/islem", json={"islem": "tahsile_ver", "tarih": "2026-10-02",
                                                                "banka_hesap_id": hesap["id"]}, headers=a).status_code == 404
    assert client.post(f"/api/cekler/{acek['id']}/islem", json={"islem": "ciro", "tarih": "2026-10-02",
                                                                "cari_id": cari["id"]}, headers=a).status_code == 404
    # B'nin kayıtları sağlam
    assert client.get(f"/api/faturalar/{f['id']}", headers=b).status_code == 200


def test_agdan_hesap_acilamaz_sifre_denemesi_sinirli_eski_oturum_gecersiz():
    from datetime import datetime, timedelta

    from fastapi.testclient import TestClient

    from app.db import SessionLocal
    from app.models import Oturum
    from app.routers import temel
    eposta = f"{uuid.uuid4().hex}@ornek.com"
    yeni_kullanici(eposta)
    uzak = TestClient(app, client=("192.168.1.50", 50000))
    r = uzak.post("/api/kayit", json={"sirket_unvan": "X", "ad": "X", "eposta": f"{uuid.uuid4().hex}@o.com", "sifre": "gizli123"})
    assert r.status_code == 403
    assert client.post("/api/kayit", json={"sirket_unvan": "X", "ad": "X", "eposta": f"{uuid.uuid4().hex}@o.com", "sifre": "12"}).status_code == 422
    # Aynı bilgisayardan 5 hatalı denemeden sonra doğru şifre de 10 dakika kabul edilmez
    for _ in range(temel.HATALI_GIRIS_SINIRI):
        assert uzak.post("/api/giris", json={"eposta": eposta, "sifre": "yanlis"}).status_code == 401
    assert uzak.post("/api/giris", json={"eposta": eposta, "sifre": "gizli123"}).status_code == 429
    # Kilit veritabanında: program yeniden açılsa da sürer
    from app.models import HataliGiris
    with SessionLocal() as db:
        assert db.query(HataliGiris).filter(HataliGiris.ip == "192.168.1.50").count() == temel.HATALI_GIRIS_SINIRI
        db.query(HataliGiris).filter(HataliGiris.ip == "192.168.1.50").update({"zaman": 0})  # 10 dakika geçmiş gibi
        db.commit()
    token = uzak.post("/api/giris", json={"eposta": eposta, "sifre": "gizli123"}).json()["token"]
    hh = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/ben", headers=hh).status_code == 200
    with SessionLocal() as db:
        db.get(Oturum, token).olusturma = datetime.utcnow() - timedelta(days=31)
        db.commit()
    assert client.get("/api/ben", headers=hh).status_code == 401


def test_kur_yeniden_baslatma_komutunda_tirnak_yok():
    """Windows'ta cmd iç içe/kaçışlı tırnağı anlamaz ('\\"Muhasebe Programi\\"' bulunamıyor hatası)."""
    import subprocess
    from pathlib import PureWindowsPath
    from app.main import _baslat_komutu
    komut = subprocess.list2cmdline(_baslat_komutu(PureWindowsPath(r"C:\\Users\\G\\Masaüstü\\Muhasebe-deneme (1)\\Muhasebe\\baslat.bat")))
    assert komut == "cmd.exe /c baslat.bat" and '"' not in komut


def test_baslat_el_yazisi_icin_uygun_python_secer():
    # El yazısı paketi (onnxruntime) Python 3.14+ için yok: baslat.bat önce 3.12/3.13 arar, yoksa winget ile 3.12 kurar,
    # ortam uygun olmayan Python ile kurulduysa onu bir kez yeniden kurar
    from pathlib import Path
    bat = (Path(__file__).resolve().parents[2] / "baslat.bat").read_bytes().decode()
    assert "\r\n" in bat and "\n" not in bat.replace("\r\n", "")
    bul = bat[bat.index(":py_bul\r\n"):]
    assert bul.index("py -3.12") < bul.index("py -3.13") < bul.index("Python312")
    assert bat.index("call :py_bul") < bat.index('set "PY_YEDEK=py -3"')
    assert "winget install -e --id Python.Python.3.12" in bat
    assert 'ren ".venv" ".venv-eski"' in bat and "call :py_uygun %PY% || goto venv_var" in bat


def test_butun_yuklemelerde_ayni_boyut_siniri():
    # Her dosya yükleme ucu dosyayı parça parça okur, 25 MB'ı aşınca durur ve kısa Türkçe mesaj verir
    from app import yukleme
    h = yeni_kullanici(f"{uuid.uuid4().hex}@ornek.com")
    hesap = client.post("/api/banka-hesaplari", json={"ad": "Sınır Bankası"}, headers=h).json()["id"]
    buyuk = b"0" * (yukleme.EN_BUYUK_DOSYA + 1)
    uclar_ = ["/api/excel/faturalar/yukle", "/api/excel/cekler/onizle", "/api/excel/cekler/yukle",
              f"/api/banka-hesaplari/{hesap}/ekstre", "/api/cekler/oku", "/api/faturalar/oku",
              "/api/kredi-karti-ekstresi", "/api/excel/cariler/yukle", "/api/taseron-giderleri/bordro-onizle"]
    def gez(routes):
        for r in routes:
            if getattr(r, "original_router", None) is not None:
                yield from gez(r.original_router.routes)
            elif hasattr(r, "dependant"):
                yield r
    yuklemeler = [r.path for r in gez(app.routes) if any(p.name in ("dosya", "dosyalar") for p in r.dependant.body_params)]
    for ucu in uclar_:
        assert any(re.fullmatch(re.sub(r"\{[^}]+\}", r"[^/]+", y), ucu) for y in yuklemeler), ucu
        r = client.post(ucu, files={"dosya": ("buyuk.pdf", buyuk, "application/pdf")}, headers=h)
        assert r.status_code == 413 and "en çok 25 MB" in r.json()["detail"], (ucu, r.status_code, r.text[:200])
    assert len(yuklemeler) == len(uclar_) + 2  # + toplu çek okuma ve çek okuma raporu (aşağıda)
    r = client.post("/api/cekler/oku-toplu", files=[("dosyalar", ("buyuk.pdf", buyuk, "application/pdf"))], headers=h)
    assert r.status_code == 200 and "en çok 25 MB" in str(r.json())
    r = client.post("/api/cekler/okuma-raporu", files=[("dosyalar", ("buyuk.pdf", buyuk, "application/pdf"))], headers=h)
    assert r.status_code == 413 and "en çok 25 MB" in r.json()["detail"]
    # Toplu fatura ZIP'i daha büyük olabilir
    assert yukleme.sinir("faturalar.zip") > yukleme.EN_BUYUK_DOSYA == yukleme.sinir("fatura.pdf")
