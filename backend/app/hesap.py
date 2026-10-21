"""Cari ve banka bakiyesi hesapları.

Cari bakiye pozitifse cari bize borçludur, negatifse biz cariye borçluyuz.
"""
from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .models import HAREKET_TURLERI, BankaHesabi, Fatura, Hareket

MASRAF_TURLERI = ("masraf", "banka_masrafi")


def tl_kur(f: Fatura) -> float:
    """Faturanın tutarlarını TL'ye çeviren çarpan: dövizli faturada girilen kur, TL faturada 1."""
    return float(f.kur) if f.kur and (f.para_birimi or "TRY") not in ("TRY", "TL") else 1.0


def iade_mi(f: Fatura) -> bool:
    return (f.fatura_tipi or "").upper() == "IADE"


def satis_tarafi(f: Fatura) -> bool:
    """Fatura gelir (satış) tarafını mı etkiler? Satış faturası ve müşteriden gelen iade satış tarafıdır; alış faturası
    ve tedarikçiye kestiğimiz iade alış tarafıdır. İade faturası o tarafın tutarını azaltır (bkz. isaret)."""
    return (f.yon == "giden") != iade_mi(f)


def isaret(f: Fatura) -> int:
    return -1 if iade_mi(f) else 1


def fatura_vadesi(f: Fatura) -> date | None:
    """Faturada yazan vade; yoksa fatura tarihi + carinin varsayılan vade günü; o da yoksa fatura tarihi."""
    if f.vade:
        return f.vade
    if f.tarih and f.cari and f.cari.vade_gun:
        return f.tarih + timedelta(days=f.cari.vade_gun)
    return f.tarih


def cari_hareketleri(db: Session, sirket_id: int, cari_id: int | None = None) -> list[dict]:
    """Onaylı fatura ve para hareketlerinden cari ekstre satırları (tarih sırasız)."""
    fq = select(Fatura).where(Fatura.sirket_id == sirket_id, Fatura.durum == "onayli", Fatura.cari_id.is_not(None))
    hq = select(Hareket).where(Hareket.sirket_id == sirket_id, Hareket.durum == "onayli", Hareket.cari_id.is_not(None))
    if cari_id is not None:
        fq = fq.where(Fatura.cari_id == cari_id)
        hq = hq.where(Hareket.cari_id == cari_id)
    satirlar = []
    for f in db.scalars(fq):
        tutar = round(float(f.genel_toplam) * tl_kur(f), 2)  # dövizli fatura TL karşılığıyla
        satis = f.yon == "giden"
        ad = ("İade faturası (kestiğimiz)" if satis else "İade faturası (gelen)") if iade_mi(f) else \
            "Satış faturası" if satis else "Alış faturası"
        if tl_kur(f) != 1:
            ad += f" ({float(f.genel_toplam):,.2f} {f.para_birimi} x {float(f.kur):g})"
        satirlar.append({"cari_id": f.cari_id, "tarih": f.tarih, "belge": f.fatura_no,
                         "aciklama": ad,
                         "borc": tutar if satis else 0.0, "alacak": 0.0 if satis else tutar,
                         "fatura_id": f.id, "hareket_id": None, "sira": (0, f.id, 0)})
    for h in db.scalars(hq):
        tutar = float(h.tutar)
        giris = h.yon == "giris"  # cari bize ödedi -> carinin borcu azalır
        if not giris and h.tur in MASRAF_TURLERI:
            # Banka kesintisi gibi masraflar: cariye hem gider (alacak) hem ödeme (borç) olarak işlenir, bakiye sıfırlanır.
            satirlar.append({"cari_id": h.cari_id, "tarih": h.tarih, "belge": None,
                             "aciklama": "Gider: " + (h.aciklama or HAREKET_TURLERI.get(h.tur, h.tur)),
                             "borc": 0.0, "alacak": tutar, "fatura_id": None, "hareket_id": h.id, "sira": (1, h.id, 0)})
        satirlar.append({"cari_id": h.cari_id, "tarih": h.tarih, "belge": None,
                         "aciklama": HAREKET_TURLERI.get(h.tur, h.tur) + (f" - {h.aciklama}" if h.aciklama else ""),
                         "borc": 0.0 if giris else tutar, "alacak": tutar if giris else 0.0,
                         "fatura_id": None, "hareket_id": h.id, "sira": (1, h.id, 1)})
    return satirlar


def cari_bakiyeleri(db: Session, sirket_id: int) -> dict[int, dict]:
    toplam: dict[int, dict] = defaultdict(lambda: {"borc": 0.0, "alacak": 0.0})
    for s in cari_hareketleri(db, sirket_id):
        toplam[s["cari_id"]]["borc"] += s["borc"]
        toplam[s["cari_id"]]["alacak"] += s["alacak"]
    return toplam


def banka_bakiyeleri(db: Session, sirket_id: int, tarihe_kadar: bool = False) -> dict[int, float]:
    """Onaylı hareketlerle banka bakiyeleri. tarihe_kadar: her hesap için son ekstre tarihine kadarki bakiye."""
    hesaplar = list(db.scalars(select(BankaHesabi).where(BankaHesabi.sirket_id == sirket_id)))
    sinir = {b.id: b.ekstre_tarihi for b in hesaplar}
    bakiye = {b.id: float(b.acilis_bakiyesi or 0) for b in hesaplar}
    for h in db.scalars(select(Hareket).where(Hareket.sirket_id == sirket_id, Hareket.durum == "onayli",
                                              Hareket.banka_hesap_id.is_not(None))):
        if tarihe_kadar and sinir[h.banka_hesap_id] and h.tarih > sinir[h.banka_hesap_id]:
            continue
        bakiye[h.banka_hesap_id] += float(h.tutar) if h.yon == "giris" else -float(h.tutar)
    return {k: round(v, 2) for k, v in bakiye.items()}


def kasa_sorgusu(sirket_id: int):
    """Nakit kasa: bankaya bağlı olmayan para hareketleri. Çek hareketlerinden yalnızca kasadan ödenen / kasaya tahsil
    edilen girer (çekin alınması, verilmesi ve cirosu nakit değildir)."""
    return select(Hareket).where(Hareket.sirket_id == sirket_id, Hareket.banka_hesap_id.is_(None),
                                 or_(Hareket.cek_id.is_(None), Hareket.tur.in_(("cek_tahsil", "cek_odeme"))))


def kasa_bakiyesi(db: Session, sirket_id: int) -> float:
    return round(sum(float(h.tutar) * (1 if h.yon == "giris" else -1)
                     for h in db.scalars(kasa_sorgusu(sirket_id).where(Hareket.durum == "onayli"))), 2)
