"""Değişiklik geçmişi ekranı ve kayıtlı fatura/hareketin iptali (silmeden, geçmişiyle)."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import gecmis
from ..auth import aktif_kullanici, yazabilir
from ..db import get_db
from ..models import BankaHesabi, Cari, Degisiklik, Fatura, Hareket, Kullanici, Santiye
from .temel import sirket_kaydi

router = APIRouter(prefix="/api")

_AD_ALANLARI = {"cari_id": Cari, "ciro_cari_id": Cari, "banka_hesap_id": BankaHesabi, "santiye_id": Santiye}
_DURUMLAR = {"taslak": "Taslak", "onayli": "Onaylı", "iptal": "İptal"}


@router.get("/gecmis")
def gecmis_listesi(tablo: str | None = None, kayit_id: int | None = None, limit: int = 500,
                   db: Session = Depends(get_db), k: Kullanici = Depends(aktif_kullanici)):
    q = select(Degisiklik).where(Degisiklik.sirket_id == k.sirket_id)
    if tablo:
        q = q.where(Degisiklik.tablo == tablo)
    if kayit_id is not None:
        q = q.where(Degisiklik.kayit_id == kayit_id)
    satirlar = db.scalars(q.order_by(Degisiklik.id.desc()).limit(min(limit, 5000))).all()
    kullanicilar = {u.id: u.ad for u in db.scalars(select(Kullanici).where(Kullanici.sirket_id == k.sirket_id))}
    adlar: dict[tuple, str] = {}

    def ad(alan, deger):
        if deger in (None, ""):
            return None
        if alan == "durum":
            return _DURUMLAR.get(deger, deger)
        model = _AD_ALANLARI.get(alan)
        if not model:
            return deger
        if (alan, deger) not in adlar:
            kayit = db.get(model, deger)
            adlar[(alan, deger)] = (getattr(kayit, "unvan", None) or getattr(kayit, "ad", None)) if kayit and kayit.sirket_id == k.sirket_id else f"#{deger}"
        return adlar[(alan, deger)]

    sonuc = []
    for d in satirlar:
        ozet = d.ozet
        if d.islem == "degisti" and d.alanlar:
            okunur = {a: [ad(a, e), ad(a, y)] if a != "kalemler" else [e, y] for a, (e, y) in d.alanlar.items()}
            ozet = gecmis._ozet(d.islem, d.ozet.split(":")[0], okunur)
        sonuc.append({"id": d.id, "zaman": d.zaman, "kullanici": kullanicilar.get(d.kullanici_id, "Program"),
                      "tablo": d.tablo, "kayit_id": d.kayit_id, "islem": d.islem, "ozet": ozet, "alanlar": d.alanlar})
    return sonuc


class Iptal(BaseModel):
    neden: str


def _neden(veri: Iptal) -> str:
    neden = (veri.neden or "").strip()
    if len(neden) < 3:
        raise HTTPException(400, "İptal nedenini yazın.")
    return neden[:500]


@router.post("/faturalar/{fatura_id}/iptal")
def fatura_iptal(fatura_id: int, veri: Iptal, db: Session = Depends(get_db), k: Kullanici = Depends(yazabilir)):
    """Onaylı fatura silinmez, iptal edilir: bakiyelerden ve raporlardan düşer, kaydı ve geçmişi kalır."""
    f = sirket_kaydi(db, Fatura, fatura_id, k)
    if f.durum != "onayli":
        raise HTTPException(400, "Yalnız onaylı fatura iptal edilir; taslak fatura silinebilir.")
    f.durum, f.iptal_nedeni = "iptal", _neden(veri)
    db.commit()
    return {"ok": True}


@router.post("/faturalar/{fatura_id}/iptal-geri")
def fatura_iptal_geri(fatura_id: int, db: Session = Depends(get_db), k: Kullanici = Depends(yazabilir)):
    from .faturalar import mukerrer_mi
    f = sirket_kaydi(db, Fatura, fatura_id, k)
    if f.durum != "iptal":
        raise HTTPException(400, "Bu fatura iptal edilmemiş.")
    if mukerrer_mi(db, f):
        raise HTTPException(409, f"{f.fatura_no} numaralı fatura bu cari için yeniden kaydedilmiş; iptal geri alınamaz.")
    f.durum, f.iptal_nedeni = "onayli", None
    db.commit()
    return {"ok": True}


def _hareket(db: Session, hareket_id: int, k: Kullanici) -> Hareket:
    from .banka import ESLEME_UYARISI
    h = sirket_kaydi(db, Hareket, hareket_id, k)
    if h.cek_id:
        raise HTTPException(400, "Çek hareketleri çek ekranından değiştirilir.")
    if h.kaynak == "esleme" and h.bagli_hareket_id:
        raise HTTPException(400, ESLEME_UYARISI)
    return h


@router.post("/hareketler/{hareket_id}/iptal")
def hareket_iptal(hareket_id: int, veri: Iptal, db: Session = Depends(get_db), k: Kullanici = Depends(yazabilir)):
    from .banka import esle
    h = _hareket(db, hareket_id, k)
    if h.durum != "onayli":
        raise HTTPException(400, "Yalnız onaylı hareket iptal edilir; onay bekleyen satır silinebilir.")
    h.durum, h.iptal_nedeni = "iptal", _neden(veri)
    esle(db, h)  # kasadaki/karşı hesaptaki karşılığı da kalkar
    db.commit()
    return {"ok": True}


@router.post("/hareketler/{hareket_id}/iptal-geri")
def hareket_iptal_geri(hareket_id: int, db: Session = Depends(get_db), k: Kullanici = Depends(yazabilir)):
    from .banka import esle
    h = _hareket(db, hareket_id, k)
    if h.durum != "iptal":
        raise HTTPException(400, "Bu hareket iptal edilmemiş.")
    h.durum, h.iptal_nedeni = "onayli", None
    esle(db, h)
    db.commit()
    return {"ok": True}
