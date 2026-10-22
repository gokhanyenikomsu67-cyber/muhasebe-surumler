"""Kişi bazında bölüm yetkileri (sentetik veri)."""
import importlib
import pkgutil
import uuid

from app import yetki
from tests.test_api import client, yeni_kullanici


def _uye(h, yetkiler):
    eposta = f"{uuid.uuid4().hex}@ornek.com"
    r = client.post("/api/kullanicilar", json={"ad": "Üye", "eposta": eposta, "sifre": "gizli123", "rol": "muhasebeci",
                                              "yetkiler": yetkiler}, headers=h)
    assert r.status_code == 200, r.text
    t = client.post("/api/giris", json={"eposta": eposta, "sifre": "gizli123"}).json()["token"]
    return r.json()["id"], {"Authorization": f"Bearer {t}"}


def test_butun_uclarin_bolumu_var():
    import app.routers as R
    eksik = []
    for m in pkgutil.iter_modules(R.__path__):
        for r in importlib.import_module(f"app.routers.{m.name}").router.routes:
            for yontem in r.methods:
                if r.path.startswith("/api/") and r.path not in ("/api/giris", "/api/kayit") and \
                        not yetki.acik_mi(yontem, r.path) and yetki.bolum(r.path) is None:
                    eksik.append(f"{yontem} {r.path}")
    assert eksik == []


def test_duzey():
    assert yetki.duzey("POST", "/api/faturalar/toplu-sil") == "sil"
    assert yetki.duzey("POST", "/api/faturalar/5/iptal") == "duzenle"
    assert yetki.duzey("POST", "/api/faturalar/5/onayla") == "ekle"
    assert yetki.duzey("PUT", "/api/cekler/5") == "duzenle"


def test_yalniz_fatura_girisi_yalniz_banka_yalniz_goruntuleme():
    h = yeni_kullanici(f"{uuid.uuid4().hex}@ornek.com")
    _, fh = _uye(h, {"fatura": ["ekle"]})  # giren görür de
    ben = client.get("/api/ben", headers=fh).json()
    assert ben["yetkiler"]["fatura"] == ["gor", "ekle"] and ben["yetkiler"]["banka"] == []
    # Fatura girer; fatura girerken yeni cari açabilir; banka ve çek göremez, fatura silemez
    c = client.post("/api/cariler", json={"unvan": "Deneme Satıcı"}, headers=fh)
    assert c.status_code == 200
    f = client.post("/api/faturalar", json={"yon": "gelen", "fatura_no": "DNM1", "tarih": "2026-09-10", "cari_id": c.json()["id"],
                                            "kalemler": [{"aciklama": "Kum", "miktar": 1, "birim_fiyat": 100, "kdv_orani": 20}]}, headers=fh)
    assert f.status_code == 200
    assert client.post(f"/api/faturalar/{f.json()['id']}/onayla", headers=fh).status_code == 200
    assert client.get("/api/faturalar", headers=fh).status_code == 200
    assert client.post("/api/faturalar/toplu-sil", json={"idler": [f.json()["id"]]}, headers=fh).status_code == 403
    assert client.get("/api/hareketler", headers=fh).status_code == 403
    assert client.get("/api/cekler", headers=fh).status_code == 403
    r = client.get("/api/raporlar/kdv", headers=fh)
    assert r.status_code == 403 and "yetkiniz yok" in r.json()["detail"]
    # Kullanıcı ekleyemez (sahip işi)
    assert client.post("/api/kullanicilar", json={"ad": "x", "eposta": "x@ornek.com", "sifre": "gizli123"}, headers=fh).status_code == 403
    # Yalnız banka
    _, bh = _uye(h, {"banka": ["gor", "ekle", "duzenle"]})
    assert client.get("/api/hareketler", headers=bh).status_code == 200
    assert client.get("/api/faturalar", headers=bh).status_code == 403
    # Yalnız görüntüleme: her bölümü görür, hiçbir şey giremez
    gid, gh = _uye(h, {b: ["gor"] for b in yetki.BOLUMLER})
    assert client.get("/api/faturalar", headers=gh).status_code == 200
    assert client.post("/api/cariler", json={"unvan": "Olmaz"}, headers=gh).status_code == 403
    # Sahip yetkiyi sonradan değiştirir
    assert client.put(f"/api/kullanicilar/{gid}", json={"yetkiler": {"cari": ["ekle"]}}, headers=h).status_code == 200
    assert client.post("/api/cariler", json={"unvan": "Artık Olur"}, headers=gh).status_code == 200
    assert client.get("/api/faturalar", headers=gh).status_code == 403
    liste = client.get("/api/kullanicilar", headers=h).json()
    assert set(liste["bolumler"]) == set(yetki.BOLUMLER)
    assert [x["yetkiler"]["cari"] for x in liste["kullanicilar"] if x["id"] == gid] == [["gor", "ekle"]]
