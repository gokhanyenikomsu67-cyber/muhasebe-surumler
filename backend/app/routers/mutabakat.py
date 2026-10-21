"""Mutabakat ekranı: banka (ekstre ile program), çek (vadesi geçen, ekstrede görünmeyen) ve cari (tarih itibarıyla bakiye).
Bakiyeler hesap.py'deki tek kaynaktan gelir; burada yalnız farkın nedeni olabilecek kayıtlar listelenir."""
from datetime import date, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import aktif_kullanici
from ..db import get_db
from ..hesap import banka_bakiyeleri, cari_hareketleri
from ..models import ACIK_CEK_DURUMLARI, CEK_DURUMLARI, HAREKET_TURLERI, BankaHesabi, Cari, Cek, Hareket, Kullanici

router = APIRouter(prefix="/api")

VADE_PAYI = 3  # vadesinden bu kadar gün sonra hâlâ bekleyen çek listelenir


def _satir(h: Hareket, neden: str) -> dict:
    return {"id": h.id, "tarih": h.tarih, "yon": h.yon, "tur": HAREKET_TURLERI.get(h.tur, h.tur), "tutar": float(h.tutar),
            "aciklama": h.aciklama, "cari": h.cari.unvan if h.cari else None, "cek_id": h.cek_id, "neden": neden}


def banka_mutabakati(db: Session, sirket_id: int) -> list[dict]:
    bakiye = banka_bakiyeleri(db, sirket_id)
    kadar = banka_bakiyeleri(db, sirket_id, tarihe_kadar=True)
    sonuc = []
    for b in db.scalars(select(BankaHesabi).where(BankaHesabi.sirket_id == sirket_id).order_by(BankaHesabi.ad)):
        r = {"id": b.id, "ad": b.ad, "kart": b.tur == "kredi_karti", "bakiye": bakiye.get(b.id, 0), "ekstre_tarihi": b.ekstre_tarihi,
             "ekstre_bakiye": float(b.ekstre_bakiye) if b.ekstre_bakiye is not None else None, "program_bakiye": None,
             "fark": None, "kayitlar": []}
        if b.ekstre_tarihi is None or b.ekstre_bakiye is None:
            sonuc.append(r)
            continue
        r["program_bakiye"] = kadar.get(b.id, 0)
        r["fark"] = round(r["ekstre_bakiye"] - r["program_bakiye"], 2)
        ilk = db.scalar(select(func.min(Hareket.tarih)).where(Hareket.banka_hesap_id == b.id, Hareket.ekstre_anahtari.is_not(None)))
        donem = select(Hareket).where(Hareket.banka_hesap_id == b.id, Hareket.tarih >= ilk, Hareket.tarih <= b.ekstre_tarihi)
        for h in db.scalars(donem.order_by(Hareket.tarih, Hareket.id)):
            if h.ekstre_anahtari is None and h.durum == "onayli":
                r["kayitlar"].append(_satir(h, "Programda var, ekstrede yok"))
            elif h.ekstre_anahtari is not None and h.durum == "taslak":
                r["kayitlar"].append(_satir(h, "Ekstrede var, onay bekliyor"))
            elif h.ekstre_anahtari is not None and h.durum == "iptal":
                r["kayitlar"].append(_satir(h, "Ekstrede var, programda iptal edilmiş"))
        sonuc.append(r)
    return sonuc


def cek_mutabakati(db: Session, sirket_id: int, bugun: date) -> dict:
    sinir = bugun - timedelta(days=VADE_PAYI)
    bekleyen = []
    for c in db.scalars(select(Cek).where(Cek.sirket_id == sirket_id, Cek.durum.in_(ACIK_CEK_DURUMLARI),
                                          Cek.vade < sinir).order_by(Cek.vade)):
        bekleyen.append({"id": c.id, "yon": c.yon, "vade": c.vade, "tutar": float(c.tutar), "cek_no": c.cek_no,
                         "cari": c.cari.unvan if c.cari else None, "durum": CEK_DURUMLARI[c.yon].get(c.durum, c.durum),
                         "neden": "Vadesi geçti; tahsil edildi mi?" if c.yon == "alinan" else "Vadesi geçti; ödendi mi?"})
    ekstrede_yok = []
    hesaplar = {b.id: b for b in db.scalars(select(BankaHesabi).where(BankaHesabi.sirket_id == sirket_id))}
    for h in db.scalars(select(Hareket).where(Hareket.sirket_id == sirket_id, Hareket.tur.in_(("cek_tahsil", "cek_odeme")),
                                              Hareket.ekstre_anahtari.is_(None), Hareket.durum == "onayli")):
        b = hesaplar.get(h.banka_hesap_id)
        if b and b.ekstre_tarihi and h.tarih <= b.ekstre_tarihi:
            ekstrede_yok.append({**_satir(h, "Banka ekstresinde görünmüyor"), "banka": b.ad})
    portfoy = db.scalar(select(func.coalesce(func.sum(Cek.tutar), 0)).where(
        Cek.sirket_id == sirket_id, Cek.yon == "alinan", Cek.durum.in_(("portfoyde", "tahsilde", "teminatta"))))
    verilen = db.scalar(select(func.coalesce(func.sum(Cek.tutar), 0)).where(
        Cek.sirket_id == sirket_id, Cek.yon == "verilen", Cek.durum == "verildi"))
    return {"portfoy": round(float(portfoy), 2), "verilen": round(float(verilen), 2), "vadesi_gecen": bekleyen,
            "ekstrede_yok": ekstrede_yok}


def cari_mutabakati(db: Session, sirket_id: int, tarih: date) -> list[dict]:
    toplam: dict[int, float] = {}
    for s in cari_hareketleri(db, sirket_id):
        if s["tarih"] is None or s["tarih"] <= tarih:
            toplam[s["cari_id"]] = toplam.get(s["cari_id"], 0) + s["borc"] - s["alacak"]
    cariler = {c.id: c for c in db.scalars(select(Cari).where(Cari.sirket_id == sirket_id))}
    return sorted(({"id": i, "unvan": cariler[i].unvan, "vkn": cariler[i].vkn, "eposta": cariler[i].eposta,
                    "bakiye": round(v, 2)} for i, v in toplam.items() if abs(v) >= 0.01 and i in cariler),
                  key=lambda r: -abs(r["bakiye"]))


@router.get("/mutabakat")
def mutabakat(tarih: date | None = None, db: Session = Depends(get_db), k: Kullanici = Depends(aktif_kullanici)):
    tarih = tarih or date.today()
    return {"tarih": tarih, "banka": banka_mutabakati(db, k.sirket_id), "cek": cek_mutabakati(db, k.sirket_id, date.today()),
            "cari": cari_mutabakati(db, k.sirket_id, tarih)}
