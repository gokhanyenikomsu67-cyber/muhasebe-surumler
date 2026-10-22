"""Yedek gerçekten geri yüklenebiliyor mu: doğrulama, bozuk yedeğin reddi, yedeğe dönüş ve haftalık deneme."""
import uuid
import zipfile
from pathlib import Path

from app import yedek
from tests.test_api import client, yeni_kullanici


def test_yedek_dogrulanir_geri_yuklenir_bozugu_reddedilir(tmp_path, monkeypatch):
    monkeypatch.setenv("MUHASEBE_YEDEK_KLASORLERI", str(tmp_path / "y1"))
    h = yeni_kullanici(f"{uuid.uuid4().hex}@ornek.com")
    cari = client.post("/api/cariler", json={"unvan": "Yedekten Önce Ltd"}, headers=h).json()
    r = client.post("/api/yedekler", headers=h).json()
    assert r["hedefler"][0]["ok"]
    d = yedek.durum()["son_yedek"]
    assert d["ok"] and d["dosya"] == r["dosya"]
    zip_yolu = tmp_path / "y1" / r["dosya"]
    assert yedek.yedegi_dogrula(zip_yolu)["ok"]
    # Yedekten sonra yapılan değişiklik yedeğe dönünce gider, önceki kayıt geri gelir
    client.delete(f"/api/cariler/{cari['id']}", headers=h)
    client.post("/api/cariler", json={"unvan": "Yedekten Sonra Ltd"}, headers=h)
    g = client.post("/api/yedekler/geri-yukle", json={"klasor": str(tmp_path / "y1"), "dosya": r["dosya"]}, headers=h)
    assert g.status_code == 200, g.text
    adlar = [c["unvan"] for c in client.get("/api/cariler", headers=h).json()]
    assert "Yedekten Önce Ltd" in adlar and "Yedekten Sonra Ltd" not in adlar
    # Dönmeden önce bugünkü veri yedeklendi: o yedekte "sonra" carisi var
    assert (tmp_path / "y1" / g.json()["onceki_yedek"]).exists()
    # Bozuk yedek: doğrulama yakalar, geri yükleme hiçbir şeyi değiştirmez
    bozuk = tmp_path / "y1" / "muhasebe-yedek-20200101-000000.zip"
    with zipfile.ZipFile(bozuk, "w") as z:
        z.writestr("muhasebe.db", b"bu bir veritabani degil" * 100)
    assert not yedek.yedegi_dogrula(bozuk)["ok"]
    g = client.post("/api/yedekler/geri-yukle", json={"klasor": str(tmp_path / "y1"), "dosya": bozuk.name}, headers=h)
    assert g.status_code == 422 and "değiştirilmedi" in g.json()["detail"]
    assert "Yedekten Önce Ltd" in [c["unvan"] for c in client.get("/api/cariler", headers=h).json()]
    # Yedek klasörü dışındaki dosya istenemez
    assert client.post("/api/yedekler/geri-yukle", json={"klasor": str(tmp_path), "dosya": "../x.zip"}, headers=h).status_code == 404
    # Haftalık deneme: son yedek açılıp denenir
    assert client.post("/api/yedekler/dene", headers=h).json()["ok"]
    assert yedek.son_yedegi_dene() is None  # bir hafta dolmadan tekrar denenmez


def test_yedek_silme_en_sonu_korur_kopyalari_sorar(tmp_path, monkeypatch):
    y1, y2 = tmp_path / "y1", tmp_path / "drive"
    monkeypatch.setenv("MUHASEBE_YEDEK_KLASORLERI", f"{y1};{y2}")
    h = yeni_kullanici(f"{uuid.uuid4().hex}@ornek.com")
    for ad in ("muhasebe-yedek-20261001-100000.zip", "muhasebe-yedek-20261002-100000.zip"):
        for k in (y1, y2):
            k.mkdir(exist_ok=True)
            (k / ad).write_bytes(b"x")
    son = client.post("/api/yedekler", headers=h).json()["dosya"]
    sil = lambda secilen, diger=False: client.post("/api/yedekler/sil", headers=h, json={  # noqa: E731
        "secilenler": [{"klasor": str(k), "dosya": d} for k, d in secilen], "diger_kopyalar": diger})
    # Yalnız seçilen klasördeki kopya silinir; istenirse Drive'daki kopyası da
    assert sil([(y1, "muhasebe-yedek-20261001-100000.zip")]).json()["silinen"] == 1
    assert (y2 / "muhasebe-yedek-20261001-100000.zip").exists()
    assert sil([(y1, "muhasebe-yedek-20261002-100000.zip")], True).json()["silinen"] == 2
    assert not (y2 / "muhasebe-yedek-20261002-100000.zip").exists()
    # En son yedeğin bütün kopyaları silinemez; bir klasördeki kopyası silinebilir
    r = sil([(y1, son), (y2, son)])
    assert r.status_code == 400 and "En son yedek silinemez" in r.json()["detail"]
    assert sil([(y1, son)], True).status_code == 400
    assert sil([(y2, son)]).json()["silinen"] == 1 and (y1 / son).exists()


def test_eski_yedekler_adetle_sinirli_belgeler_bir_kez_saklanir(tmp_path, monkeypatch):
    import os
    import time
    monkeypatch.setattr(yedek, "SAKLAMA_ADEDI", 3)
    adlar = [f"muhasebe-yedek-202610{g:02d}-100000.zip" for g in range(1, 8)]
    for ad in adlar:
        (tmp_path / ad).write_bytes(b"x")
    yedek.eskileri_sil(tmp_path)
    assert sorted(d.name for d in tmp_path.iterdir()) == adlar[-3:]  # aynı ay: en yeni 3 (ayın sonuncusu da içinde)
    # Aynı belge ikinci kez yüklenince yeniden saklanmaz
    from app.routers.faturalar import DOSYA_KLASORU, _dosya_kaydet
    icerik = uuid.uuid4().bytes * 100
    assert _dosya_kaydet(icerik, "pdf") == _dosya_kaydet(icerik, "pdf")
    # Kayda bağlı olmayan eski belge yedeğe girmez, yenisi girer
    eski = DOSYA_KLASORU / f"{uuid.uuid4().hex}.pdf"
    eski.write_bytes(b"eski")
    os.utime(eski, (time.time() - 30 * 86400,) * 2)
    yeni = DOSYA_KLASORU / f"{uuid.uuid4().hex}.pdf"
    yeni.write_bytes(b"yeni")
    monkeypatch.setenv("MUHASEBE_YEDEK_KLASORLERI", str(tmp_path / "y"))
    r = yedek.yedek_al()
    with zipfile.ZipFile(tmp_path / "y" / r["dosya"]) as z:
        adlar = set(z.namelist())
        liste = set(z.read("belgeler.txt").decode().split())
    # Belgeler ZIP'e değil yedek klasörünün belge deposuna bir kez kopyalanır; ZIP'te yalnız listesi olur
    assert not any(a.startswith("belgeler/") for a in adlar)
    assert yeni.name in liste and eski.name not in liste
    depo = tmp_path / "y" / yedek.BELGE_KLASORU
    assert (depo / yeni.name).read_bytes() == b"yeni" and not (depo / eski.name).exists()
    # Dördüncü yedekten sonra en eski yedek silinir; kullanılmayan belge depodan da silinir
    yeni.unlink()
    for _ in range(3):
        time.sleep(1.05)
        yedek.yedek_al()
    assert len(list((tmp_path / "y").glob("muhasebe-yedek-*.zip"))) == 3
    assert not (depo / yeni.name).exists()
    eski.unlink()
