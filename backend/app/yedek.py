"""Yedekleme: veritabanı ve belgeler tek .zip dosyasına alınır ve her hedef
klasöre kopyalanır.

Hedefler MUHASEBE_YEDEK_KLASORLERI ortam değişkeninde ';' ile ayrılarak verilir.
Örnek (Windows):
  C:\\MuhasebeYedek;G:\\Drive'ım\\MuhasebeYedek
İkinci klasör Google Drive masaüstü uygulamasının eşitlediği klasör olduğunda
yedek kendiliğinden Google Drive'a da gider.
"""
import hashlib
import json
import os
import re
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from .db import DATABASE_URL, VERI_KLASORU

SAKLAMA_ADEDI = max(1, int(os.environ.get("MUHASEBE_YEDEK_ADET", "3")))  # en yeni bu kadar yedek kalır, eskiler silinir
YENI_BELGE_GUNU = 7  # kayda bağlanmamış belge (ör. okunup kaydedilmemiş çek) bu kadar gün yedeğe girer
_ONEK = "muhasebe-yedek-"
# Belgeler (PDF, resim) her yedeğe yeniden konmaz: yedek klasöründeki bu alt klasörde bir kez durur (adları içerik
# özetidir), yedek ZIP'inde yalnız veritabanı ve belge listesi (belgeler.txt) olur. Eski yedekler belgeleri içinde taşır.
BELGE_KLASORU = "yedek-belgeler"
_LISTE = "belgeler.txt"
GUVENLIK_PAYI = 50 * 1024 * 1024  # yedekten sonra diskte en az bu kadar boş yer kalsın
DURUM_DOSYASI = VERI_KLASORU / "yedek-durumu.json"
DENEME_ARALIGI = 7 * 86400  # son yedek haftada bir geçici veritabanına açılıp denenir
SAYILAN_TABLOLAR = ("sirketler", "cariler", "faturalar", "hareketler", "cekler")


def _db_yolu() -> str:
    return DATABASE_URL.removeprefix("sqlite:///")


def _ozet(yol: Path) -> str:
    h = hashlib.sha256()
    with open(yol, "rb") as f:
        for parca in iter(lambda: f.read(1 << 20), b""):
            h.update(parca)
    return h.hexdigest()


def durum() -> dict:
    try:
        return json.loads(DURUM_DOSYASI.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _durum_yaz(**alanlar) -> None:
    d = durum()
    d.update(alanlar)
    try:
        DURUM_DOSYASI.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        pass


def _sayilar(baglanti) -> dict:
    sayilar = {}
    for t in SAYILAN_TABLOLAR:
        try:
            sayilar[t] = baglanti.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        except sqlite3.Error:
            pass
    return sayilar


def yedegi_dogrula(zip_yolu: Path, klasor: Path | None = None) -> dict:
    """Yedek geri yüklenebilir mi: ZIP sağlam, içindeki veritabanı açılıyor ve PRAGMA integrity_check 'ok'.
    Veritabanı geçici klasöre açılır (asıl veri hiç değişmez). Döner: ok, hata, kayıt sayıları."""
    try:
        with zipfile.ZipFile(zip_yolu) as z:
            if (bozuk := z.testzip()) is not None:
                return {"ok": False, "hata": f"Yedek dosyası bozuk ({bozuk})."}
            if "muhasebe.db" not in z.namelist():
                return {"ok": False, "hata": "Yedekte veritabanı yok."}
            hedef = Path(klasor or tempfile.mkdtemp())
            z.extract("muhasebe.db", hedef)
        baglanti = sqlite3.connect(hedef / "muhasebe.db")
        try:
            sonuc = baglanti.execute("PRAGMA integrity_check").fetchone()[0]
            sayilar = _sayilar(baglanti)
        finally:
            baglanti.close()
        if klasor is None:
            shutil.rmtree(hedef, ignore_errors=True)
        if sonuc != "ok":
            return {"ok": False, "hata": f"Yedekteki veritabanı bozuk: {sonuc}"}
        if "sirketler" not in sayilar:
            return {"ok": False, "hata": "Yedekteki veritabanı bu programa ait değil."}
        return {"ok": True, "sayilar": sayilar}
    except FileNotFoundError:
        return {"ok": False, "hata": "Yedek dosyası bulunamadı; silinmiş ya da taşınmış olabilir."}
    except (OSError, zipfile.BadZipFile, sqlite3.Error) as e:
        return {"ok": False, "hata": f"Yedek açılamadı: {e}"}


def hedef_klasorler() -> list[Path]:
    deger = os.environ.get("MUHASEBE_YEDEK_KLASORLERI")
    yollar = [Path(p.strip()) for p in deger.split(";") if p.strip()] if deger else [VERI_KLASORU / "yedekler"]
    for y in yollar:
        y.mkdir(parents=True, exist_ok=True)
    return yollar


def yedek_al(koru: Path | None = None) -> dict:
    """Yedek alır; eski yedekler silinir. koru: silinmeyecek yedek (geri dönülen yedek, yeni yedek yüzünden silinmesin)."""
    if not DATABASE_URL.startswith("sqlite"):
        raise RuntimeError("PostgreSQL yedeği pg_dump ile alınır; bu fonksiyon SQLite içindir.")
    zaman = datetime.now().strftime("%Y%m%d-%H%M%S")
    ad = f"{_ONEK}{zaman}.zip"
    n = 1
    while any((k / ad).exists() for k in hedef_klasorler()):  # aynı saniyede ikinci yedek öncekinin üstüne yazılmasın
        n += 1
        ad = f"{_ONEK}{zaman}-{n}.zip"
    with tempfile.TemporaryDirectory() as gecici:
        db_kopya = Path(gecici) / "muhasebe.db"
        # Çalışan veritabanının tutarlı kopyası
        kaynak = sqlite3.connect(_db_yolu())
        hedef = sqlite3.connect(db_kopya)
        kaynak.backup(hedef)
        canli = _sayilar(kaynak)
        kullanilan = _kullanilan_belgeler(hedef)
        hedef.close()
        kaynak.close()

        zip_yolu = Path(gecici) / ad
        # Yalnız kayıtlara bağlı belgeler (ve son günlerde yüklenenler) yedeklenir: okunup kaydedilmeyen ya da silinen
        # kayıtların dosyaları yedeği büyütmesin
        belgeler = VERI_KLASORU / "belgeler"
        yeni_sinir = datetime.now().timestamp() - YENI_BELGE_GUNU * 86400
        secilen = sorted((d for d in belgeler.iterdir() if d.is_file() and not d.name.startswith(".")
                          and (d.name in kullanilan or d.stat().st_mtime >= yeni_sinir)), key=lambda d: d.name) \
            if belgeler.exists() else []
        with zipfile.ZipFile(zip_yolu, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(db_kopya, "muhasebe.db")
            z.writestr(_LISTE, "\n".join(d.name for d in secilen))

        # Yedek yazılmadan önce denenir: açılmayan ya da kayıt sayısı tutmayan yedek "alındı" sayılmaz
        dogrulama = yedegi_dogrula(zip_yolu)
        if dogrulama["ok"] and dogrulama["sayilar"] != canli:
            dogrulama = {"ok": False, "hata": "Yedekteki kayıt sayıları veritabanıyla tutmuyor."}
        zaman_s = datetime.now().isoformat(timespec="seconds")
        if not dogrulama["ok"]:
            _durum_yaz(son_yedek={"zaman": zaman_s, "dosya": ad, "ok": False, "hata": dogrulama["hata"]})
            raise RuntimeError(dogrulama["hata"])
        ozet = _ozet(zip_yolu)
        sonuc = []
        for klasor in hedef_klasorler():
            try:
                yer_kontrolu(klasor, zip_yolu.stat().st_size + _eksik_belge_boyutu(klasor, secilen))
                _belgeleri_kopyala(klasor, secilen)
                shutil.copy2(zip_yolu, klasor / ad)
                # Kopya (ör. Google Drive klasörü) birebir aynı mı
                if _ozet(klasor / ad) != ozet:
                    raise OSError("kopya kaynakla aynı değil")
                eskileri_sil(klasor, koru)
                sonuc.append({"klasor": str(klasor), "ok": True})
            except OSError as e:
                sonuc.append({"klasor": str(klasor), "ok": False, "hata": str(e)})
    hatali = [x for x in sonuc if not x["ok"]]
    if hatali and len(hatali) == len(sonuc):
        _durum_yaz(son_yedek={"zaman": zaman_s, "dosya": ad, "ok": False, "hata": hatali[0]["hata"]})
        raise RuntimeError(hatali[0]["hata"])
    _durum_yaz(son_yedek={"zaman": zaman_s, "dosya": ad, "ok": not hatali or len(hatali) < len(sonuc),
                          "hata": "; ".join(f"{x['klasor']}: {x['hata']}" for x in hatali) or None,
                          "kayit": sum(dogrulama["sayilar"].get(t, 0) for t in ("faturalar", "hareketler", "cekler"))})
    return {"dosya": ad, "hedefler": sonuc}


def bos_yer(klasor: Path) -> int:
    k = Path(klasor)
    while not k.exists() and k != k.parent:
        k = k.parent
    return shutil.disk_usage(k).free


def boyut_yazisi(bayt: float) -> str:
    return f"{bayt / 1024 ** 3:.1f} GB".replace(".", ",") if bayt >= 1024 ** 3 else f"{bayt / 1024 ** 2:.0f} MB"


def yer_kontrolu(klasor: Path, gerekli: int) -> None:
    """Yazmadan önce: diskte gereken yer + güvenlik payı yoksa anlaşılır Türkçe hata (yarım dosya kalmasın)."""
    bos = bos_yer(klasor)
    if bos < gerekli + GUVENLIK_PAYI:
        raise OSError(f"Diskte yer yok: {boyut_yazisi(bos)} boş, en az {boyut_yazisi(gerekli + GUVENLIK_PAYI)} gerekli. "
                      "Geri Dönüşüm Kutusu'nu boşaltın, İndirilenler klasöründeki gereksiz dosyaları silin ya da "
                      "Araçlar > Yedekler'den eski yedekleri silin.")


def _eksik_belge_boyutu(klasor: Path, secilen: list[Path]) -> int:
    hedef = klasor / BELGE_KLASORU
    return sum(d.stat().st_size for d in secilen if not ((hedef / d.name).is_file() and (hedef / d.name).stat().st_size == d.stat().st_size))


def _belgeleri_kopyala(klasor: Path, secilen: list[Path]) -> None:
    """Yedek klasörünün belge deposunda olmayan belgeler kopyalanır (adı içerik özeti olduğu için bir kez yeter)."""
    hedef = klasor / BELGE_KLASORU
    hedef.mkdir(parents=True, exist_ok=True)
    for d in secilen:
        h = hedef / d.name
        if not (h.is_file() and h.stat().st_size == d.stat().st_size):
            shutil.copy2(d, h)
            if h.stat().st_size != d.stat().st_size:
                raise OSError(f"{d.name} belgesi yedeğe tam kopyalanamadı")


def _belge_listesi(zip_yolu: Path) -> set[str]:
    try:
        with zipfile.ZipFile(zip_yolu) as z:
            return set(z.read(_LISTE).decode("utf-8").split()) if _LISTE in z.namelist() else set()
    except (OSError, zipfile.BadZipFile, KeyError):
        return set()


def _belge_deposunu_temizle(klasor: Path) -> None:
    """Hiçbir yedeğin listesinde olmayan belgeler yedek klasöründen silinir."""
    depo = klasor / BELGE_KLASORU
    if not depo.is_dir():
        return
    gerekli = set().union(*(_belge_listesi(y) for y in klasor.glob(f"{_ONEK}*.zip")))
    for d in depo.iterdir():
        if d.is_file() and d.name not in gerekli:
            d.unlink(missing_ok=True)


def _kullanilan_belgeler(baglanti) -> set[str]:
    adlar = set()
    for sorgu in ("SELECT kaynak_dosya FROM faturalar", "SELECT xml_dosya FROM faturalar", "SELECT kaynak_dosya FROM cekler"):
        try:
            adlar |= {r[0] for r in baglanti.execute(sorgu) if r[0]}
        except sqlite3.Error:
            pass
    return adlar


def eskileri_sil(klasor: Path, koru: Path | None = None):
    """En yeni SAKLAMA_ADEDI (3) yedek kalır, eskiler silinir; artık hiçbir yedeğin kullanmadığı belgeler de silinir.
    koru: o an geri dönülen yedek silinmez (bir sonraki yedekte sırası gelince silinir)."""
    tumu = sorted(klasor.glob(f"{_ONEK}*.zip"))  # ad tarih sırasıdır: muhasebe-yedek-YYYYMMDD-SSDDss.zip
    for d in tumu[:-SAKLAMA_ADEDI]:
        if koru is None or d.name != koru.name:
            d.unlink(missing_ok=True)
    _belge_deposunu_temizle(klasor)


def yedekleri_sil(secilenler: list[tuple[str, str]], diger_kopyalar: bool) -> dict:
    """Seçilen yedekleri siler. diger_kopyalar: aynı yedeğin öteki klasörlerdeki (ör. Google Drive) kopyaları da.
    En son yedek silinemez (geri dönülecek yedek hep kalsın)."""
    yollar = {yedek_bul(k, d) for k, d in secilenler}
    if diger_kopyalar:
        adlar = {y.name for y in yollar}
        yollar |= {k / a for k in hedef_klasorler() for a in adlar if (k / a).is_file()}
    tumu = [y for k in hedef_klasorler() for y in k.glob(f"{_ONEK}*.zip")]
    if tumu:
        en_son = max(y.name for y in tumu)
        if all(y in yollar for y in tumu if y.name == en_son):
            raise ValueError("En son yedek silinemez: geri dönülecek bir yedek hep kalmalı. Önce yeni yedek alın.")
    for y in yollar:
        y.unlink(missing_ok=True)
    for k in {y.parent for y in yollar}:
        _belge_deposunu_temizle(k)
    return {"silinen": len(yollar)}


def disk_durumu() -> dict:
    """Genel Durum için: veri klasörünün diskindeki boş yer ve programın kendi klasörlerinin kapladığı yer."""
    def boyut(p: Path) -> int:
        if p.is_file():
            return p.stat().st_size
        return sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) if p.is_dir() else 0
    db = Path(_db_yolu())
    parcalar = {"Veritabanı": sum(boyut(Path(str(db) + e)) for e in ("", "-wal", "-shm")), "Belgeler": boyut(VERI_KLASORU / "belgeler"),
                "Yedekler": sum(boyut(k) for k in hedef_klasorler()),
                "Güncelleme yedekleri": boyut(VERI_KLASORU / "guncelleme-yedekleri") + boyut(VERI_KLASORU / "guncelleme")}
    bos = bos_yer(VERI_KLASORU)
    return {"bos": bos, "bos_yazi": boyut_yazisi(bos), "az": bos < 1024 ** 3,
            "parcalar": [{"ad": a, "boyut": b, "yazi": boyut_yazisi(b)} for a, b in parcalar.items() if b]}


def yedekler() -> list[dict]:
    liste = []
    for klasor in hedef_klasorler():
        for d in sorted(klasor.glob(f"{_ONEK}*.zip"), reverse=True):
            liste.append({"klasor": str(klasor), "dosya": d.name, "boyut": d.stat().st_size,
                          "tarih": datetime.fromtimestamp(d.stat().st_mtime).isoformat(timespec="seconds")})
    return liste


def son_yedek_zamani() -> float | None:
    zamanlar = [d.stat().st_mtime for k in hedef_klasorler() for d in k.glob(f"{_ONEK}*.zip")]
    return max(zamanlar) if zamanlar else None


def yedek_bul(klasor: str, dosya: str) -> Path:
    """Listedeki bir yedeğin yolu; yalnız yedek klasörlerindeki yedek dosyaları kabul edilir."""
    if not re.fullmatch(re.escape(_ONEK) + r"\d{8}-\d{6}(?:-\d+)?\.zip", dosya or ""):
        raise ValueError("Geçersiz yedek adı.")
    for k in hedef_klasorler():
        if str(k) == klasor and (k / dosya).is_file():
            return k / dosya
    raise ValueError("Yedek bulunamadı.")


def geri_yukle(zip_yolu: Path) -> dict:
    """Seçilen yedeğe döner: önce bugünkü veri yedeklenir, sonra yedek geçici veritabanına açılıp doğrulanır;
    sağlamsa çalışan veritabanının yerine (SQLite yedekleme yöntemiyle, sayfa sayfa) yazılır, belgeler geri konur."""
    onceki = yedek_al(koru=zip_yolu)  # yanlış yedeğe dönülürse bu yedekle geri gelinir; seçilen yedek silinmez
    with tempfile.TemporaryDirectory() as gecici:
        dogrulama = yedegi_dogrula(zip_yolu, Path(gecici))
        if not dogrulama["ok"]:
            raise RuntimeError(dogrulama["hata"] + " Veriniz değiştirilmedi.")
        kaynak = sqlite3.connect(Path(gecici) / "muhasebe.db")
        hedef = sqlite3.connect(_db_yolu(), timeout=30)
        try:
            kaynak.backup(hedef)
        finally:
            hedef.close()
            kaynak.close()
        belgeler = VERI_KLASORU / "belgeler"
        belgeler.mkdir(exist_ok=True)
        with zipfile.ZipFile(zip_yolu) as z:
            for ad in z.namelist():  # eski biçim: belgeler yedeğin içinde
                if ad.startswith("belgeler/") and "/" not in ad[9:] and ad[9:] and not ad[9:].startswith("."):
                    (belgeler / ad[9:]).write_bytes(z.read(ad))
        depo = zip_yolu.parent / BELGE_KLASORU
        for ad in _belge_listesi(zip_yolu):
            if "/" not in ad and "\\" not in ad and not ad.startswith(".") and (depo / ad).is_file() and not (belgeler / ad).exists():
                shutil.copy2(depo / ad, belgeler / ad)
    _durum_yaz(son_geri_yukleme={"zaman": datetime.now().isoformat(timespec="seconds"), "dosya": zip_yolu.name,
                                 "onceki_yedek": onceki["dosya"]})
    return {"geri_yuklenen": zip_yolu.name, "onceki_yedek": onceki["dosya"], "sayilar": dogrulama["sayilar"]}


def son_yedegi_dene(zorla: bool = False) -> dict | None:
    """Haftada bir: en son yedek geçici veritabanına açılıp denenir (asıl veriye dokunulmaz); sonuç Genel Durum'da."""
    d = durum().get("son_deneme") or {}
    if not zorla and d.get("zaman") and datetime.now().timestamp() - datetime.fromisoformat(d["zaman"]).timestamp() < DENEME_ARALIGI:
        return None
    adaylar = sorted((y for k in hedef_klasorler() for y in k.glob(f"{_ONEK}*.zip")), key=lambda y: y.name, reverse=True)
    if not adaylar:
        return None
    sonuc = yedegi_dogrula(adaylar[0])
    kayit = {"zaman": datetime.now().isoformat(timespec="seconds"), "dosya": adaylar[0].name, "ok": sonuc["ok"],
             "hata": sonuc.get("hata")}
    _durum_yaz(son_deneme=kayit)
    return kayit
