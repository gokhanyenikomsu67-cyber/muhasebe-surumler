"""Programın kendi kendini güncellemesi.

Kaynak (biri yeter):
- GitHub: herkese açık sürüm deposu (muhasebe-surumler). İçinde yalnız program paketi ve sürüm adını yazan
  surum.txt vardır; ana kod deposu gizli kalır, token gerekmez.
- Klasör: .env'de MUHASEBE_GUNCELLEME_KLASORU (ör. Google Drive'ın eşitlediği klasör) verilirse oradaki en yeni
  Muhasebe paketi (.zip) kullanılır; internete hiç gidilmez.

Akış: denetle() yeni sürüm var mı bakar (günde en çok bir kez kendiliğinden; internet yoksa sessizce geçer).
hazirla() paketi indirir, doğrular ve "guncelleme-bekliyor.txt" işaretini koyar; program baslat.bat ile yeniden açılır.
baslat.bat bu dosyayı "uygula" ile çalıştırır: değişen dosyaların eskisi "eski-surum" klasörüne alınır, yenileri
yazılır. Veri klasörüne (Belgeler\\Muhasebe Verileri), .env'e ve program ortamına (.venv) dokunulmaz. Yeni sürüm
açılamazsa baslat.bat "geri" ile eski sürüm geri konur.
"""
import errno
import json
import os
import re
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from datetime import date
from pathlib import Path

PROGRAM = Path(__file__).resolve().parents[2]  # baslat.bat'ın olduğu klasör
DEPO = os.environ.get("MUHASEBE_GUNCELLEME_DEPO", "gokhanyenikomsu67-cyber/muhasebe-surumler")
DAL = os.environ.get("MUHASEBE_GUNCELLEME_DALI", "main")
BEKLIYOR = PROGRAM / "guncelleme-bekliyor.txt"   # içinde hazırlanan paketin yolu
DENENIYOR = PROGRAM / "guncelleme-deneniyor.txt"  # yeni sürüm ilk kez açılıyor; açılınca silinir
SONUC = PROGRAM / "guncelleme-sonucu.txt"
ESKI = PROGRAM / "eski-surum"
GEREKLI_YER = 100 * 1024 * 1024  # güncelleme için diskte istenen en az boş yer (paket, eski dosyalar, yedek)
# Güncellemede hiç dokunulmayan yerler (program klasörüne göre)
KORUNAN = (".env", "backend/.venv", "backend/veri", "eski-surum", "baslat-gunlugu.txt", "guncelleme-bekliyor.txt",
           "guncelleme-deneniyor.txt", "guncelleme-sonucu.txt", "yeniden-baslatiliyor.txt", "python312-son-deneme.txt")
ZAMAN_ASIMI = 8


class GuncellemeHatasi(Exception):
    pass


def _surum() -> str:
    from .surum import SURUM
    return SURUM


def _durum_dosyasi() -> Path:
    from .db import VERI_KLASORU
    return VERI_KLASORU / "guncelleme.json"


def durum() -> dict:
    try:
        return json.loads(_durum_dosyasi().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _durum_yaz(**alanlar) -> None:
    d = {**durum(), **alanlar}
    try:
        _durum_dosyasi().write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        pass


def _indir(url: str, hedef: Path | None = None) -> bytes | None:
    istek = urllib.request.Request(url, headers={"User-Agent": "muhasebe-guncelleme"})
    with urllib.request.urlopen(istek, timeout=ZAMAN_ASIMI if hedef is None else 120) as y:
        if hedef is None:
            return y.read()
        with open(hedef, "wb") as f:
            shutil.copyfileobj(y, f)
    return None


def paket_surumu(zip_yolu: Path) -> str | None:
    """Paketin sürümü (backend/app/surum.py içindeki tarih ve kayıt kodu)."""
    try:
        with zipfile.ZipFile(zip_yolu) as z:
            ad = next((n for n in z.namelist() if n.endswith("backend/app/surum.py")), None)
            if ad is None:
                return None
            m = re.search(r'_HAM = "(\d{4}-\d{2}-\d{2} [0-9a-f]{7,})"', z.read(ad).decode("utf-8", "replace"))
    except (OSError, zipfile.BadZipFile):
        return None
    return m.group(1) if m else None


def _klasordeki_en_yeni() -> tuple[str, Path] | None:
    klasor = os.environ.get("MUHASEBE_GUNCELLEME_KLASORU", "").strip()
    if not klasor or not Path(klasor).is_dir():
        return None
    adaylar = [(s, p) for p in Path(klasor).glob("*.zip") if (s := paket_surumu(p))]
    return max(adaylar, default=None, key=lambda x: (x[0][:10], x[1].stat().st_mtime))


def denetle(zorla: bool = False) -> dict:
    """Yeni sürüm var mı: {var, yeni, simdiki, kaynak, hata}. Kendiliğinden yapılan denetim günde en çok bir kez."""
    simdiki = _surum()
    d = durum()
    onceki = d.get("son_denetim") or {}
    # Günün denetimi yalnız aynı sürüm için geçerli: program bugün güncellendiyse eski "yeni sürüm var" sonucu kullanılmaz
    if not zorla and d.get("denetim_gunu") == date.today().isoformat() and onceki.get("simdiki") == simdiki:
        return onceki
    sonuc = {"var": False, "simdiki": simdiki, "yeni": None, "kaynak": None, "hata": None}
    if simdiki == "geliştirme":
        sonuc["hata"] = "Geliştirme sürümü güncellenmez."
    elif (klasorde := _klasordeki_en_yeni()) is not None:
        sonuc.update(kaynak="klasor", yeni=klasorde[0], var=klasorde[0][:10] >= simdiki[:10] and klasorde[0] != simdiki)
    else:
        try:
            yeni = _indir(f"https://raw.githubusercontent.com/{DEPO}/{DAL}/surum.txt").decode("utf-8").strip()
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2} [0-9a-f]{7,}", yeni):
                raise ValueError(yeni)
            sonuc.update(kaynak="github", yeni=yeni, var=yeni[:10] >= simdiki[:10] and yeni != simdiki)
        except Exception as e:  # noqa: BLE001  internet yok ya da sürüm deposu yok: sessizce geçilir
            sonuc["hata"] = ("Güncelleme bilgisi okunamadı." if isinstance(e, ValueError)
                             else "Güncelleme kaynağına ulaşılamadı (internet yok ya da sürüm deposu henüz açılmadı).")
    _durum_yaz(denetim_gunu=date.today().isoformat(), son_denetim=sonuc)
    return sonuc


def _paketi_dogrula(zip_yolu: Path) -> str:
    """Paket sağlam mı ve bu programın paketi mi; içindeki program klasörünün adı (ör. 'Muhasebe/')."""
    try:
        with zipfile.ZipFile(zip_yolu) as z:
            if z.testzip() is not None:
                raise GuncellemeHatasi("İndirilen paket bozuk.")
            adlar = z.namelist()
    except zipfile.BadZipFile as e:
        raise GuncellemeHatasi("İndirilen dosya program paketi değil.") from e
    kok = next((n[: -len("baslat.bat")] for n in adlar if n.endswith("baslat.bat") and n.count("/") <= 1), None)
    if kok is None or not all(f"{kok}{g}" in adlar for g in ("backend/app/main.py", "web/app.js", "backend/requirements.txt")):
        raise GuncellemeHatasi("İndirilen dosya program paketi değil.")
    return kok


def hazirla() -> dict:
    """Yeni sürümü indirir/kopyalar, doğrular, önce yedek alır ve uygulanmak üzere işaretler."""
    from . import yedek
    from .db import VERI_KLASORU
    d = denetle(zorla=True)
    if not d["var"]:
        raise GuncellemeHatasi(d.get("hata") or "Program güncel.")
    klasor = VERI_KLASORU / "guncelleme"
    klasor.mkdir(exist_ok=True)
    hedef = klasor / "yeni-surum.zip"
    # Paket (~5 MB), açılırken eski dosyaların kopyası ve veri yedeği için yer: yoksa indirmeden önce söylenir
    for yer in {VERI_KLASORU, PROGRAM}:
        try:
            yedek.yer_kontrolu(yer, GEREKLI_YER)
        except OSError as e:
            raise GuncellemeHatasi(str(e)) from e
    try:
        if d["kaynak"] == "klasor":
            shutil.copy2(_klasordeki_en_yeni()[1], hedef)
        else:
            try:
                _indir(f"https://codeload.github.com/{DEPO}/zip/refs/heads/{DAL}", hedef)
            except OSError as e:
                if getattr(e, "errno", None) == errno.ENOSPC:
                    raise
                raise GuncellemeHatasi("Yeni sürüm indirilemedi; internet bağlantısını kontrol edin.") from e
            except Exception as e:  # noqa: BLE001
                raise GuncellemeHatasi("Yeni sürüm indirilemedi; internet bağlantısını kontrol edin.") from e
        _paketi_dogrula(hedef)
        yedek.yedek_al()  # güncellemeden önce veri yedeği; alınamazsa güncelleme yapılmaz
    except OSError as e:
        hedef.unlink(missing_ok=True)
        if getattr(e, "errno", None) == errno.ENOSPC:
            raise GuncellemeHatasi(f"Diskte yer kalmadı ({yedek.boyut_yazisi(yedek.bos_yer(VERI_KLASORU))} boş). Geri Dönüşüm "
                                   "Kutusu'nu boşaltın, İndirilenler klasörünü temizleyin, sonra Tekrar dene.") from e
        raise GuncellemeHatasi(str(e)) from e
    except RuntimeError as e:  # yedek alınamadı
        hedef.unlink(missing_ok=True)
        raise GuncellemeHatasi(f"Güncellemeden önce yedek alınamadı: {e}") from e
    BEKLIYOR.write_text(str(hedef), encoding="utf-8")
    return {"yeni": d["yeni"]}


# --- baslat.bat'tan çalıştırılan kısım (program kapalıyken) --------------------------------------------------------

def _korunan_mu(goreli: str) -> bool:
    return any(goreli == k or goreli.startswith(k + "/") for k in KORUNAN) or "__pycache__" in goreli


def uygula() -> str:
    """Bekleyen paketi program klasörüne yazar; değişen dosyaların eskisi eski-surum'a alınır. Hata olursa geri alınır."""
    zip_yolu = Path(BEKLIYOR.read_text(encoding="utf-8").strip())
    BEKLIYOR.unlink(missing_ok=True)
    kok = _paketi_dogrula(zip_yolu)
    shutil.rmtree(ESKI, ignore_errors=True)
    ESKI.mkdir()
    yazilan: list[Path] = []
    yeni_acilan: list[Path] = []
    try:
        with zipfile.ZipFile(zip_yolu) as z, tempfile.TemporaryDirectory() as gecici:
            for bilgi in z.infolist():
                if bilgi.is_dir() or not bilgi.filename.startswith(kok):
                    continue
                goreli = bilgi.filename[len(kok):]
                if not goreli or ".." in Path(goreli).parts or _korunan_mu(goreli):
                    continue
                hedef = PROGRAM / goreli
                veri = z.read(bilgi)
                if hedef.exists():
                    if hedef.read_bytes() == veri:
                        continue
                    (ESKI / goreli).parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(hedef, ESKI / goreli)
                else:
                    yeni_acilan.append(hedef)
                gecici_dosya = Path(gecici) / "d"
                gecici_dosya.write_bytes(veri)
                hedef.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(gecici_dosya, hedef)
                yazilan.append(hedef)
    except Exception:
        geri_al(yeni_acilan)
        raise
    (ESKI / ".yeni-dosyalar.txt").write_text("\n".join(str(p.relative_to(PROGRAM)) for p in yeni_acilan), encoding="utf-8")
    DENENIYOR.write_text(str(paket_surumu(zip_yolu)), encoding="utf-8")
    return f"{len(yazilan)} dosya güncellendi."


def geri_al(yeni_acilan: list[Path] | None = None) -> str:
    """eski-surum'daki dosyaları yerine koyar, güncellemenin eklediği dosyaları siler."""
    if yeni_acilan is None:
        liste = ESKI / ".yeni-dosyalar.txt"
        yeni_acilan = [PROGRAM / s for s in liste.read_text(encoding="utf-8").splitlines() if s] if liste.exists() else []
    n = 0
    for eski in ESKI.rglob("*") if ESKI.exists() else []:
        if eski.is_file() and eski.name != ".yeni-dosyalar.txt":
            hedef = PROGRAM / eski.relative_to(ESKI)
            hedef.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(eski, hedef)
            n += 1
    for p in yeni_acilan:
        p.unlink(missing_ok=True)
    DENENIYOR.unlink(missing_ok=True)
    return f"Eski sürüm geri kondu ({n} dosya)."


def acildi() -> None:
    """Program açıldı: yeni sürüm sorunsuz başladı, geri dönüş işareti kaldırılır."""
    if DENENIYOR.exists():
        _durum_yaz(son_guncelleme={"surum": _surum(), "tarih": date.today().isoformat()})
        DENENIYOR.unlink(missing_ok=True)
    # Uygulanmış paket yer kaplamasın (bekleyen güncelleme yoksa)
    if not BEKLIYOR.exists():
        from .db import VERI_KLASORU
        (VERI_KLASORU / "guncelleme" / "yeni-surum.zip").unlink(missing_ok=True)


if __name__ == "__main__":
    islem = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        mesaj = uygula() if islem == "uygula" else geri_al() if islem == "geri" else "Bilinmeyen işlem."
        tamam = True
    except Exception as e:  # noqa: BLE001
        mesaj, tamam = f"Güncelleme yapılamadı, eski sürüm kullanılıyor: {e}", False
    SONUC.write_text(mesaj, encoding="utf-8")
    print(mesaj)
    sys.exit(0 if tamam else 1)
