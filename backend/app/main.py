import os
import re
import threading
import time
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import onarim, yedek
from .auth import aktif_kullanici, yazabilir
from . import gecmis as degisiklik_gecmisi
from .db import Base, SessionLocal, db_guncelle, engine
from .models import Kullanici
from .routers import (aktarim, ana_depo, banka, cekler, faturalar, gecmis, kartlar, kolaylik, malzemeler, mali, mutabakat,
                      raporlar, reddedilen, taseron, temel, wolvox, yazdir)

Base.metadata.create_all(engine)
degisiklik_gecmisi.kur(SessionLocal)
db_guncelle(engine)

app = FastAPI(title="Muhasebe")
app.include_router(temel.router)
app.include_router(faturalar.router)
app.include_router(raporlar.router)
app.include_router(cekler.router)
app.include_router(banka.router)
app.include_router(kartlar.router)
app.include_router(aktarim.router)
app.include_router(mali.router)
app.include_router(yazdir.router)
app.include_router(kolaylik.router)
app.include_router(gecmis.router)
app.include_router(mutabakat.router)
app.include_router(reddedilen.router)
app.include_router(taseron.router)
app.include_router(malzemeler.router)
app.include_router(wolvox.router)
app.include_router(ana_depo.router)

WEB = Path(__file__).resolve().parents[2] / "web"
app.mount("/web", StaticFiles(directory=WEB), name="web")


@app.middleware("http")
async def onbellek_yok(istek, sonraki):
    """Ekran dosyaları tarayıcı önbelleğinde kalmasın: yeni paket kurulunca eski app.js çalışmaya devam ediyordu."""
    yanit = await sonraki(istek)
    if istek.url.path == "/" or istek.url.path.startswith("/web/"):
        yanit.headers["Cache-Control"] = "no-cache, must-revalidate"
    return yanit


@app.get("/")
def anasayfa():
    # Dosya adına sürüm eklenir (değiştirilme zamanı): tarayıcı yeni sürümü kesin yükler
    from fastapi.responses import HTMLResponse
    surum = int(max((WEB / a).stat().st_mtime for a in ("app.js", "style.css")))
    html = (WEB / "index.html").read_text(encoding="utf-8")
    html = html.replace('/web/app.js"', f'/web/app.js?v={surum}"').replace('/web/style.css"', f'/web/style.css?v={surum}"')
    return HTMLResponse(html, headers={"Cache-Control": "no-cache, must-revalidate"})


@app.get("/api/yedekler")
def yedek_listesi(k: Kullanici = Depends(aktif_kullanici)):
    return yedek.yedekler()


@app.post("/api/yedekler")
def yedek_olustur(k: Kullanici = Depends(aktif_kullanici)):
    if k.rol != "sahip":
        raise HTTPException(403, "Yedeği sadece sahip alabilir.")
    try:
        return yedek.yedek_al()
    except RuntimeError as e:
        raise HTTPException(500, f"Yedek alınamadı: {e}") from e


class YedekKlasorleri(BaseModel):
    klasorler: list[str]


@app.get("/api/yedekler/klasorler")
def yedek_klasorleri(k: Kullanici = Depends(aktif_kullanici)):
    return {"klasorler": [str(x) for x in yedek.hedef_klasorler()], "secildi": yedek.secilen_klasorler() is not None}


@app.put("/api/yedekler/klasorler")
def yedek_klasorlerini_sec(istek: YedekKlasorleri, k: Kullanici = Depends(aktif_kullanici)):
    """Yedeklerin alınacağı klasörler (ana bilgisayarda); yalnız sahip seçer."""
    if k.rol != "sahip":
        raise HTTPException(403, "Yedek klasörünü sadece sahip seçebilir.")
    try:
        return {"klasorler": yedek.klasorleri_sec(istek.klasorler)}
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


@app.get("/api/yedekler/klasor-gez")
def yedek_klasor_gez(yol: str = "", k: Kullanici = Depends(aktif_kullanici)):
    if k.rol != "sahip":
        raise HTTPException(403, "Yedek klasörünü sadece sahip seçebilir.")
    try:
        return yedek.klasor_gez(yol)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e


class GeriYukleme(BaseModel):
    klasor: str
    dosya: str


@app.post("/api/yedekler/geri-yukle")
def yedege_don(istek: GeriYukleme, k: Kullanici = Depends(yazabilir)):
    """Seçilen yedeğe döner (önce bugünkü veri yedeklenir, yedek doğrulanmadan hiçbir şey değişmez)."""
    if k.rol != "sahip":
        raise HTTPException(403, "Yedeğe dönmeyi sadece sahip yapabilir.")
    try:
        yol = yedek.yedek_bul(istek.klasor, istek.dosya)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e
    from .routers.faturalar import KAYIT_KILIDI
    try:
        with KAYIT_KILIDI:
            return yedek.geri_yukle(yol)
    except RuntimeError as e:
        raise HTTPException(422, str(e)) from e


class YedekSilme(BaseModel):
    secilenler: list[GeriYukleme]
    diger_kopyalar: bool = False


@app.post("/api/yedekler/sil")
def yedekleri_sil(istek: YedekSilme, k: Kullanici = Depends(yazabilir)):
    if k.rol != "sahip":
        raise HTTPException(403, "Yedekleri sadece sahip silebilir.")
    try:
        return yedek.yedekleri_sil([(s.klasor, s.dosya) for s in istek.secilenler], istek.diger_kopyalar)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


class Sifirlama(BaseModel):
    onay: str


@app.post("/api/sistem/sifirla")
def verileri_sifirla(istek: Sifirlama, k: Kullanici = Depends(yazabilir)):
    """Deneme verilerini siler: faturalar, ekstre/banka/kasa hareketleri, çekler, cariler, şantiyeler, banka hesapları,
    düzenli ödemeler. Firma bilgileri ve kullanıcılar kalır. Önce yedek alınır (Yedekler > "Bu yedeğe dön" ile geri gelir)."""
    from sqlalchemy import delete, select, update
    from .models import (BankaHesabi, Cari, Cek, Degisiklik, Depo, DuzenliOdeme, Fatura, FaturaKalem, Hareket, IsyeriEslesme,
                         Malzeme, RedFatura, Santiye, TaseronGider, WolvoxAktarim)
    from .routers.faturalar import KAYIT_KILIDI
    if k.rol != "sahip":
        raise HTTPException(403, "Verileri sadece sahip sıfırlayabilir.")
    if istek.onay.strip().upper().replace("İ", "I") != "SIFIRLA":
        raise HTTPException(400, "Onay için SIFIRLA yazın.")
    with KAYIT_KILIDI:
        try:
            yd = yedek.yedek_al()
        except Exception as e:  # noqa: BLE001 - yedek alınamazsa hiçbir şey silinmez
            raise HTTPException(500, f"Önce yedek alınamadı, hiçbir şey silinmedi: {e}") from e
        db = SessionLocal()
        try:
            sid = k.sirket_id
            sayilar = {"fatura": db.query(Fatura).filter(Fatura.sirket_id == sid).count(),
                       "hareket": db.query(Hareket).filter(Hareket.sirket_id == sid).count(),
                       "cek": db.query(Cek).filter(Cek.sirket_id == sid).count(),
                       "cari": db.query(Cari).filter(Cari.sirket_id == sid).count()}
            db.execute(update(Hareket).where(Hareket.sirket_id == sid).values(bagli_hareket_id=None))
            db.execute(delete(FaturaKalem).where(FaturaKalem.fatura_id.in_(select(Fatura.id).where(Fatura.sirket_id == sid))))
            for model in (Degisiklik, DuzenliOdeme, TaseronGider, Hareket, Cek, Fatura, RedFatura, IsyeriEslesme, BankaHesabi, Depo,
                          Santiye, Malzeme, WolvoxAktarim, Cari):
                db.execute(delete(model).where(model.sirket_id == sid))
            db.commit()
            # Hiçbir kayda bağlı kalmayan belgeler (fatura/çek dosyaları) de silinir; yedekte duruyorlar
            from .routers.faturalar import DOSYA_KLASORU
            kullanilan = {a for f in db.query(Fatura).all() for a in (f.kaynak_dosya, f.xml_dosya) if a} | \
                {c.kaynak_dosya for c in db.query(Cek).all() if c.kaynak_dosya}
            for dosya in DOSYA_KLASORU.iterdir():
                if dosya.is_file() and dosya.name not in kullanilan:
                    dosya.unlink(missing_ok=True)
        finally:
            db.close()
    return {"ok": True, "yedek": yd, **sayilar}


@app.post("/api/yedekler/dene")
def yedegi_dene(k: Kullanici = Depends(yazabilir)):
    """Son yedeği geçici veritabanına açıp dener (asıl veriye dokunmaz)."""
    return yedek.son_yedegi_dene(zorla=True) or {"ok": False, "hata": "Henüz yedek yok."}


_KURULUM = {"durum": None, "hata": None}  # Tesseract kurulumu: None | "kuruluyor" | "bitti" | "hata"
VENV = Path(__file__).resolve().parents[1] / ".venv"


@app.get("/api/sistem-durumu")
def sistem_durumu(k: Kullanici = Depends(aktif_kullanici)):
    """Genel Durum'daki tek satırlık uyarılar için: resim okuma programı, ek paketler, son yedek ve son yedek denemesi."""
    from . import ocr
    try:
        ek_hata = (VENV / "kurulum-hatasi.txt").read_text(encoding="utf-8", errors="replace").strip() or None
    except OSError:
        ek_hata = None
    d = yedek.durum()
    from .surum import ek_paketler
    return {"ocr_var": ocr.var_mi(), "ocr_kurulum": _KURULUM, "kurulabilir": os.name == "nt", "ek_paket_hatasi": ek_hata,
            "ek_paketler": ek_paketler(), "ek_kurulum": _ek_kurulum_durumu(),
            "son_yedek": d.get("son_yedek"), "son_deneme": d.get("son_deneme"), "guncelleme": _guncelleme_durumu(),
            "disk": _disk_durumu(), "ag": _ag_durumu()}


def _ag_durumu() -> dict:
    """Öteki bilgisayarlardan erişim açık mı ve bu (ana) bilgisayarın adresleri."""
    import socket
    ad = socket.gethostname()
    ipler = set()
    try:
        for bilgi in socket.getaddrinfo(ad, None, socket.AF_INET):
            ipler.add(bilgi[4][0])
    except OSError:
        pass
    ipler.discard("127.0.0.1")
    return {"acik": os.environ.get("MUHASEBE_AG") == "1", "bilgisayar": ad,
            "adresler": [f"http://{x}:8000" for x in [ad, *sorted(ipler)]]}


class AgModu(BaseModel):
    acik: bool


@app.post("/api/sistem/ag-modu")
def ag_modu(istek: AgModu, k: Kullanici = Depends(yazabilir)):
    """Ofisteki öteki bilgisayarlardan erişimi açar/kapatır: .env'e MUHASEBE_AG yazılır, program yeniden açılır."""
    if k.rol != "sahip":
        raise HTTPException(403, "Bunu sadece sahip yapabilir.")
    kok = Path(__file__).resolve().parents[2]
    bat, env = kok / "baslat.bat", kok / ".env"
    if os.name != "nt" or not bat.exists():
        raise HTTPException(400, "Bu ayar yalnız Windows'ta, baslat.bat ile açılan programda ekrandan yapılır.")
    try:
        # Bayt olarak: dosyadaki öteki satırların kodlaması (Windows'ta ANSI olabilir) bozulmasın
        satirlar = env.read_bytes().splitlines() if env.exists() else []
        satirlar = [x for x in satirlar if not x.strip().startswith(b"MUHASEBE_AG=")] + [b"MUHASEBE_AG=" + (b"1" if istek.acik else b"0")]
        env.write_bytes(b"\r\n".join(satirlar) + b"\r\n")
    except OSError as e:
        raise HTTPException(500, f"Ayar yazılamadı: {e}") from e
    threading.Thread(target=_yeniden_baslat, args=(bat,), daemon=True).start()
    return {"acik": istek.acik, "yeniden_baslatiliyor": True}


def _disk_durumu() -> dict | None:
    try:
        return yedek.disk_durumu()
    except OSError:
        return None


# --- Kendi kendini güncelleme ------------------------------------------------------------------------------------
_GUNCELLEME = {"durum": None, "hata": None}  # None | "hazirlaniyor" | "yeniden_baslatiliyor" | "hata"


def _guncelleme_durumu() -> dict:
    from . import guncelleme
    d = guncelleme.durum()
    try:
        sonuc = guncelleme.SONUC.read_text(encoding="utf-8").strip() or None  # baslat.bat'taki son uygulamanın sonucu
    except OSError:
        sonuc = None
    son = d.get("son_denetim")
    if son and son.get("simdiki") != guncelleme._surum():
        son = None  # program o denetimden sonra güncellendi: eski "yeni sürüm var" uyarısı gösterilmez
    return {**_GUNCELLEME, "son_denetim": son, "son_guncelleme": d.get("son_guncelleme"), "sonuc": sonuc}


@app.post("/api/sistem/guncelleme/denetle")
def guncelleme_denetle(k: Kullanici = Depends(yazabilir)):
    from . import guncelleme
    return guncelleme.denetle(zorla=True)


@app.post("/api/sistem/guncelleme/sonucu-okundu")
def guncelleme_sonucu_okundu(k: Kullanici = Depends(yazabilir)):
    from . import guncelleme
    guncelleme.SONUC.unlink(missing_ok=True)
    return {"ok": True}


def _guncelle() -> None:
    from . import guncelleme
    try:
        guncelleme.hazirla()
    except Exception as e:  # noqa: BLE001
        _GUNCELLEME.update(durum="hata", hata=str(e) if isinstance(e, guncelleme.GuncellemeHatasi)
                           else f"Güncelleme hazırlanamadı: {e}")
        return
    _GUNCELLEME.update(durum="yeniden_baslatiliyor", hata=None)
    _yeniden_baslat(Path(__file__).resolve().parents[2] / "baslat.bat")


@app.post("/api/sistem/guncelle")
def guncelle(k: Kullanici = Depends(yazabilir)):
    """Yeni sürümü indirir, önce yedek alır; program baslat.bat ile kapanıp yeni sürümle yeniden açılır."""
    if k.rol != "sahip":
        raise HTTPException(403, "Güncellemeyi sadece sahip yapabilir.")
    bat = Path(__file__).resolve().parents[2] / "baslat.bat"
    if os.name != "nt" or not bat.exists():
        raise HTTPException(400, "Otomatik güncelleme yalnız Windows'ta, baslat.bat ile açılan programda yapılır.")
    if _GUNCELLEME["durum"] not in ("hazirlaniyor", "yeniden_baslatiliyor"):
        _GUNCELLEME.update(durum="hazirlaniyor", hata=None)
        threading.Thread(target=_guncelle, daemon=True).start()
    return _GUNCELLEME


def _gunluk_guncelleme_denetimi():
    """Açılıştan biraz sonra, günde en çok bir kez yeni sürüm var mı bakılır; internet yoksa sessizce geçilir."""
    from . import guncelleme
    time.sleep(60)
    try:
        guncelleme.denetle()
    except Exception as e:  # noqa: BLE001
        print("Güncelleme denetlenemedi:", e)


_EK_KURULUM = {"durum": None, "hata": None}  # isteğe bağlı paketler (karekod, el yazısı)


def _ek_kurulum_durumu() -> dict:
    """Program içinden kurulum yoksa baslat.bat'ın açılıştaki denemesi başarısız olmuş mu (bugün yeniden denenmez)."""
    if _EK_KURULUM["durum"] is None and any((VENV / ad).exists() for ad in ("el-son-deneme.txt", "ek-son-deneme.txt")):
        return {"durum": "hata", "hata": "Paketler program açılırken kurulamadı. İnternet bağlantısını kontrol edip "
                                         "\"Tekrar dene\"ye basın; yine olmazsa baslat-gunlugu.txt dosyasını gönderin."}
    return _EK_KURULUM


def _ek_paketleri_kur():
    """requirements-ek.txt ve requirements-el.txt ayrı ayrı kurulur (biri kurulamazsa öbürü etkilenmez)."""
    import subprocess
    import sys
    from .surum import ek_paketler
    klasor = Path(__file__).resolve().parents[1]
    hatalar = []
    for dosya in ("requirements-ek.txt", "requirements-el.txt"):
        try:
            r = subprocess.run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--only-binary", ":all:",
                                "--timeout", "30", "-r", str(klasor / dosya)], capture_output=True, timeout=1800,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if r.returncode:
                hatalar.append(dosya)
                cikti = (r.stdout or b"").decode(errors="replace") + (r.stderr or b"").decode(errors="replace")
                if re.search(r"(?i)WinError 5|WinError 32|Access is denied|Erişim engellendi|being used by another process", cikti):
                    _EK_KURULUM["kilitli"] = True
        except (OSError, subprocess.TimeoutExpired):
            hatalar.append(dosya)
    import importlib
    importlib.invalidate_caches()
    durum = ek_paketler()
    if all(durum.values()):
        _EK_KURULUM.update(durum="bitti", hata=None)
    else:
        eksik = [ad for ad, var in (("karekod okuma", durum["karekod"]), ("el yazısı okuma", durum["el_yazisi"])) if not var]
        neden = ("Paket dosyaları açık program tarafından kullanılıyor. Programı kapatıp baslat.bat ile yeniden açın; "
                 "açılırken kurulur." if _EK_KURULUM.pop("kilitli", False) else "İnternet bağlantısını kontrol edip tekrar deneyin.")
        _EK_KURULUM.update(durum="hata", hata=f"{', '.join(eksik).capitalize()} kurulamadı. {neden}")


def _yeniden_baslat(bat: Path) -> None:
    """baslat.bat yeni bir pencerede açılır (bu programı kapatır, paketleri kurar, programı yeniden açar). Yanıt tarayıcıya
    ulaşsın diye biraz beklenir. Komut satırı tırnak içinde tek parametre: cmd'ye iç içe tırnak verilmez."""
    import subprocess
    time.sleep(1.5)
    try:
        (VENV.parent / "yeniden-baslatiliyor.txt").write_text("1")  # eski pencere kapanınca hata mesajı göstermesin
        subprocess.Popen(_baslat_komutu(bat), cwd=str(bat.parent), close_fds=True,
                         creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
    except OSError as e:
        _EK_KURULUM.update(durum="hata", hata=f"Program yeniden açılamadı ({e}). Programı kapatıp baslat.bat ile açın; açılırken kurulur.")


def _baslat_komutu(bat: Path) -> list[str]:
    # Klasör adında boşluk ya da "(1)" gibi karakter olabilir: dosya kendi klasöründen (cwd) adıyla çalıştırılır,
    # böylece komut satırında hiç tırnak gerekmez
    return ["cmd.exe", "/c", bat.name]


@app.post("/api/sistem/ek-paket-kur")
def ek_paket_kur(k: Kullanici = Depends(aktif_kullanici)):
    """Karekod ve el yazısı okuma paketlerini program içinden kurar (şirket sahibi)."""
    if k.rol != "sahip":
        raise HTTPException(403, "Kurulumu sadece sahip başlatabilir.")
    if _EK_KURULUM["durum"] in ("kuruluyor", "yeniden_baslatiliyor"):
        return _EK_KURULUM
    # Paketler kurulurken çalışan program dosyalarını kilitler (Windows): kurulum, programı yeniden açan baslat.bat'a
    # bırakılır. baslat.bat önce bu programı kapatır, paketleri kurar, sonra programı yeniden açar.
    for ad in ("kurulu-requirements-ek.txt", "kurulu-requirements-el.txt", "ek-son-deneme.txt", "el-son-deneme.txt"):
        (VENV / ad).unlink(missing_ok=True)
    bat = Path(__file__).resolve().parents[2] / "baslat.bat"
    (bat.parent / "python312-son-deneme.txt").unlink(missing_ok=True)  # uygun Python kurulumu da yeniden denensin
    if os.name == "nt" and bat.exists():
        _EK_KURULUM.update(durum="yeniden_baslatiliyor", hata=None)
        threading.Thread(target=_yeniden_baslat, args=(bat,), daemon=True).start()
        return _EK_KURULUM
    _EK_KURULUM.update(durum="kuruluyor", hata=None)
    threading.Thread(target=_ek_paketleri_kur, daemon=True).start()
    return _EK_KURULUM


def _tesseract_kur():
    import subprocess
    try:
        sonuc = subprocess.run(["winget", "install", "-e", "--id", "UB-Mannheim.TesseractOCR", "--silent",
                                "--accept-source-agreements", "--accept-package-agreements"],
                               capture_output=True, timeout=1800, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        from . import ocr
        if ocr.var_mi():
            _KURULUM.update(durum="bitti", hata=None)
        else:
            _KURULUM.update(durum="hata", hata=f"Kurulum tamamlanamadı (kod {sonuc.returncode}). İnternet bağlantısını kontrol edip tekrar deneyin.")
    except (OSError, subprocess.TimeoutExpired) as e:
        _KURULUM.update(durum="hata", hata=f"Kurulum başlatılamadı: {e}")


@app.post("/api/sistem/tesseract-kur")
def tesseract_kur(k: Kullanici = Depends(aktif_kullanici)):
    """Resim okuma programını (Tesseract) program içinden kurar; yalnız Windows'ta ve şirket sahibi."""
    from . import ocr
    if k.rol != "sahip":
        raise HTTPException(403, "Kurulumu sadece sahip başlatabilir.")
    if ocr.var_mi():
        return {"durum": "bitti"}
    if os.name != "nt":
        raise HTTPException(400, "Otomatik kurulum yalnız Windows'ta yapılır.")
    if _KURULUM["durum"] != "kuruluyor":
        _KURULUM.update(durum="kuruluyor", hata=None)
        threading.Thread(target=_tesseract_kur, daemon=True).start()
    return _KURULUM


def _gunluk_yedek():
    """Son yedek 24 saatten eskiyse yeni yedek alır; haftada bir son yedeği dener; saatte bir kontrol eder."""
    while True:
        try:
            son = yedek.son_yedek_zamani()
            if son is None or time.time() - son > 86400:
                yedek.yedek_al()
        except Exception as e:  # yedek hatası programı durdurmamalı
            print("Otomatik yedek alınamadı:", e)
        try:
            yedek.son_yedegi_dene()
        except Exception as e:  # noqa: BLE001
            print("Yedek denenemedi:", e)
        time.sleep(3600)


_TOAST = r"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
$t = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$x = $t.GetElementsByTagName("text")
$x.Item(0).AppendChild($t.CreateTextNode($env:MUHASEBE_BASLIK)) > $null
$x.Item(1).AppendChild($t.CreateTextNode($env:MUHASEBE_METIN)) > $null
$id = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($id).Show([Windows.UI.Notifications.ToastNotification]::new($t))
"""


def windows_bildirimi(baslik: str, metin: str) -> None:
    """Windows'un sağ alttaki bildirimi (yalnızca Windows'ta; olmazsa sessizce geçer)."""
    if os.name != "nt":
        return
    import subprocess
    try:
        subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", _TOAST], timeout=30,
                       env={**os.environ, "MUHASEBE_BASLIK": baslik, "MUHASEBE_METIN": metin},
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), capture_output=True)
    except Exception as e:  # noqa: BLE001
        print("Windows bildirimi verilemedi:", e)


def _vade_bildirimi():
    """Vadesi gelen/geçen çek varsa, ödendi/tahsil/ciro işaretlenene kadar saatte bir Windows bildirimi.
    Program penceresi açıksa bildirimi o verir (çift bildirim olmasın)."""
    time.sleep(120)
    while True:
        try:
            if time.time() - cekler.SON_TARAYICI_KONTROLU[0] > 3900:
                db = SessionLocal()
                try:
                    liste = cekler.vadesi_gelen_cekler(db)
                finally:
                    db.close()
                if liste:
                    alinan = sum(1 for c in liste if c.yon == "alinan")
                    verilen = len(liste) - alinan
                    parca = [f"{verilen} verilen çek ödenecek" if verilen else "", f"{alinan} alınan çek tahsil edilecek" if alinan else ""]
                    windows_bildirimi("Vadesi gelen çek var", ", ".join(p for p in parca if p) + ". Ödenince programda işaretleyin.")
        except Exception as e:  # noqa: BLE001
            print("Vade bildirimi kontrol edilemedi:", e)
        time.sleep(3600)


@app.on_event("startup")
def baslangic():
    threading.Thread(target=_gunluk_yedek, daemon=True).start()
    threading.Thread(target=_vade_bildirimi, daemon=True).start()
    threading.Thread(target=onarim.baslangicta_onar, daemon=True).start()
    from . import guncelleme
    guncelleme.acildi()  # yeni sürüm sorunsuz açıldı: baslat.bat eski sürüme dönmez
    threading.Thread(target=_gunluk_guncelleme_denetimi, daemon=True).start()
