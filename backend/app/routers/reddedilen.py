"""Reddedilen faturalar: karşı tarafın reddettiği / iptal ettiği faturalar listesi.

Listedeki fatura yüklemede kaydedilmez; programda onaylı olarak kayıtlıysa iptal edilmesi önerilir."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import aktif_kullanici, yazabilir
from ..db import get_db
from ..models import Fatura, Kullanici, RedFatura
from .faturalar import _kayitli_fatura
from .temel import sirket_kaydi

router = APIRouter(prefix="/api/reddedilen-faturalar")

RED_NEDENI = "Karşı taraf faturayı reddetti."


def _okunan(r: RedFatura) -> dict:
    return {"fatura_no": r.fatura_no, "ettn": r.ettn, "satici" if r.yon == "gelen" else "alici": {"vkn": r.vkn}}


@router.get("")
def liste(db: Session = Depends(get_db), k: Kullanici = Depends(aktif_kullanici)) -> list[dict]:
    sonuc = []
    for r in db.scalars(select(RedFatura).where(RedFatura.sirket_id == k.sirket_id).order_by(RedFatura.tarih.desc(), RedFatura.id.desc())):
        f = _kayitli_fatura(db, k.sirket_id, _okunan(r), r.yon)
        sonuc.append({"id": r.id, "yon": r.yon, "fatura_no": r.fatura_no, "tarih": r.tarih.isoformat() if r.tarih else None,
                      "cari_unvan": r.unvan or (f.cari.unvan if f is not None and f.cari else None), "genel_toplam": float(r.tutar or 0),
                      "kayitli_id": f.id if f is not None and f.durum == "onayli" else None,
                      "durum": {"onayli": "Kayıtlı (iptal edilmeli)", "iptal": "İptal edildi", "taslak": "Onay bekliyor"}.get(
                          f.durum if f is not None else "", "Kaydedilmedi")})
    return sonuc


@router.delete("/{red_id}")
def listeden_cikar(red_id: int, db: Session = Depends(get_db), k: Kullanici = Depends(yazabilir)):
    """Yanlışlıkla listeye girmiş fatura: listeden çıkar, sonraki yüklemede normal kaydedilir."""
    db.delete(sirket_kaydi(db, RedFatura, red_id, k))
    db.commit()
    return {"ok": True}


class Idler(BaseModel):
    idler: list[int]


@router.post("/iptal-et")
def iptal_et(istek: Idler, db: Session = Depends(get_db), k: Kullanici = Depends(yazabilir)):
    """Reddedilen ama programda onaylı kayıtlı faturalar iptal edilir (silinmez; bakiyeden ve raporlardan düşer)."""
    n = 0
    for fid in istek.idler:
        f = sirket_kaydi(db, Fatura, fid, k)
        if f.durum == "onayli":
            f.durum, f.iptal_nedeni = "iptal", RED_NEDENI
            n += 1
    db.commit()
    return {"iptal_edilen": n}
