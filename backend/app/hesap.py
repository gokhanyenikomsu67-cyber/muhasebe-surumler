"""Cari ve banka bakiyesi hesapları.

Cari bakiye pozitifse cari bize borçludur, negatifse biz cariye borçluyuz.
"""
from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .models import HAREKET_TURLERI, BankaHesabi, Depo, Fatura, FaturaKalem, Hareket, TaseronGider

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


def kalem_toplami(f: Fatura, kl: FaturaKalem) -> float:
    """Kalemin KDV dahil maliyeti (faturanın tevkifat/stopaj/diğer vergi farkı kalem tutarı oranında paylaştırılır),
    faturanın biriminde."""
    ara = sum(float(x.tutar) for x in f.kalemler)
    ek = float(f.genel_toplam) - ara - sum(x.kdv for x in f.kalemler)
    oran = float(kl.tutar) / ara if ara else 1 / len(f.kalemler)
    return float(kl.tutar) + kl.kdv + ek * oran


def depo_kalemleri(db: Session, sirket_id: int, cari_id: int | None = None, depo_id: int | None = None) -> list[dict]:
    """Onaylı alış faturalarında depoya ayrılmış kalemler (TL karşılığıyla). İade faturasında tutar eksidir.
    Depoya cari bağlıysa bu tutarlar o cariye borç yazılır; faturanın kendi carisi değişmez."""
    q = select(FaturaKalem, Fatura, Depo).join(Fatura, FaturaKalem.fatura_id == Fatura.id).join(Depo, FaturaKalem.depo_id == Depo.id) \
        .where(Fatura.sirket_id == sirket_id, Fatura.durum == "onayli")
    if cari_id is not None:
        q = q.where(Depo.cari_id == cari_id)
    if depo_id is not None:
        q = q.where(Depo.id == depo_id)
    satirlar = []
    for kl, f, d in db.execute(q.order_by(Fatura.tarih, Fatura.id, FaturaKalem.id)):
        if satis_tarafi(f):
            continue
        kur, i = tl_kur(f), isaret(f)
        satirlar.append({"depo_id": d.id, "depo": d.ad, "cari_id": d.cari_id, "santiye_id": kl.santiye_id or f.santiye_id,
                         "fatura_id": f.id, "tarih": f.tarih, "fatura_no": f.fatura_no,
                         "satici": f.cari.unvan if f.cari else None, "kalem": kl.aciklama,
                         "miktar": float(kl.miktar or 0), "birim": kl.birim,
                         "tutar": round(i * float(kl.tutar) * kur, 2), "kdv": round(i * kl.kdv * kur, 2),
                         "toplam": round(i * kalem_toplami(f, kl) * kur, 2), "kalem_id": kl.id})
    return satirlar


TASERON_GIDER_ADLARI = {"elden": "Elden harcama", "personel": "Personel ücreti / SGK"}


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
    # Taşeron adına harcananlar: depoya ayrılan fatura kalemleri ve faturasız giderler cariye borç yazılır
    depolu: dict[tuple, dict] = {}
    for d in depo_kalemleri(db, sirket_id, cari_id):
        if d["cari_id"] is None:
            continue
        s = depolu.setdefault((d["cari_id"], d["fatura_id"]), {
            "cari_id": d["cari_id"], "tarih": d["tarih"], "belge": d["fatura_no"],
            "aciklama": f"Adına harcanan malzeme ({d['depo']}, satıcı: {d['satici'] or '-'})",
            "borc": 0.0, "alacak": 0.0, "fatura_id": None, "hareket_id": None, "depo_fatura_id": d["fatura_id"],
            "sira": (2, d["fatura_id"], 0)})
        s["borc"] = round(s["borc"] + d["toplam"], 2)
    for s in depolu.values():
        if s["borc"] < 0:  # iade fazla: borç azalır
            s["borc"], s["alacak"] = 0.0, -s["borc"]
        satirlar.append(s)
    gq = select(TaseronGider).where(TaseronGider.sirket_id == sirket_id)
    if cari_id is not None:
        gq = gq.where(TaseronGider.cari_id == cari_id)
    personel: dict[tuple, dict] = {}
    for g in db.scalars(gq):
        if g.tur == "personel":  # bordro ayı tek satır
            s = personel.setdefault((g.cari_id, g.donem, g.tarih), {
                "cari_id": g.cari_id, "tarih": g.tarih, "belge": g.donem,
                "aciklama": f"Personel ücreti ve SGK ({g.donem or g.tarih})", "borc": 0.0, "alacak": 0.0,
                "fatura_id": None, "hareket_id": None, "sira": (3, g.id, 0)})
            s["borc"] = round(s["borc"] + float(g.tutar), 2)
            continue
        satirlar.append({"cari_id": g.cari_id, "tarih": g.tarih, "belge": None,
                         "aciklama": "Elden harcama" + (f" - {g.aciklama}" if g.aciklama else ""),
                         "borc": float(g.tutar), "alacak": 0.0, "fatura_id": None, "hareket_id": None, "sira": (3, g.id, 0)})
    satirlar.extend(personel.values())
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
