"""Kendi kendini güncelleme: paket doğrulanır, veri/ayar/ortam dosyalarına dokunulmaz, eski sürüm geri konabilir."""
import zipfile

import pytest

from app import guncelleme


def paket(yol, surum="2026-10-22 abcdef1", kok="Muhasebe/", ek=None):
    dosyalar = {"baslat.bat": "@echo off\r\nyeni\r\n", "backend/app/main.py": "# yeni\n", "web/app.js": "// yeni\n",
                "backend/requirements.txt": "fastapi\n", "backend/app/surum.py": f'_HAM = "{surum}"\n',
                ".env": "ANTHROPIC_API_KEY=pakettegelen\n", "backend/.venv/x.txt": "paketten", **(ek or {})}
    with zipfile.ZipFile(yol, "w") as z:
        for ad, icerik in dosyalar.items():
            z.writestr(kok + ad, icerik)
    return yol


@pytest.fixture
def program(tmp_path, monkeypatch):
    p = tmp_path / "program"
    (p / "backend/app").mkdir(parents=True)
    (p / "web").mkdir()
    (p / "backend/.venv").mkdir()
    (p / "baslat.bat").write_text("eski bat")
    (p / "backend/app/main.py").write_text("# eski\n")
    (p / "web/app.js").write_text("// yeni\n")  # değişmeyen dosya
    (p / ".env").write_text("ANTHROPIC_API_KEY=benim\n")
    (p / "backend/.venv/x.txt").write_text("ortam")
    for ad in ("PROGRAM", "BEKLIYOR", "DENENIYOR", "SONUC", "ESKI"):
        deger = getattr(guncelleme, ad)
        monkeypatch.setattr(guncelleme, ad, p if ad == "PROGRAM" else p / deger.name)
    return p


def test_uygula_ve_geri_al(program, tmp_path):
    zip_yolu = paket(tmp_path / "yeni.zip", ek={"backend/app/yeni_modul.py": "x = 1\n"})
    assert guncelleme.paket_surumu(zip_yolu) == "2026-10-22 abcdef1"
    guncelleme.BEKLIYOR.write_text(str(zip_yolu))
    guncelleme.uygula()
    assert (program / "baslat.bat").read_bytes() == b"@echo off\r\nyeni\r\n"
    assert (program / "backend/app/main.py").read_text() == "# yeni\n" and (program / "backend/app/yeni_modul.py").exists()
    # Ayar, program ortamı ve veriye dokunulmaz; değişen dosyanın eskisi saklanır, değişmeyen kopyalanmaz
    assert (program / ".env").read_text() == "ANTHROPIC_API_KEY=benim\n" and (program / "backend/.venv/x.txt").read_text() == "ortam"
    assert (program / "eski-surum/backend/app/main.py").read_text() == "# eski\n" and not (program / "eski-surum/web/app.js").exists()
    assert guncelleme.DENENIYOR.exists() and not guncelleme.BEKLIYOR.exists()
    # Yeni sürüm açılamazsa eski sürüm geri konur, güncellemenin eklediği dosya silinir
    guncelleme.geri_al()
    assert (program / "backend/app/main.py").read_text() == "# eski\n" and (program / "baslat.bat").read_text() == "eski bat"
    assert not (program / "backend/app/yeni_modul.py").exists() and not guncelleme.DENENIYOR.exists()


def test_bozuk_ya_da_yabanci_paket_uygulanmaz(program, tmp_path):
    yabanci = tmp_path / "yabanci.zip"
    with zipfile.ZipFile(yabanci, "w") as z:
        z.writestr("baska/oku.txt", "x")
    guncelleme.BEKLIYOR.write_text(str(yabanci))
    with pytest.raises(guncelleme.GuncellemeHatasi):
        guncelleme.uygula()
    assert (program / "backend/app/main.py").read_text() == "# eski\n"


def test_denetim_klasorden_ve_githubdan(program, tmp_path, monkeypatch):
    monkeypatch.setattr(guncelleme, "_surum", lambda: "2026-10-21 1111111")
    monkeypatch.setattr(guncelleme, "_durum_dosyasi", lambda: tmp_path / "g.json")
    klasor = tmp_path / "drive"
    klasor.mkdir()
    paket(klasor / "Muhasebe-deneme.zip", "2026-10-22 2222222")
    monkeypatch.setenv("MUHASEBE_GUNCELLEME_KLASORU", str(klasor))
    d = guncelleme.denetle(zorla=True)
    assert d["var"] and d["yeni"] == "2026-10-22 2222222" and d["kaynak"] == "klasor"
    # Sürüm deposu: surum.txt bizimkiyse güncel; daha yeniyse yeni sürüm var. İnternet yoksa hata sessizce yazılır
    monkeypatch.delenv("MUHASEBE_GUNCELLEME_KLASORU")
    monkeypatch.setattr(guncelleme, "_indir", lambda url, hedef=None: b"2026-10-21 1111111\n")
    assert not guncelleme.denetle(zorla=True)["var"]
    monkeypatch.setattr(guncelleme, "_indir", lambda url, hedef=None: b"<html>404</html>")
    assert "okunamad" in guncelleme.denetle(zorla=True)["hata"]
    monkeypatch.setattr(guncelleme, "_indir", lambda url, hedef=None: b"2026-10-23 3333333\n")
    assert guncelleme.denetle(zorla=True)["yeni"] == "2026-10-23 3333333"
    # Günde bir kez: zorlanmadıkça aynı gün yeniden internete gidilmez
    monkeypatch.setattr(guncelleme, "_indir", lambda *a, **k: (_ for _ in ()).throw(OSError("internet yok")))
    assert guncelleme.denetle()["yeni"] == "2026-10-23 3333333"
    d = guncelleme.denetle(zorla=True)
    assert not d["var"] and "ulaşılamadı" in d["hata"]
