"""Banka hesapları, para hareketleri ve yapay zeka ile banka ekstresi işleme."""
import hashlib
import re
from collections import Counter
from datetime import date, timedelta

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .. import ai, kart, kural, schemas
from ..auth import aktif_kullanici, yazabilir
from ..db import get_db
from ..hesap import banka_bakiyeleri, kasa_bakiyesi, kasa_sorgusu
from ..models import GIDER_TURLERI, HAREKET_TURLERI, BankaHesabi, Cari, Hareket, Kullanici, Santiye, Sirket
from ..yukleme import dosyayi_oku
from . import cekler, kartlar
from .faturalar import KAYIT_KILIDI
from .temel import sirket_kaydi

router = APIRouter(prefix="/api")


# --- Banka hesapları -----------------------------------------------------

@router.get("/banka-hesaplari", response_model=list[schemas.BankaHesabiCikis])
def hesaplar(db: Session = Depends(get_db), k: Kullanici = Depends(aktif_kullanici)):
    bakiye = banka_bakiyeleri(db, k.sirket_id)
    kadar = banka_bakiyeleri(db, k.sirket_id, tarihe_kadar=True)
    sayilar = {(b, d): n for b, d, n in db.execute(select(Hareket.banka_hesap_id, Hareket.durum, func.count())
                                                   .where(Hareket.sirket_id == k.sirket_id).group_by(Hareket.banka_hesap_id, Hareket.durum))}
    sonuc = []
    for b in db.scalars(select(BankaHesabi).where(BankaHesabi.sirket_id == k.sirket_id).order_by(BankaHesabi.ad)):
        s = schemas.BankaHesabiCikis.model_validate(b)
        s.bakiye = bakiye.get(b.id, 0)
        s.onay_bekleyen = sayilar.get((b.id, "taslak"), 0)
        s.hareket_sayisi = s.onay_bekleyen + sayilar.get((b.id, "onayli"), 0)
        if b.ekstre_bakiye is not None:
            s.mutabakat_farki = round(float(b.ekstre_bakiye) - kadar.get(b.id, 0), 2)
        sonuc.append(s)
    return sonuc


@router.post("/banka-hesaplari", response_model=schemas.BankaHesabiCikis)
def hesap_ekle(veri: schemas.BankaHesabiGiris, db: Session = Depends(get_db), k: Kullanici = Depends(yazabilir)):
    _tur_kontrol(veri)
    b = BankaHesabi(sirket_id=k.sirket_id, **veri.model_dump())
    db.add(b)
    db.commit()
    s = schemas.BankaHesabiCikis.model_validate(b)
    s.bakiye = float(b.acilis_bakiyesi)
    return s


@router.put("/banka-hesaplari/{hesap_id}", response_model=schemas.BankaHesabiCikis)
def hesap_guncelle(hesap_id: int, veri: schemas.BankaHesabiGiris, db: Session = Depends(get_db), k: Kullanici = Depends(yazabilir)):
    b = sirket_kaydi(db, BankaHesabi, hesap_id, k)
    _tur_kontrol(veri)
    if abs(float(veri.acilis_bakiyesi) - float(b.acilis_bakiyesi or 0)) > 0.005:
        b.acilis_ekstreden = False  # elle girilen açılış bakiyesi ekstreyle değiştirilmez
    for alan, deger in veri.model_dump().items():
        setattr(b, alan, deger)
    db.commit()
    s = schemas.BankaHesabiCikis.model_validate(b)
    s.bakiye = banka_bakiyeleri(db, k.sirket_id).get(b.id, 0)
    return s


def _tur_kontrol(veri: schemas.BankaHesabiGiris) -> None:
    if veri.tur not in ("banka", kartlar.KART):
        raise HTTPException(400, "Hesap türü 'banka' ya da 'kredi_karti' olmalı.")


@router.get("/banka-hesaplari/{hesap_id}/silme-ozeti")
def hesap_silme_ozeti(hesap_id: int, db: Session = Depends(get_db), k: Kullanici = Depends(aktif_kullanici)):
    """Hesap hareketleriyle birlikte silinirse ne gider: hareket sayısı, giriş/çıkış toplamı, bakiyesi değişen cari sayısı."""
    b = sirket_kaydi(db, BankaHesabi, hesap_id, k)
    hs = db.scalars(select(Hareket).where(Hareket.banka_hesap_id == b.id)).all()
    onayli = [h for h in hs if h.durum == "onayli"]
    return {"hareket": len(hs), "onay_bekleyen": len(hs) - len(onayli),
            "giris": round(sum(float(h.tutar) for h in onayli if h.yon == "giris"), 2),
            "cikis": round(sum(float(h.tutar) for h in onayli if h.yon == "cikis"), 2),
            "cari": len({h.cari_id for h in onayli if h.cari_id}), "cek": sum(1 for h in hs if h.cek_id)}


@router.delete("/banka-hesaplari/{hesap_id}")
def hesap_sil(hesap_id: int, hareketlerle: bool = False, db: Session = Depends(get_db), k: Kullanici = Depends(yazabilir)):
    """Hareketi olan hesap ancak hareketlerle=true ile silinir: önce yedek alınır; virman/nakit çekimin karşı hesaptaki
    ya da kasadaki eşleme kaydı da silinir. Çek hareketi olan hesap silinmez (çek durumu bozulmasın)."""
    b = sirket_kaydi(db, BankaHesabi, hesap_id, k)
    hs = db.scalars(select(Hareket).where(Hareket.banka_hesap_id == b.id)).all()
    if hs and not hareketlerle:
        raise HTTPException(409, f"{len(hs)} hareketi var, silinemez. Önce hareketlerini silin ya da hesabı hareketleriyle "
                                 "birlikte silin.")
    if n := sum(1 for h in hs if h.cek_id):
        raise HTTPException(409, f"{n} çek hareketi var, silinemez. O çeklerin işlemini çek kartından geri alın.")
    if hs:
        from .. import yedek
        try:
            yedek.yedek_al()
        except Exception as e:  # noqa: BLE001  yedeksiz toplu silme yapılmaz
            raise HTTPException(500, f"Silmeden önce yedek alınamadı, hiçbir şey silinmedi: {e}") from e
    idler = {h.id for h in hs}
    for h in hs:
        h.durum = "silinecek"
        esle(db, h)  # karşı hesaptaki/kasadaki eşleme kaydı silinir, ekstreden gelen karşılığın bağı çözülür
    db.flush()
    for h in db.scalars(select(Hareket).where(Hareket.bagli_hareket_id.in_(idler))):
        h.bagli_hareket_id = None
    for h in hs:
        db.delete(h)
    db.flush()
    db.delete(b)
    db.commit()
    return {"ok": True, "silinen_hareket": len(hs)}


# --- Hareketler ----------------------------------------------------------

def hareket_cikis(h: Hareket) -> schemas.HareketCikis:
    s = schemas.HareketCikis.model_validate(h)
    s.cari_unvan = h.cari.unvan if h.cari else None
    s.banka_hesap_ad = h.banka_hesap.ad if h.banka_hesap else None
    s.santiye_ad = h.santiye.ad if h.santiye else None
    s.sorun = sorun(h)
    return s


def muhtelif_cari_id(db: Session, sirket_id: int) -> int:
    """EFT ücreti, KMH faizi, BSMV, komisyon, kredi ödemesi gibi banka işlemlerinin işlendiği cari; yoksa açar."""
    for c in db.scalars(select(Cari).where(Cari.sirket_id == sirket_id)):
        if kural.sade(c.unvan) == kural.sade(MUHTELIF_CARI):
            return c.id
    c = Cari(sirket_id=sirket_id, unvan=MUHTELIF_CARI, tur="tedarikci")
    db.add(c)
    db.flush()
    return c.id


def sorun(h: Hareket) -> str | None:
    """Programın kendi başına işleyemediği satırın nedeni; ekranda kırmızı gösterilir."""
    if h.durum != "taslak":
        return None
    if h.tur in ("tahsilat", "odeme") and not h.cari_id:
        return "Karşı taraf okunamadı; cariyi seçin."
    if h.tur == "diger" and not h.cari_id:
        return "Ne olduğu anlaşılamadı; türünü ya da carisini seçin."
    if h.tur == "virman" and h.banka_hesap_id and not h.bagli_hareket_id and not (h.ai_okuma or {}).get("karsi_hesap_id"):
        if h.banka_hesap and h.banka_hesap.tur == kartlar.KART:
            return "Kart borcunun hangi banka hesabından ödendiği bulunamadı; o hesabın ekstresi yüklenince eşleşir."
        return "Hangi hesabınıza gittiği/geldiği bulunamadı; yalnız bu hesaba işlenir."
    return None


# --- Hesaplar arası ve kasa eşleştirmesi --------------------------------

ESLENEN_TURLER = ("virman", "nakit_cekim", "nakit_yatirma")
ELLE_GUN = 3  # elle girilen banka hareketi ile ekstre satırı arasında izin verilen gün farkı


def _karsi_hesap(h: Hareket) -> tuple[bool, int | None]:
    """Bu hareketin karşılığı hangi hesaba yazılmalı? (gerekli mi, banka hesabı; None = nakit kasa)"""
    if h.bagli_hareket_id or h.durum != "onayli" or not h.banka_hesap_id:
        return False, None
    if h.tur in ("nakit_cekim", "nakit_yatirma"):
        return True, None
    hedef = (h.ai_okuma or {}).get("karsi_hesap_id")
    if h.tur == "virman" and hedef and hedef != h.banka_hesap_id:
        return True, hedef
    return False, None


def esle(db: Session, h: Hareket) -> None:
    """Bankadan çıkan virman/nakit çekimin karşı hesaptaki (ya da kasadaki) girişini yazar, günceller ya da kaldırır.

    Karşı hesabın ekstresi önceden yüklenmişse aynı transfer orada aranır ve ikinci kez yazılmaz.
    """
    db.flush()
    gerekli, hedef = _karsi_hesap(h)
    bagli = list(db.scalars(select(Hareket).where(Hareket.bagli_hareket_id == h.id)))
    if not gerekli:
        for b in bagli:
            if b.kaynak == "esleme":
                db.delete(b)
            else:
                b.bagli_hareket_id = None
        return
    karsi_yon = "giris" if h.yon == "cikis" else "cikis"
    if bagli:
        for b in bagli:
            if b.kaynak == "esleme":
                b.tarih, b.tutar, b.yon, b.tur, b.banka_hesap_id = h.tarih, h.tutar, karsi_yon, h.tur, hedef
        return
    # Kart borcu ödemesi bankadan çıktığı gün karta geçmeyebilir: kartla ilgili virmanda birkaç gün fark olabilir.
    gun = kartlar.GUN if kartlar.kart_ilgili(db, h.banka_hesap_id, hedef) else 0
    q = select(Hareket).where(
        Hareket.sirket_id == h.sirket_id, Hareket.id != h.id, Hareket.yon == karsi_yon,
        Hareket.tarih.between(h.tarih - timedelta(days=gun), h.tarih + timedelta(days=gun)),
        func.abs(Hareket.tutar - float(h.tutar)) < 0.005, Hareket.tur.in_(ESLENEN_TURLER),
        Hareket.bagli_hareket_id.is_(None), Hareket.cek_id.is_(None),
        Hareket.banka_hesap_id == hedef if hedef else Hareket.banka_hesap_id.is_(None))
    for aday in sorted(db.scalars(q), key=lambda a: abs((a.tarih - h.tarih).days)):
        if not db.scalar(select(Hareket.id).where(Hareket.bagli_hareket_id == aday.id).limit(1)):
            aday.bagli_hareket_id = h.id
            return
    kaynak_ad = h.banka_hesap.ad if h.banka_hesap else "banka"
    aciklama = {"nakit_cekim": f"{kaynak_ad} hesabından nakit çekim", "nakit_yatirma": f"{kaynak_ad} hesabına nakit yatırma"}.get(
        h.tur, f"{kaynak_ad} hesabı{'ndan' if karsi_yon == 'giris' else 'na'} transfer")
    db.add(Hareket(sirket_id=h.sirket_id, durum="onayli", tarih=h.tarih, yon=karsi_yon, tur=h.tur, tutar=h.tutar,
                   banka_hesap_id=hedef, aciklama=aciklama, kaynak="esleme", bagli_hareket_id=h.id))


def ekstre_tazele(db: Session, hesap: BankaHesabi | None) -> None:
    """Hesabın ekstre bilgisini kalan ekstre satırlarından yeniden kurar: son bakiye/tarih son satırdan,
    ekstreden gelen açılış bakiyesi ilk satırdan. Ekstre satırı kalmadıysa ekstre bilgisi temizlenir
    (hareketi olmayan hesapta eski ekstre bakiyesi ve sahte mutabakat farkı kalmaz)."""
    if hesap is None:
        return
    db.flush()
    satirlar = [h for h in db.scalars(select(Hareket).where(Hareket.banka_hesap_id == hesap.id, Hareket.ekstre_anahtari.is_not(None))
                                      .order_by(Hareket.tarih, Hareket.id))
                if (h.ai_okuma or {}).get("bakiye") is not None]
    if not satirlar:
        hesap.ekstre_tarihi = hesap.ekstre_bakiye = None
        if hesap.acilis_ekstreden:
            hesap.acilis_bakiyesi, hesap.acilis_ekstreden = 0, False
        return
    ilk, son = satirlar[0], satirlar[-1]
    hesap.ekstre_tarihi, hesap.ekstre_bakiye = son.tarih, float(son.ai_okuma["bakiye"])
    if hesap.acilis_ekstreden:
        isaretli = float(ilk.tutar) if ilk.yon == "giris" else -float(ilk.tutar)
        hesap.acilis_bakiyesi = round(float(ilk.ai_okuma["bakiye"]) - isaretli, 2)


@router.get("/kasa")
def kasa(db: Session = Depends(get_db), k: Kullanici = Depends(aktif_kullanici)):
    """Nakit kasa: bakiye ve onaylı hareketler."""
    hareketler = db.scalars(kasa_sorgusu(k.sirket_id).where(Hareket.durum == "onayli")
                            .order_by(Hareket.tarih.desc(), Hareket.id.desc()))
    return {"bakiye": kasa_bakiyesi(db, k.sirket_id), "hareketler": [hareket_cikis(h) for h in hareketler]}


@router.get("/hareket-turleri")
def hareket_turleri(k: Kullanici = Depends(aktif_kullanici)):
    return HAREKET_TURLERI


@router.get("/hareketler", response_model=list[schemas.HareketCikis])
def hareketler(durum: str | None = None, banka_hesap_id: int | None = None, cari_id: int | None = None,
               baslangic: date | None = None, bitis: date | None = None,
               db: Session = Depends(get_db), k: Kullanici = Depends(aktif_kullanici)):
    q = select(Hareket).where(Hareket.sirket_id == k.sirket_id)
    for alan, deger in [(Hareket.durum, durum), (Hareket.banka_hesap_id, banka_hesap_id), (Hareket.cari_id, cari_id)]:
        if deger is not None:
            q = q.where(alan == deger)
    if baslangic:
        q = q.where(Hareket.tarih >= baslangic)
    if bitis:
        q = q.where(Hareket.tarih <= bitis)
    return [hareket_cikis(h) for h in db.scalars(q.order_by(Hareket.tarih.desc(), Hareket.id.desc()))]


def _kontrol(db: Session, veri: schemas.HareketGiris, k: Kullanici):
    if veri.yon not in ("giris", "cikis"):
        raise HTTPException(400, "Hareket yönü 'giris' veya 'cikis' olmalı.")
    if veri.tur not in HAREKET_TURLERI:
        raise HTTPException(400, "Geçersiz hareket türü.")
    if veri.tutar <= 0:
        raise HTTPException(400, "Tutar sıfırdan büyük olmalı.")
    for model, kimlik in [(Cari, veri.cari_id), (BankaHesabi, veri.banka_hesap_id), (Santiye, veri.santiye_id)]:
        if kimlik:
            sirket_kaydi(db, model, kimlik, k)


@router.post("/hareketler", response_model=schemas.HareketCikis)
def hareket_ekle(veri: schemas.HareketGiris, db: Session = Depends(get_db), k: Kullanici = Depends(yazabilir)):
    _kontrol(db, veri, k)
    h = Hareket(sirket_id=k.sirket_id, **veri.model_dump())
    db.add(h)
    esle(db, h)
    db.commit()
    return hareket_cikis(h)


ESLEME_UYARISI = ("Bu satır bankadaki nakit çekim / hesaplar arası transferin karşılığıdır; bankadaki hareketi "
                  "değiştirin ya da silin, bu satır onunla birlikte değişir.")


@router.get("/hareketler/{hareket_id}", response_model=schemas.HareketCikis)
def hareket_getir(hareket_id: int, db: Session = Depends(get_db), k: Kullanici = Depends(aktif_kullanici)):
    return hareket_cikis(sirket_kaydi(db, Hareket, hareket_id, k))


@router.put("/hareketler/{hareket_id}", response_model=schemas.HareketCikis)
def hareket_guncelle(hareket_id: int, veri: schemas.HareketGiris, db: Session = Depends(get_db), k: Kullanici = Depends(yazabilir)):
    h = sirket_kaydi(db, Hareket, hareket_id, k)
    if h.cek_id:
        raise HTTPException(400, "Çek hareketleri çek ekranından değiştirilir.")
    if h.kaynak == "esleme" and h.bagli_hareket_id:
        raise HTTPException(400, ESLEME_UYARISI)
    if h.durum == "iptal":
        raise HTTPException(400, "İptal edilmiş hareket değiştirilemez; önce iptali geri alın.")
    _kontrol(db, veri, k)
    for alan, deger in veri.model_dump().items():
        setattr(h, alan, deger)
    esle(db, h)
    kartlar.isyeri_ogren(db, h)
    db.commit()
    return hareket_cikis(h)


@router.delete("/hareketler/{hareket_id}")
def hareket_sil(hareket_id: int, db: Session = Depends(get_db), k: Kullanici = Depends(yazabilir)):
    h = sirket_kaydi(db, Hareket, hareket_id, k)
    if h.cek_id:
        raise HTTPException(400, "Çek hareketleri çek ekranından silinir.")
    if h.kaynak == "esleme" and h.bagli_hareket_id:
        raise HTTPException(400, ESLEME_UYARISI)
    h.durum = "silinecek"
    esle(db, h)
    hesap = h.banka_hesap
    db.delete(h)
    ekstre_tazele(db, hesap)
    db.commit()
    return {"ok": True}


class SilIstegi(BaseModel):
    idler: list[int]


@router.post("/hareketler/toplu-sil")
def hareket_toplu_sil(istek: SilIstegi, db: Session = Depends(get_db), k: Kullanici = Depends(yazabilir)):
    """Seçilen hareketleri siler; birden çok hareket silinecekse önce yedek alınır. Çek hareketleri silinmez."""
    hs = db.scalars(select(Hareket).where(Hareket.sirket_id == k.sirket_id, Hareket.id.in_(istek.idler))).all()
    secilen = {h.id for h in hs}
    # Karşılık satırı (kasadaki nakit çekim, karşı hesaptaki transfer) bankadaki asıl hareketiyle birlikte silinir
    tek_eslenen = [h for h in hs if h.kaynak == "esleme" and h.bagli_hareket_id and h.bagli_hareket_id not in secilen]
    silinecek = [h for h in hs if not h.cek_id and h not in tek_eslenen]
    if len(silinecek) > 1:
        from .. import yedek
        try:
            yedek.yedek_al()
        except Exception as e:  # noqa: BLE001  yedeksiz toplu silme yapılmaz
            raise HTTPException(500, f"Silmeden önce yedek alınamadı, hiçbir şey silinmedi: {e}") from e
    hesaplar = {h.banka_hesap for h in silinecek if h.banka_hesap}
    idler = {h.id for h in silinecek}
    cari_idleri = {h.cari_id for h in silinecek if h.cari_id}
    for h in silinecek:
        h.durum = "silinecek"
        esle(db, h)
    db.flush()
    for h in db.scalars(select(Hareket).where(Hareket.bagli_hareket_id.in_(idler))):
        h.bagli_hareket_id = None
    for h in silinecek:
        if h in db:
            db.delete(h)
    db.flush()
    for b in hesaplar:
        ekstre_tazele(db, b)
    # Bu satırlar için kendiliğinden açılmış, başka hiçbir kayıtta kullanılmayan cariler de silinir
    # (yanlış hesaba yüklenen ekstre silinince "NAKİT ÇEKİLEN" gibi cariler kalmasın)
    from ..models import DuzenliOdeme, IsyeriEslesme
    from .temel import bagli_kayitlar
    for c in db.scalars(select(Cari).where(Cari.id.in_(cari_idleri), Cari.ad_otomatik.is_(True))):
        if not bagli_kayitlar(db, cari_id=c.id) and not db.scalar(select(DuzenliOdeme.id).where(DuzenliOdeme.cari_id == c.id)):
            db.execute(delete(IsyeriEslesme).where(IsyeriEslesme.cari_id == c.id))
            db.delete(c)
    db.commit()
    return {"silinen": len(silinecek), "silinmeyen": [f"Çek hareketi (çek kartından silinir): {h.aciklama or h.id}"
                                                     for h in hs if h.cek_id]
            + [f"Bankadaki harekete bağlı karşılık (bankadaki hareketle silinir): {h.aciklama or h.id}" for h in tek_eslenen]}


class OnayIstegi(BaseModel):
    idler: list[int]


class TopluHareket(BaseModel):
    idler: list[int]
    cari_id: int | None = None
    muhtelif: bool = False  # seçilenleri MUHTELİF BANKA İŞLEMLERİ carisine ata
    tur: str | None = None


@router.post("/hareketler/toplu-guncelle")
def hareket_toplu_guncelle(istek: TopluHareket, db: Session = Depends(get_db), k: Kullanici = Depends(yazabilir)):
    """Onay bekleyen hareketlere toplu cari ve/veya tür atar."""
    cari_id = muhtelif_cari_id(db, k.sirket_id) if istek.muhtelif else istek.cari_id
    if cari_id:
        sirket_kaydi(db, Cari, cari_id, k)
    if istek.tur and istek.tur not in HAREKET_TURLERI:
        raise HTTPException(400, "Geçersiz hareket türü.")
    n = 0
    for h in db.scalars(select(Hareket).where(Hareket.sirket_id == k.sirket_id, Hareket.id.in_(istek.idler),
                                              Hareket.durum == "taslak", Hareket.cek_id.is_(None))).all():
        if cari_id:
            h.cari_id = cari_id
            kartlar.isyeri_ogren(db, h)
        if istek.tur:
            h.tur = istek.tur
        n += 1
    db.commit()
    return {"guncellenen": n}


@router.post("/hareketler/onayla")
def hareket_onayla(istek: OnayIstegi, db: Session = Depends(get_db), k: Kullanici = Depends(yazabilir)):
    sayi = 0
    for h in db.scalars(select(Hareket).where(Hareket.sirket_id == k.sirket_id, Hareket.id.in_(istek.idler),
                                              Hareket.durum == "taslak")).all():
        h.durum = "onayli"
        esle(db, h)
        kartlar.isyeri_ogren(db, h)
        sayi += 1
    db.commit()
    return {"onaylanan": sayi}


# --- Banka ekstresi ------------------------------------------------------

MUHTELIF_CARI = "MUHTELİF BANKA İŞLEMLERİ"
EKSTRE_TURLERI = ai.EKSTRE_TABLO_TURLERI | set(ai.DESTEKLENEN_TURLER)
_YON = {"tahsilat": "giris", "cek_tahsil": "giris", "odeme": "cikis", "masraf": "cikis", "banka_masrafi": "cikis",
        "cek_odeme": "cikis", "nakit_cekim": "cikis", "nakit_yatirma": "giris",
        "kredi_odeme": "cikis"}


def dosya_turu(dosya: UploadFile) -> str:
    mime = dosya.content_type or ""
    ad = (dosya.filename or "").lower()
    if ad.endswith(".xlsx"):
        mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    elif ad.endswith(".csv"):
        mime = "text/csv"
    elif ad.endswith(".pdf"):
        mime = "application/pdf"
    elif ad.endswith(".xls"):
        raise HTTPException(422, "Eski .xls biçimi desteklenmiyor. Dosyayı Excel'de açıp .xlsx olarak kaydedin.")
    if mime not in EKSTRE_TURLERI:
        raise HTTPException(422, "Ekstre Excel (.xlsx), CSV, PDF veya görsel olmalı.")
    return mime


def atlanan_nedeni(db: Session, hesap_id: int, anahtarlar: list[str]) -> str:
    """Atlanan ekstre satırları neden atlandı: hepsi daha önce yüklenmiştir; nerede durdukları söylenir."""
    if not anahtarlar:
        return ""
    durumlar = Counter(db.scalars(select(Hareket.durum).where(Hareket.banka_hesap_id == hesap_id,
                                                               Hareket.ekstre_anahtari.in_(set(anahtarlar)))))
    yer = [f"{n} tanesi {ad}" for d, ad in (("taslak", "Onay Bekleyen Hareketler'de onay bekliyor"), ("onayli", "onaylanmış"),
                                             ("iptal", "iptal edilmiş")) if (n := durumlar.get(d))]
    return f"{len(anahtarlar)} satır bu hesaba daha önce yüklenmiş, ikinci kez eklenmedi" + (f" ({', '.join(yer)})" if yer else "") + "."


def ekstre_anahtari(hesap_id: int, tarih: str, tutar: float, aciklama: str, bakiye: float | None = None) -> str:
    normal = " ".join(aciklama.lower().split())
    # Bakiye, aynı gün aynı açıklamalı iki ayrı satırı (ör. iki EFT masrafı) birbirinden ayırır.
    ek = f"|{bakiye:.2f}" if isinstance(bakiye, (int, float)) else ""
    return hashlib.sha256(f"{hesap_id}|{tarih}|{tutar:.2f}|{normal}{ek}".encode()).hexdigest()


def eskiden_yeniye(satirlar: list[dict]) -> list[dict]:
    """Ekstre satırlarını eskiden yeniye dizer. Yeniden eskiye sıralı ekstre ters çevrilir; ilk ve son satır aynı
    günse sıra bakiye zincirinden anlaşılır (önceki bakiye + tutar = sonraki bakiye)."""
    if len(satirlar) < 2:
        return satirlar
    ilk, son = satirlar[0].get("tarih") or "", satirlar[-1].get("tarih") or ""
    if ilk != son:
        return satirlar[::-1] if ilk > son else satirlar
    ileri = geri = 0
    for a, b in zip(satirlar, satirlar[1:]):
        try:
            ab, bb, at, bt = float(a["bakiye"]), float(b["bakiye"]), float(a.get("tutar") or 0), float(b.get("tutar") or 0)
        except (KeyError, TypeError, ValueError):
            continue
        ileri += abs(ab + bt - bb) < 0.01
        geri += abs(bb + at - ab) < 0.01
    return satirlar[::-1] if geri > ileri else satirlar


@router.post("/banka-hesaplari/{hesap_id}/ekstre")
def ekstre_yukle(hesap_id: int, dosya: UploadFile = File(...), yontem: str = "otomatik",
                 db: Session = Depends(get_db), k: Kullanici = Depends(yazabilir)):
    """Ekstreyi okur; her satırı taslak hareket olarak kaydeder.

    yontem: otomatik | kural (yapay zekasız) | ai. Excel/CSV otomatikte önce sütun başlıklarından
    okunur, PDF metninden okunur; okunamazsa ve anahtar varsa yapay zekaya gönderilir. Görseller
    yalnızca yapay zekayla okunur.
    """
    hesap = sirket_kaydi(db, BankaHesabi, hesap_id, k)
    icerik = dosyayi_oku(dosya)
    mime = dosya_turu(dosya)
    # Kredi kartı ekstresi (kart hesabına yüklendi ya da içeriğinden anlaşıldı) kart kurallarıyla işlenir.
    if hesap.tur == kartlar.KART or (yontem != "ai" and kart.kart_ekstresi_mi(kart.tespit_metni(icerik, mime))):
        okunan = kartlar.oku(icerik, mime)
        notlar = []
        son4 = okunan.get("kart_son4")
        if hesap.tur != kartlar.KART or (son4 and hesap.kart_no and hesap.kart_no[-4:] != son4):
            hesap, yeni = kartlar.kart_hesabi(db, k.sirket_id, son4, okunan.get("banka"))
            notlar.append(f"Kredi kartı ekstresi; {'yeni açılan ' if yeni else ''}{hesap.ad} hesabına işlendi.")
        elif son4 and not hesap.kart_no:
            hesap.kart_no = f"**** **** **** {son4}"
        return kartlar.kart_ekstresi_isle(db, k, hesap, okunan, notlar)

    okunan = _banka_ekstresi_oku(db, k, icerik, mime, yontem)
    with KAYIT_KILIDI:  # iki ekstre aynı anda işlenirse aynı cari/hesap iki kez açılmasın
        db.expire_all()  # okuma sürerken başka işlemin açtığı cariler görülsün
        return _ekstre_kaydet(db, k, hesap, okunan)


def _banka_ekstresi_oku(db: Session, k: Kullanici, icerik: bytes, mime: str, yontem: str) -> dict:
    """Banka hesap ekstresini okur (Excel/CSV/PDF kurallarla, okunamazsa ve anahtar varsa yapay zekayla)."""
    cariler = db.scalars(select(Cari).where(Cari.sirket_id == k.sirket_id)).all()
    cari_listesi = [{"id": c.id, "unvan": c.unvan, "vkn": c.vkn, "iban": c.iban} for c in cariler]
    tablo = mime in ai.EKSTRE_TABLO_TURLERI or mime == "application/pdf"
    try:
        if tablo and yontem != "ai":
            try:
                okunan = kural.ekstre_kural_oku(icerik, mime, cari_listesi, db.get(Sirket, k.sirket_id).unvan)
            except kural.KuralHatasi:
                if yontem == "kural" or not ai.anahtar_var():
                    raise
                okunan = ai.ekstre_oku(icerik, mime, cari_listesi, GIDER_TURLERI)
        elif yontem == "kural":
            raise kural.KuralHatasi("Görsel ekstreler yapay zekasız okunamaz. Bankanızdan Excel (.xlsx) veya PDF ekstre indirin.")
        else:
            okunan = ai.ekstre_oku(icerik, mime, cari_listesi, GIDER_TURLERI)
    except (ai.OkumaHatasi, kural.KuralHatasi) as e:
        raise HTTPException(422, str(e)) from e
    return okunan


@router.post("/ekstre-yukle")
def ekstre_otomatik(dosya: UploadFile = File(...), yontem: str = "otomatik", hesap_id: int | None = None,
                    db: Session = Depends(get_db), k: Kullanici = Depends(yazabilir)):
    """Hesap seçmeden ekstre yükleme: kredi kartı ekstresi kart numarasından, hesap ekstresi dosyadaki IBAN'dan
    bulunur. Hesap açık değilse banka adı (IBAN'dan) ve IBAN'ıyla kendiliğinden açılır. IBAN yazmayan dosyada tek
    banka hesabı varsa ona, hiç yoksa yeni hesaba işlenir; birden fazla hesap varsa hangisi olduğu sorulur."""
    icerik = dosyayi_oku(dosya)
    mime = dosya_turu(dosya)
    if hesap_id:
        dosya.file.seek(0)
        return ekstre_yukle(hesap_id, dosya, yontem, db, k)
    if yontem != "ai" and kart.kart_ekstresi_mi(kart.tespit_metni(icerik, mime)):
        okunan = kartlar.oku(icerik, mime)
        hesap, yeni = kartlar.kart_hesabi(db, k.sirket_id, okunan.get("kart_son4"), okunan.get("banka"))
        sonuc = kartlar.kart_ekstresi_isle(db, k, hesap, okunan, [f"Yeni kart hesabı açıldı: {hesap.ad}."] if yeni else [])
        sonuc["yeni_hesap"] = [hesap.ad] if yeni else []
        return sonuc
    okunan = _banka_ekstresi_oku(db, k, icerik, mime, yontem)
    with KAYIT_KILIDI:
        db.expire_all()
        hesaplar = list(db.scalars(select(BankaHesabi).where(BankaHesabi.sirket_id == k.sirket_id, BankaHesabi.tur != kartlar.KART)))
        iban = okunan.get("iban")
        hesap, yeni = None, False
        if iban:
            hesap = next((b for b in hesaplar if kural.iban_uyar(b.iban, iban)), None)
            if hesap is None:
                banka = kural.iban_banka(iban)
                hesap = BankaHesabi(sirket_id=k.sirket_id, ad=f"{banka or 'Banka'} {iban[-4:]}", banka=banka, iban=iban)
                yeni = True
        elif len(hesaplar) == 1:
            hesap = hesaplar[0]
        elif not hesaplar:
            hesap, yeni = BankaHesabi(sirket_id=k.sirket_id, ad="Banka hesabı"), True
        else:
            raise HTTPException(409, "Ekstrede IBAN yazmıyor; hangi hesaba ait olduğunu seçin.")
        if yeni:
            db.add(hesap)
            db.flush()
        sonuc = _ekstre_kaydet(db, k, hesap, okunan)
        if yeni:
            sonuc["yeni_hesap"] = [hesap.ad, *sonuc.get("yeni_hesap", [])]
            sonuc["notlar"] = " ".join(x for x in (f"Yeni banka hesabı açıldı: {hesap.ad} (Banka Hesapları'ndan düzenlenebilir).",
                                                     sonuc.get("notlar")) if x)
        return sonuc


def _ekstre_kaydet(db: Session, k: Kullanici, hesap: BankaHesabi, okunan: dict) -> dict:
    cariler = db.scalars(select(Cari).where(Cari.sirket_id == k.sirket_id)).all()
    cari_listesi = [{"id": c.id, "unvan": c.unvan, "vkn": c.vkn, "iban": c.iban} for c in cariler]
    notlar = [okunan.get("notlar") or ""]
    hesaplar = list(db.scalars(select(BankaHesabi).where(BankaHesabi.sirket_id == k.sirket_id)))
    yeni_hesap: list[str] = []

    def hesap_bul_ya_ac(iban: str, banka: str | None) -> BankaHesabi:
        """IBAN'ı (maskeli de olabilir) tutan hesabı bulur; yoksa şirketin yeni banka hesabı olarak açar."""
        for b in hesaplar:
            if kural.iban_uyar(b.iban, iban):
                if "*" in (b.iban or "") and "*" not in iban:
                    b.iban = iban  # maskeli bilinen IBAN'ı tam haliyle güncelle
                    if not b.banka and kural.iban_banka(iban):
                        b.banka = kural.iban_banka(iban)
                        if b.ad == f"Banka {iban[-4:]}":
                            b.ad = f"{b.banka} {iban[-4:]}"
                return b
        b = BankaHesabi(sirket_id=k.sirket_id, ad=f"{banka or 'Banka'} {iban[-4:]}", banka=banka, iban=iban)
        db.add(b)
        db.flush()
        hesaplar.append(b)
        yeni_hesap.append(b.ad)
        return b

    iban = okunan.get("iban")
    if iban and not kural.iban_uyar(hesap.iban, iban):
        if hesap.iban and "*" not in hesap.iban or any(kural.iban_uyar(b.iban, iban) for b in hesaplar):
            # Ekstre seçilen hesaba ait değil: kendi hesabına (yoksa yeni açılan hesaba) işlenir.
            hesap = hesap_bul_ya_ac(iban, kural.iban_banka(iban) or hesap.banka)
            notlar.append(f"Ekstre IBAN'ı {iban}; {hesap.ad} hesabına işlendi.")
        else:
            hesap.iban = iban
    elif iban and "*" in (hesap.iban or ""):
        hesap.iban = iban

    cari_idleri = {c.id for c in cariler}
    yeni_cari = 0

    def cari_ac(unvan: str, tur: str, iban: str | None = None) -> int:
        nonlocal yeni_cari
        c = Cari(sirket_id=k.sirket_id, unvan=unvan, iban=iban, tur=tur)
        db.add(c)
        db.flush()
        cari_listesi.append({"id": c.id, "unvan": c.unvan, "vkn": None, "iban": c.iban})
        cari_idleri.add(c.id)
        yeni_cari += 1
        return c.id

    def karsi_cari(oneri: dict, yon: str) -> int | None:
        """Açıklamadaki karşı taraf caride varsa onu, yoksa yeni açtığı cariyi döndürür. Aynı adlı cari (ek, Türkçe
        harf ve nokta farkı yok sayılır) ikinci kez açılmaz."""
        anahtar = kural.unvan_cekirdegi(oneri["unvan"]) or kural.ad_anahtari(oneri["unvan"])
        ayni = next((c["id"] for c in cari_listesi
                     if anahtar and (kural.unvan_cekirdegi(c["unvan"]) or kural.ad_anahtari(c["unvan"])) == anahtar), None)
        return ayni or kural.cari_eslestir(oneri["unvan"], cari_listesi) or cari_ac(
            oneri["unvan"], "musteri" if yon == "giris" else "tedarikci", oneri.get("iban"))

    muhtelif_id = None

    def muhtelif_cari() -> int:
        nonlocal muhtelif_id, yeni_cari
        if muhtelif_id is None:
            yeni = not any(kural.sade(c["unvan"]) == kural.sade(MUHTELIF_CARI) for c in cari_listesi)
            muhtelif_id = muhtelif_cari_id(db, k.sirket_id)
            yeni_cari += yeni
        return muhtelif_id

    mevcut = set(db.scalars(select(Hareket.ekstre_anahtari).where(Hareket.sirket_id == k.sirket_id,
                                                                  Hareket.banka_hesap_id == hesap.id,
                                                                  Hareket.ekstre_anahtari.is_not(None))))
    ilk_ekstre = not mevcut  # hesapta ekstreden gelmiş satır yok
    kart_listesi = kartlar.kartlar(db, k.sirket_id)
    satirlar = eskiden_yeniye(okunan.get("satirlar", []))
    eklenen = atlanan = eslesen = cek_eslesen = elle_eslesen = 0
    atlananlar: list[str] = []
    islenemeyen: list[str] = []
    for s in satirlar:
        try:
            tarih = date.fromisoformat(s["tarih"])
        except (KeyError, ValueError):
            islenemeyen.append(f"Tarihi okunamadı: {s.get('aciklama') or s}")
            continue
        tutar = float(s.get("tutar") or 0)
        if tutar == 0:
            islenemeyen.append(f"{tarih:%d.%m.%Y} tutarı okunamadı: {s.get('aciklama', '')}")
            continue
        anahtar = ekstre_anahtari(hesap.id, s["tarih"], tutar, s.get("aciklama", ""), s.get("bakiye"))
        if anahtar in mevcut:
            atlanan += 1
            atlananlar.append(anahtar)
            continue
        mevcut.add(anahtar)
        yon = "giris" if tutar > 0 else "cikis"
        kart_hedef = kartlar.odeme_karti(kart_listesi, s.get("aciklama", "")) if yon == "cikis" else None
        # Karşı hesabın ekstresinden daha önce yazılmış aynı transfer varsa onu bu satırla eşleştir.
        gun = kartlar.GUN if kart_hedef else 0
        karsilik = db.scalars(select(Hareket).where(
            Hareket.sirket_id == k.sirket_id, Hareket.banka_hesap_id == hesap.id, Hareket.kaynak == "esleme",
            Hareket.ekstre_anahtari.is_(None), Hareket.tarih.between(tarih - timedelta(days=gun), tarih + timedelta(days=gun)),
            Hareket.yon == yon, func.abs(Hareket.tutar - abs(tutar)) < 0.005)).first()
        if karsilik:
            karsilik.kaynak, karsilik.ekstre_anahtari = "ekstre", anahtar
            karsilik.aciklama, karsilik.ai_okuma = s.get("aciklama"), {"bakiye": s.get("bakiye")}
            db.flush()
            eslesen += 1
            continue
        if not kart_hedef and cekler.ekstre_cekle_esle(db, k.sirket_id, hesap, tarih, yon, tutar, s.get("aciklama"),
                                                       anahtar, s.get("bakiye")):
            cek_eslesen += 1
            continue
        # Aynı para elle girilmişse (ekstre gelmeden önce) o hareket bu satıra bağlanır, ikinci kez yazılmaz.
        elle = db.scalars(select(Hareket).where(
            Hareket.sirket_id == k.sirket_id, Hareket.banka_hesap_id == hesap.id, Hareket.kaynak == "elle",
            Hareket.ekstre_anahtari.is_(None), Hareket.cek_id.is_(None), Hareket.yon == yon,
            func.abs(Hareket.tutar - abs(tutar)) < 0.005,
            Hareket.tarih.between(tarih - timedelta(days=ELLE_GUN), tarih + timedelta(days=ELLE_GUN)))
            .order_by(func.abs(func.julianday(Hareket.tarih) - func.julianday(tarih)), Hareket.id)).first()
        if elle:
            elle.ekstre_anahtari, elle.tarih = anahtar, tarih
            elle.ai_okuma = {**(elle.ai_okuma or {}), "bakiye": s.get("bakiye"), "ekstre_aciklama": s.get("aciklama")}
            db.flush()
            elle_eslesen += 1
            continue
        tur = s.get("onerilen_tur") or "diger"
        if _YON.get(tur, yon) != yon:  # yön ile tür çelişiyorsa yöne uy
            tur = "tahsilat" if yon == "giris" else "odeme"
        cari_id = s.get("onerilen_cari_id") if s.get("onerilen_cari_id") in cari_idleri else None
        if kart_hedef and tur in kartlar._ODEME_OLABILIR:
            tur, cari_id = "virman", None  # kredi kartı borcu ödemesi: bankadan karta virman
        if not cari_id and s.get("onerilen_cari") and tur in ("tahsilat", "odeme"):
            cari_id = karsi_cari(s["onerilen_cari"], yon)
        # Banka kesintileri, kredi ödemeleri ve ne olduğu anlaşılamayan banka satırları (kullanıcı kararı)
        if tur in ("banka_masrafi", "kredi_odeme") or (tur == "diger" and not cari_id):
            cari_id = muhtelif_cari()
        ek = {"bakiye": s.get("bakiye")}
        kh = s.get("karsi_hesap")
        if tur == "virman" and kart_hedef:
            ek["karsi_hesap_id"] = kart_hedef.id
        elif tur == "virman" and kh and not kural.iban_uyar(kh["iban"], hesap.iban):
            ek["karsi_hesap_id"] = hesap_bul_ya_ac(kh["iban"], kh.get("banka") or (hesap.banka if kh.get("ayni_banka") else None)).id
        gider = s.get("onerilen_gider_turu") if s.get("onerilen_gider_turu") in GIDER_TURLERI else None
        db.add(Hareket(sirket_id=k.sirket_id, durum="taslak", tarih=tarih, yon=yon, tur=tur, tutar=abs(tutar),
                       cari_id=cari_id, banka_hesap_id=hesap.id, gider_turu=gider, aciklama=s.get("aciklama"),
                       kaynak="ekstre", ekstre_anahtari=anahtar, ai_okuma=ek))
        eklenen += 1

    if ilk_ekstre and not float(hesap.acilis_bakiyesi or 0):
        hesap.acilis_ekstreden = True  # açılış bakiyesi = ilk satırın bakiyesi - ilk satırın tutarı
    ekstre_tazele(db, hesap)
    if yeni_hesap:
        notlar.append("Yeni banka hesabı açıldı: " + ", ".join(yeni_hesap))
    if elle_eslesen:
        notlar.append(f"{elle_eslesen} satır elle girdiğiniz hareketle eşleşti; ikinci kez yazılmadı.")
    if cek_eslesen:
        notlar.append(f"{cek_eslesen} satır kayıtlı çekle eşleşti; çek tahsil edildi/ödendi sayıldı, ikinci kez yazılmadı.")
    db.commit()
    return {"eklenen": eklenen, "atlanan": atlanan, "atlanan_nedeni": atlanan_nedeni(db, hesap.id, atlananlar),
            "eslesen": eslesen, "yeni_cari": yeni_cari, "hesap": hesap.ad, "yeni_hesap": yeni_hesap, "islenemeyen": islenemeyen, "notlar": " ".join(n for n in notlar if n)}
