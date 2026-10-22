"""Veritabanı bağlantısı.

Varsayılan olarak yerel SQLite dosyası kullanılır; dosya Belgeler\\Muhasebe Verileri klasöründedir
(MUHASEBE_VERI ile değiştirilebilir). Sunucuda PostgreSQL için
DATABASE_URL ortam değişkeni verilir, ör.
postgresql+psycopg://kullanici:sifre@localhost/muhasebe
"""
import os
import shutil
import sqlite3
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

PAKET_VERI = Path(__file__).resolve().parents[1] / "veri"  # eski sürümler veriyi paket klasöründe tutuyordu


def _varsayilan_klasor() -> Path:
    """Veri, programın klasöründen bağımsız sabit bir yerde durur; yeni paket başka klasöre açılsa da kaybolmaz."""
    belgeler = Path.home() / "Documents"
    return (belgeler if belgeler.is_dir() else Path.home()) / "Muhasebe Verileri"


def _kayit_sayisi(db: Path) -> int:
    try:
        with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as b:
            return sum(b.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                       for t in ("kullanicilar", "faturalar", "hareketler", "cariler", "cekler"))
    except sqlite3.Error:
        return -1


def eski_veritabanlari(aranacak: list[Path] | None = None) -> list[Path]:
    """Eski paket klasörlerinde (Masaüstü, İndirilenler, Belgeler altında) kalmış veritabanları."""
    if aranacak is None:
        aranacak = [Path.home() / d for d in ("Desktop", "Downloads", "Documents", "OneDrive/Desktop", "OneDrive/Masaüstü")]
    bulunan = {PAKET_VERI / "muhasebe.db"}
    for kok in aranacak:
        if kok.is_dir():
            for derinlik in ("*", "*/*", "*/*/*"):
                bulunan.update(kok.glob(f"{derinlik}/backend/veri/muhasebe.db"))
    return [d for d in bulunan if d.is_file()]


def eski_veriyi_tasi(hedef: Path, adaylar: list[Path]) -> Path | None:
    """Hedefte veritabanı yoksa en çok kayıt içeren eski veritabanını (ve fatura belgelerini) hedefe kopyalar."""
    if (hedef / "muhasebe.db").exists():
        return None
    adaylar = sorted((a for a in adaylar if _kayit_sayisi(a) > 0), key=lambda a: (_kayit_sayisi(a), a.stat().st_mtime))
    if not adaylar:
        return None
    kaynak = adaylar[-1]
    hedef.mkdir(parents=True, exist_ok=True)
    shutil.copy2(kaynak, hedef / "muhasebe.db")
    if (kaynak.parent / "belgeler").is_dir():
        shutil.copytree(kaynak.parent / "belgeler", hedef / "belgeler", dirs_exist_ok=True)
    return kaynak


if os.environ.get("MUHASEBE_VERI"):
    VERI_KLASORU = Path(os.environ["MUHASEBE_VERI"])
else:
    VERI_KLASORU = _varsayilan_klasor()
    if not os.environ.get("DATABASE_URL"):
        TASINAN = eski_veriyi_tasi(VERI_KLASORU, eski_veritabanlari())
VERI_KLASORU.mkdir(parents=True, exist_ok=True)

DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite:///{VERI_KLASORU / 'muhasebe.db'}")

engine = create_engine(
    DATABASE_URL,
    # Açılış onarımı ya da yedek sürerken başka bir kayıt "database is locked" hatası vermesin, sırasını beklesin.
    connect_args={"check_same_thread": False, "timeout": 30} if DATABASE_URL.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False)

if DATABASE_URL.startswith("sqlite"):
    from sqlalchemy import event

    @event.listens_for(engine, "connect")
    def _sqlite_ayarlari(baglanti, _kayit):
        # WAL: bir kayıt yazılırken öteki ekranlar okumaya devam eder; toplu yüklemede kilitlenme olmaz.
        imlec = baglanti.cursor()
        imlec.execute("PRAGMA journal_mode=WAL")
        imlec.execute("PRAGMA synchronous=NORMAL")
        imlec.close()


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Eski veritabanlarına sonradan eklenen sütunlar (tablo, sütun, tanım).
EKLENEN_SUTUNLAR = [
    ("faturalar", "iptal_nedeni", "TEXT"),
    ("faturalar", "dosya_ozeti", "VARCHAR(64)"),
    ("hareketler", "iptal_nedeni", "TEXT"),
    ("faturalar", "diger_vergiler", "NUMERIC(14, 2) DEFAULT 0 NOT NULL"),
    ("faturalar", "yuvarlama", "NUMERIC(14, 2) DEFAULT 0 NOT NULL"),
    ("fatura_kalemleri", "santiye_id", "INTEGER REFERENCES santiyeler(id)"),
    ("hareketler", "bagli_hareket_id", "INTEGER REFERENCES hareketler(id)"),
    ("banka_hesaplari", "ekstre_bakiye", "NUMERIC(18, 2)"),
    ("banka_hesaplari", "ekstre_tarihi", "DATE"),
    ("sirketler", "vergi_dairesi", "VARCHAR(100)"),
    ("sirketler", "adres", "TEXT"),
    ("sirketler", "telefon", "VARCHAR(50)"),
    ("sirketler", "eposta", "VARCHAR(255)"),
    ("sirketler", "iban", "VARCHAR(34)"),
    ("sirketler", "fatura_seri", "VARCHAR(3)"),
    ("faturalar", "xml_dosya", "VARCHAR(255)"),
    ("fatura_kalemleri", "tevkifat_orani", "NUMERIC(4, 2) DEFAULT 0 NOT NULL"),
    ("fatura_kalemleri", "tevkifat_kodu", "VARCHAR(10)"),
    ("fatura_kalemleri", "kdv_tutari", "NUMERIC(14, 2)"),
    ("fatura_kalemleri", "iskonto_orani", "NUMERIC(6, 2) DEFAULT 0 NOT NULL"),
    ("fatura_kalemleri", "iskonto_tutari", "NUMERIC(14, 2) DEFAULT 0 NOT NULL"),
    ("cariler", "ad_otomatik", "BOOLEAN DEFAULT 0 NOT NULL"),
    ("banka_hesaplari", "acilis_ekstreden", "BOOLEAN DEFAULT 0 NOT NULL"),
    ("faturalar", "kur", "NUMERIC(18, 6)"),
    ("faturalar", "fatura_tipi", "VARCHAR(20)"),
    ("banka_hesaplari", "tur", "VARCHAR(12) DEFAULT 'banka' NOT NULL"),
    ("banka_hesaplari", "kart_no", "VARCHAR(25)"),
    ("banka_hesaplari", "son_odeme_tarihi", "DATE"),
    ("banka_hesaplari", "asgari_odeme", "NUMERIC(18, 2)"),
    ("cariler", "vade_gun", "INTEGER"),
    ("cekler", "islem_tarihi", "DATE"),
    ("cekler", "ozel_kod", "VARCHAR(50)"),
    ("cekler", "kesideci_vkn", "VARCHAR(11)"),
    ("cekler", "lehtar", "VARCHAR(200)"),
    ("faturalar", "stopaj", "NUMERIC(14, 2) DEFAULT 0 NOT NULL"),
    ("fatura_kalemleri", "stopaj_orani", "NUMERIC(5, 2) DEFAULT 0 NOT NULL"),
    ("fatura_kalemleri", "depo_id", "INTEGER REFERENCES depolar(id)"),
]


def _sutunlari_ekle(baglanti, motor) -> None:
    """Eski veritabanına sonradan eklenen sütunlar (var olan atlanır)."""
    from sqlalchemy import inspect, text
    denetci = inspect(baglanti)
    for tablo, sutun, tanim in EKLENEN_SUTUNLAR:
        if tablo in denetci.get_table_names() and sutun not in {c["name"] for c in denetci.get_columns(tablo)}:
            baglanti.execute(text(f"ALTER TABLE {tablo} ADD COLUMN {sutun} {tanim}"))
            if (tablo, sutun) == ("faturalar", "fatura_tipi") and motor.dialect.name == "sqlite" \
                    and "ai_okuma" in {c["name"] for c in denetci.get_columns(tablo)}:
                # Eski kayıtlarda e-Fatura tipi okumada saklanmıştı (İADE faturaları raporlarda ters işlensin)
                baglanti.execute(text("UPDATE faturalar SET fatura_tipi = upper(json_extract(ai_okuma, '$.fatura_tipi')) "
                                      "WHERE json_valid(ai_okuma) AND json_extract(ai_okuma, '$.fatura_tipi') IS NOT NULL"))


# Şema sürümleri: her adım bir kez, sırayla çalışır; önce veritabanının yedeği alınır. Yeni değişiklik listenin
# sonuna yeni numarayla eklenir (eski adımlar değiştirilmez).
SEMA_ADIMLARI = [
    (1, "Eski veritabanına eksik sütunlar eklenir", _sutunlari_ekle),
    (2, "Faturalara stopaj sütunları eklenir", _sutunlari_ekle),
    (3, "Fatura kalemlerine depo sütunu eklenir", _sutunlari_ekle),
]
SEMA_YEDEK_KLASORU = VERI_KLASORU / "guncelleme-yedekleri"


def _sema_yedegi(motor, surum: int) -> Path | None:
    """Güncelleme adımından önce SQLite veritabanının tam kopyası (WAL içindekiler dahil); son 5 kopya tutulur."""
    if motor.dialect.name != "sqlite" or not motor.url.database:
        return None
    from datetime import datetime
    SEMA_YEDEK_KLASORU.mkdir(parents=True, exist_ok=True)
    hedef = SEMA_YEDEK_KLASORU / f"sema-{surum}-oncesi-{datetime.now():%Y%m%d-%H%M%S}.db"
    with sqlite3.connect(motor.url.database) as kaynak, sqlite3.connect(hedef) as kopya:
        kaynak.backup(kopya)
    for eski in sorted(SEMA_YEDEK_KLASORU.glob("sema-*.db"), key=lambda p: p.stat().st_mtime)[:-5]:
        eski.unlink(missing_ok=True)
    return hedef


def sema_surumu(motor) -> int:
    from sqlalchemy import text
    with motor.begin() as baglanti:
        baglanti.execute(text("CREATE TABLE IF NOT EXISTS sema_surumu (surum INTEGER NOT NULL)"))
        return baglanti.execute(text("SELECT max(surum) FROM sema_surumu")).scalar() or 0


def db_guncelle(motor) -> None:
    """Veritabanını programın şema sürümüne getirir (veri kaybı olmadan): bekleyen adımlar sırayla, her biri
    öncesinde yedek alınarak ve kendi işleminde (yarıda kalırsa geri alınır) çalışır."""
    from sqlalchemy import inspect, text
    eski = sema_surumu(motor)
    bekleyen = [a for a in SEMA_ADIMLARI if a[0] > eski]
    if not bekleyen:
        return
    with motor.connect() as baglanti:
        dolu = "sirketler" in inspect(baglanti).get_table_names() and \
            baglanti.execute(text("SELECT 1 FROM sirketler LIMIT 1")).first() is not None
    for no, aciklama, adim in bekleyen:
        if dolu:
            try:
                _sema_yedegi(motor, no)
            except Exception as e:  # noqa: BLE001
                raise RuntimeError(f"Veritabanı güncellenmeden önce yedek alınamadı ({e}). Diskte yer açıp programı "
                                   "yeniden açın; verileriniz değiştirilmedi.") from e
        with motor.begin() as baglanti:
            adim(baglanti, motor)
            baglanti.execute(text("INSERT INTO sema_surumu (surum) VALUES (:s)"), {"s": no})
        print(f"Veritabanı güncellendi: {no}. {aciklama}")
