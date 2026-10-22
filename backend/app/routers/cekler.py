"""Çek/senet takibi. Her durum değişikliği ilgili cari veya banka hareketini oluşturur."""
import re
from datetime import date, timedelta

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from fastapi.responses import FileResponse, Response
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .. import ai, cek_okuma, kural, schemas
from ..auth import aktif_kullanici, yazabilir
from ..db import get_db
from ..models import ACIK_CEK_DURUMLARI, CEK_DURUMLARI, BankaHesabi, Cari, Cek, Hareket, Kullanici, Santiye, Sirket
from ..yukleme import DosyaBuyuk, dosyayi_oku
from .faturalar import DOSYA_KLASORU, _dosya_kaydet
from .temel import sirket_kaydi

router = APIRouter(prefix="/api/cekler")

# islem -> (izin verilen mevcut durumlar, yeni durum)
ISLEMLER = {
    "alinan": {
        "ciro": ({"portfoyde"}, "ciro_edildi"),
        "tahsile_ver": ({"portfoyde", "teminatta"}, "tahsilde"),  # takasa verildi
        "teminata_ver": ({"portfoyde"}, "teminatta"),
        "portfoye_al": ({"tahsilde", "teminatta"}, "portfoyde"),  # bankadan geri alındı
        "tahsil": ({"portfoyde", "tahsilde", "teminatta"}, "tahsil_edildi"),
        "karsiliksiz": ({"portfoyde", "tahsilde", "teminatta", "ciro_edildi"}, "karsiliksiz"),
        "iade": ({"portfoyde"}, "iade"),
    },
    "verilen": {
        "ode": ({"verildi"}, "odendi"),
        "iade": ({"verildi"}, "iade"),
    },
}


def cikis(c: Cek) -> schemas.CekCikis:
    s = schemas.CekCikis.model_validate(c)
    s.durum_adi = CEK_DURUMLARI[c.yon].get(c.durum, c.durum)
    if c.durum in ("odendi", "tahsil_edildi"):
        s.durum_adi += f" ({c.banka_hesap.ad})" if c.banka_hesap else " (kasadan)"
    # Wolvox'taki gibi: vade günü (alıştan vadeye) ve kalan vade (bugünden vadeye; eksi = geçti)
    s.vade_gunu = (c.vade - c.alis_tarihi).days if c.alis_tarihi else None
    s.kalan_gun = (c.vade - date.today()).days if c.durum in ACIK_CEK_DURUMLARI else None
    s.cari_unvan = c.cari.unvan if c.cari else None
    s.ciro_cari_unvan = c.ciro_cari.unvan if c.ciro_cari else None
    s.banka_hesap_ad = c.banka_hesap.ad if c.banka_hesap else None
    return s


def _hareket(c: Cek, tarih: date, yon: str, tur: str, cari_id=None, banka_hesap_id=None, aciklama=""):
    return Hareket(sirket_id=c.sirket_id, tarih=tarih, yon=yon, tur=tur, tutar=c.tutar, cari_id=cari_id,
                   banka_hesap_id=banka_hesap_id, santiye_id=c.santiye_id, cek_id=c.id, kaynak="cek",
                   aciklama=f"{'Senet' if c.tur == 'senet' else 'Çek'} {c.cek_no or ''} vade {c.vade:%d.%m.%Y} {aciklama}".strip())


# --- Çek ile banka ekstresi eşleştirmesi --------------------------------
# Tahsil edilen/ödenen çek ekstrede ayrıca görünür; aynı para ikinci kez (cariye tahsilat olarak) yazılmaz.
EKSTRE_GUN = 10  # çekin işlem tarihi ile ekstre satırı arasında izin verilen gün farkı
_CEK_KELIMESI = re.compile(r"\b(cek|ceki|cekin|cekle|cekler|takas|takastan|senet|senedi|kts)\b")


def cek_kelimesi(aciklama: str | None) -> bool:
    return bool(_CEK_KELIMESI.search(kural.sade(aciklama or "")))


def cek_no_geciyor(cek_no: str | None, aciklama: str | None) -> bool:
    """Çek numarası ekstre açıklamasında ayrı bir sayı olarak geçiyor mu ("3001234 064 4601 ... ÇEK 067/0818*TKS ÖDEME")?
    Baştaki sıfırlar yok sayılır; 5 haneden kısa numara güvenilmez."""
    no = re.sub(r"\D", "", cek_no or "").lstrip("0")
    return len(no) >= 5 and no in {x.lstrip("0") for x in re.findall(r"\d+", aciklama or "")}


def ekstre_cekle_esle(db: Session, sirket_id: int, hesap: BankaHesabi, tarih: date, yon: str, tutar: float,
                      aciklama: str | None, anahtar: str, bakiye) -> bool:
    """Ekstre satırı bir çek tahsilatı/ödemesi mi? Öyleyse yeni hareket açılmaz:
    1) çek zaten 'tahsil edildi/ödendi' işaretlenmişse onun banka hareketi bu ekstre satırına bağlanır;
    2) tahsilde/portföyde (verilende: verildi) bekleyen aynı tutarlı çek varsa tahsil edildi/ödendi yapılır."""
    tur = "cek_tahsil" if yon == "giris" else "cek_odeme"
    h = db.scalars(select(Hareket).where(
        Hareket.sirket_id == sirket_id, Hareket.banka_hesap_id == hesap.id, Hareket.cek_id.is_not(None),
        Hareket.tur == tur, Hareket.ekstre_anahtari.is_(None), func.abs(Hareket.tutar - abs(tutar)) < 0.005,
        Hareket.tarih.between(tarih - timedelta(days=EKSTRE_GUN), tarih + timedelta(days=EKSTRE_GUN)))
        .order_by(func.abs(func.julianday(Hareket.tarih) - func.julianday(tarih)))).first()
    if h:
        h.ekstre_anahtari, h.ai_okuma = anahtar, {"bakiye": bakiye, "ekstre_aciklama": aciklama}
        h.tarih = tarih  # bankanın yazdığı gün esas
        return True
    cek_yon, durumlar = ("alinan", ("tahsilde", "portfoyde")) if yon == "giris" else ("verilen", ("verildi",))
    tutanlar = list(db.scalars(select(Cek).where(
        Cek.sirket_id == sirket_id, Cek.yon == cek_yon, Cek.durum.in_(durumlar), func.abs(Cek.tutar - abs(tutar)) < 0.005)))
    # Çek numarası açıklamada geçiyorsa o çektir (vade ve hesap bakılmaz)
    adaylar = [c for c in tutanlar if cek_no_geciyor(c.cek_no, aciklama)] or [
        c for c in tutanlar if c.banka_hesap_id in (hesap.id, None)
        and c.vade - timedelta(days=EKSTRE_GUN) <= tarih <= c.vade + timedelta(days=30)
        # Tahsile bu bankaya verilmiş çekte tutar ve vade yeter; ötekilerde açıklamada çek/takas geçmeli.
        and (c.banka_hesap_id == hesap.id and c.durum != "portfoyde" or cek_kelimesi(aciklama))]
    if not adaylar:
        return False
    c = min(adaylar, key=lambda c: (c.banka_hesap_id != hesap.id, abs((c.vade - tarih).days), c.id))
    c.banka_hesap_id, c.durum = hesap.id, "tahsil_edildi" if yon == "giris" else "odendi"
    yeni = _hareket(c, tarih, yon, tur, banka_hesap_id=hesap.id,
                    aciklama="tahsil edildi (ekstreden)" if yon == "giris" else "ödendi (ekstreden)")
    yeni.ekstre_anahtari, yeni.ai_okuma = anahtar, {"bakiye": bakiye, "ekstre_aciklama": aciklama}
    db.add(yeni)
    db.flush()
    return True


def _ekstre_satirini_cek_yap(c: Cek, e: Hareket) -> None:
    """Bu para ekstreden zaten gelmiş: o satır çekin tahsil/ödeme hareketi olur, ikinci kez yazılmaz."""
    tur, ne = ("cek_tahsil", "tahsil edildi") if e.yon == "giris" else ("cek_odeme", "ödendi")
    sablon = _hareket(c, e.tarih, e.yon, tur, banka_hesap_id=e.banka_hesap_id, aciklama=ne)
    e.tur, e.cek_id, e.cari_id, e.kaynak, e.durum = tur, c.id, None, "cek", "onayli"
    e.gider_turu, e.santiye_id = None, c.santiye_id
    e.ai_okuma = {**(e.ai_okuma or {}), "ekstre_aciklama": e.aciklama}
    e.aciklama = sablon.aciklama


def cekten_ekstreyi_esle(db: Session, c: Cek) -> bool:
    """Çek sonradan girildi/yüklendi: ekstrede çek numarasıyla geçen aynı tutarlı satır varsa çek
    ödendi/tahsil edildi sayılır, o satır çekin hareketi olur (cariye ikinci kez yazılmaz)."""
    yon, durumlar = ("giris", ("tahsilde", "portfoyde")) if c.yon == "alinan" else ("cikis", ("verildi",))
    if c.durum not in durumlar or not c.cek_no:
        return False
    db.flush()
    e = next((h for h in db.scalars(select(Hareket).where(
        Hareket.sirket_id == c.sirket_id, Hareket.banka_hesap_id.is_not(None), Hareket.cek_id.is_(None),
        Hareket.ekstre_anahtari.is_not(None), Hareket.yon == yon, Hareket.bagli_hareket_id.is_(None),
        Hareket.durum.in_(("taslak", "onayli")), func.abs(Hareket.tutar - float(c.tutar)) < 0.005).order_by(Hareket.tarih))
        if cek_no_geciyor(c.cek_no, h.aciklama)), None)
    if e is None:
        return False
    c.banka_hesap_id, c.islem_tarihi = e.banka_hesap_id, e.tarih
    c.durum = "tahsil_edildi" if c.yon == "alinan" else "odendi"
    _ekstre_satirini_cek_yap(c, e)
    return True


def cek_ekstre_satiri(db: Session, c: Cek, banka: BankaHesabi, tarih: date, yon: str) -> Hareket | None:
    """Çek elle 'tahsil edildi/ödendi' yapılırken aynı para ekstreden önceden gelmişse o satır bulunur
    (cariye ikinci tahsilat/ödeme yazılmasın diye o satır çek hareketine çevrilir)."""
    adaylar = [h for h in db.scalars(select(Hareket).where(
        Hareket.sirket_id == c.sirket_id, Hareket.banka_hesap_id == banka.id, Hareket.cek_id.is_(None),
        Hareket.ekstre_anahtari.is_not(None), Hareket.yon == yon, Hareket.bagli_hareket_id.is_(None),
        Hareket.tur.notin_(("virman", "nakit_cekim", "nakit_yatirma", "banka_masrafi", "kredi_odeme")),
        func.abs(Hareket.tutar - float(c.tutar)) < 0.005,
        Hareket.tarih.between(tarih - timedelta(days=EKSTRE_GUN), tarih + timedelta(days=EKSTRE_GUN))))
        if cek_kelimesi(h.aciklama) or h.cari_id in (None, c.cari_id)]
    return min(adaylar, key=lambda h: (not cek_kelimesi(h.aciklama), abs((h.tarih - tarih).days), h.id)) if adaylar else None


@router.get("", response_model=list[schemas.CekCikis])
def listele(yon: str | None = None, durum: str | None = None, db: Session = Depends(get_db), k: Kullanici = Depends(aktif_kullanici)):
    q = select(Cek).where(Cek.sirket_id == k.sirket_id).order_by(Cek.vade, Cek.id)
    if yon:
        q = q.where(Cek.yon == yon)
    if durum:
        q = q.where(Cek.durum.in_(durum.split(",")))
    return [cikis(c) for c in db.scalars(q)]


class TopluIslem(schemas.CekIslem):
    idler: list[int]


@router.post("/toplu-islem")
def toplu_islem(istek: TopluIslem, db: Session = Depends(get_db), k: Kullanici = Depends(yazabilir)):
    """Seçilen çeklere aynı işlem (ciro, takasa ver, teminat, ödendi/tahsil edildi...). Yapılamayanın nedeni döner."""
    sonuc = []
    for cid in istek.idler:
        c = sirket_kaydi(db, Cek, cid, k)
        try:
            with db.begin_nested():
                islem_uygula(db, c, istek, k)
            sonuc.append({"id": cid, "ok": True})
        except HTTPException as e:
            sonuc.append({"id": cid, "ok": False, "hata": f"{c.cek_no or c.id}: {e.detail}"})
    db.commit()
    return {"yapilan": sum(1 for x in sonuc if x["ok"]), "hatalar": [x["hata"] for x in sonuc if not x["ok"]]}


# Program penceresi açıkken bildirimi tarayıcı verir; pencere kapalıysa (sunucu açık) Windows bildirimini sunucu verir
SON_TARAYICI_KONTROLU = [0.0]


def vadesi_gelen_cekler(db: Session, sirket_id: int | None = None, gun: int = 0) -> list[Cek]:
    son = date.today() + timedelta(days=max(gun, 0))
    q = select(Cek).where(Cek.durum.in_(ACIK_CEK_DURUMLARI), Cek.vade <= son)
    if sirket_id is not None:
        q = q.where(Cek.sirket_id == sirket_id)
    return list(db.scalars(q.order_by(Cek.vade, Cek.id)))


@router.get("/vadesi-gelen")
def vadesi_gelen(gun: int = 0, db: Session = Depends(get_db), k: Kullanici = Depends(aktif_kullanici)):
    """Vadesi bugün gelen, geçmiş ya da 'gun' gün içinde gelecek açık çekler (ödendi/tahsil/ciro işaretlenince düşer)."""
    import time
    SON_TARAYICI_KONTROLU[0] = time.time()
    return [cikis(c) for c in vadesi_gelen_cekler(db, k.sirket_id, gun)]


@router.get("/{cek_id}", response_model=schemas.CekCikis)
def getir(cek_id: int, db: Session = Depends(get_db), k: Kullanici = Depends(aktif_kullanici)):
    return cikis(sirket_kaydi(db, Cek, cek_id, k))


def _kontrol(db: Session, veri: schemas.CekGiris, k: Kullanici):
    if veri.yon not in CEK_DURUMLARI:
        raise HTTPException(400, "Çek yönü 'alinan' veya 'verilen' olmalı.")
    if veri.tutar <= 0:
        raise HTTPException(400, "Tutar sıfırdan büyük olmalı.")
    if veri.cari_id:
        sirket_kaydi(db, Cari, veri.cari_id, k)
    if veri.santiye_id:
        sirket_kaydi(db, Santiye, veri.santiye_id, k)
    if veri.kaynak_dosya and not re.fullmatch(r"[0-9a-f]{32}\.[a-z0-9]{1,5}", veri.kaynak_dosya):
        raise HTTPException(400, "Geçersiz belge adı.")


@router.post("", response_model=schemas.CekCikis)
def ekle(veri: schemas.CekGiris, db: Session = Depends(get_db), k: Kullanici = Depends(yazabilir)):
    c = cek_olustur(db, veri, k)
    cekten_ekstreyi_esle(db, c)
    db.commit()
    return cikis(c)


def ayni_cek(db: Session, sirket_id: int, cek_no: str | None, banka: str | None, hesap_no: str | None = None,
             tutar: float | None = None, haric: int | None = None) -> Cek | None:
    """Aynı çek daha önce girilmiş mi: çek no aynı ve bankası aynı (banka yazılmamışsa hesap no ya da tutar aynı)."""
    no = cek_okuma.cek_no_anahtari(cek_no)
    if not no:
        return None
    banka_a = cek_okuma.banka_anahtari(banka)
    hesap_a = re.sub(r"\D", "", hesap_no or "").lstrip("0")
    for c in db.scalars(select(Cek).where(Cek.sirket_id == sirket_id)):
        if c.id == haric or cek_okuma.cek_no_anahtari(c.cek_no) != no:
            continue
        diger = cek_okuma.banka_anahtari(c.banka)
        if banka_a and diger:
            if banka_a == diger:
                return c
        elif hesap_a and re.sub(r"\D", "", c.hesap_no or "").lstrip("0") == hesap_a:
            return c
        elif tutar is not None and abs(float(c.tutar) - tutar) < 0.005:
            return c
    return None


def ayni_cek_hatasi(db: Session, sirket_id: int, veri, haric: int | None = None) -> None:
    if (c := ayni_cek(db, sirket_id, veri.cek_no, veri.banka, veri.hesap_no, veri.tutar, haric)) is not None:
        raise HTTPException(409, f"Bu çek zaten kayıtlı: {c.banka or ''} {c.cek_no}, vade {c.vade:%d.%m.%Y}, "
                                 f"{float(c.tutar):,.2f} TL".replace(",", "X").replace(".", ",").replace("X", "."))


def cek_olustur(db: Session, veri: schemas.CekGiris, k: Kullanici) -> Cek:
    """Çeki ve cariye işlenen ilk hareketini ekler (commit etmez). Aynı çek ikinci kez girilmez."""
    _kontrol(db, veri, k)
    ayni_cek_hatasi(db, k.sirket_id, veri)
    c = Cek(sirket_id=k.sirket_id, durum="portfoyde" if veri.yon == "alinan" else "verildi", **veri.model_dump())
    db.add(c)
    db.flush()
    if c.cari_id:
        tarih = c.alis_tarihi or date.today()
        if c.yon == "alinan":
            db.add(_hareket(c, tarih, "giris", "tahsilat", cari_id=c.cari_id, aciklama="alındı"))
        else:
            db.add(_hareket(c, tarih, "cikis", "odeme", cari_id=c.cari_id, aciklama="verildi"))
    return c


@router.put("/{cek_id}", response_model=schemas.CekCikis)
def guncelle(cek_id: int, veri: schemas.CekGiris, db: Session = Depends(get_db), k: Kullanici = Depends(yazabilir)):
    c = sirket_kaydi(db, Cek, cek_id, k)
    _kontrol(db, veri, k)
    ayni_cek_hatasi(db, k.sirket_id, veri, haric=c.id)
    if veri.yon != c.yon:
        raise HTTPException(400, "Çekin yönü değiştirilemez.")
    if c.durum not in ("portfoyde", "verildi") and (veri.tutar != float(c.tutar) or veri.cari_id != c.cari_id):
        raise HTTPException(400, "İşlem görmüş çekin tutarı veya carisi değiştirilemez.")
    for alan, deger in veri.model_dump().items():
        setattr(c, alan, deger)
    # Alış hareketini çekle uyumlu tut
    ilk = db.scalar(select(Hareket).where(Hareket.cek_id == c.id, Hareket.tur.in_(["tahsilat", "odeme"])))
    if ilk:
        ilk.tutar, ilk.cari_id, ilk.tarih = c.tutar, c.cari_id, c.alis_tarihi or ilk.tarih
    elif c.cari_id and c.durum in ("portfoyde", "verildi"):
        db.add(_hareket(c, c.alis_tarihi or date.today(), "giris" if c.yon == "alinan" else "cikis",
                        "tahsilat" if c.yon == "alinan" else "odeme", cari_id=c.cari_id))
    db.commit()
    return cikis(c)


@router.delete("/{cek_id}")
def sil(cek_id: int, db: Session = Depends(get_db), k: Kullanici = Depends(yazabilir)):
    c = sirket_kaydi(db, Cek, cek_id, k)
    db.execute(delete(Hareket).where(Hareket.cek_id == c.id))
    db.delete(c)
    db.commit()
    return {"ok": True}


@router.get("/{cek_id}/belge")
def belge(cek_id: int, db: Session = Depends(get_db), k: Kullanici = Depends(aktif_kullanici)):
    c = sirket_kaydi(db, Cek, cek_id, k)
    if not c.kaynak_dosya or not (DOSYA_KLASORU / c.kaynak_dosya).exists():
        raise HTTPException(404, "Bu çekin görseli yok.")
    return FileResponse(DOSYA_KLASORU / c.kaynak_dosya)


@router.post("/{cek_id}/islem", response_model=schemas.CekCikis)
def islem(cek_id: int, veri: schemas.CekIslem, db: Session = Depends(get_db), k: Kullanici = Depends(yazabilir)):
    c = sirket_kaydi(db, Cek, cek_id, k)
    islem_uygula(db, c, veri, k)
    db.commit()
    return cikis(c)


def islem_uygula(db: Session, c: Cek, veri: schemas.CekIslem, k: Kullanici) -> None:
    """Çekin akıbeti: ciro (cariye), takas/tahsile verme ve teminat (bankaya), ödendi/tahsil edildi (banka ya da kasa),
    karşılıksız, iade. Hareketler ilgili cariye, banka hesabına ya da kasaya işlenir (commit etmez)."""
    tanim = ISLEMLER[c.yon].get(veri.islem)
    if not tanim:
        raise HTTPException(400, "Bu çek için geçersiz işlem.")
    izinli, yeni_durum = tanim
    if c.durum not in izinli:
        raise HTTPException(400, f"Çek '{CEK_DURUMLARI[c.yon][c.durum]}' durumundayken bu işlem yapılamaz.")
    banka = sirket_kaydi(db, BankaHesabi, veri.banka_hesap_id, k) if veri.banka_hesap_id else None

    if veri.islem == "ciro":
        if not veri.cari_id:
            raise HTTPException(400, "Ciro edilecek cariyi seçin.")
        sirket_kaydi(db, Cari, veri.cari_id, k)
        c.ciro_cari_id = veri.cari_id
        db.add(_hareket(c, veri.tarih, "cikis", "cek_ciro", cari_id=veri.cari_id, aciklama="ciro edildi"))
    elif veri.islem in ("tahsile_ver", "teminata_ver"):
        if not banka:
            raise HTTPException(400, "Çekin verildiği banka hesabını seçin.")
        c.banka_hesap_id = banka.id
    elif veri.islem == "portfoye_al":
        c.banka_hesap_id = None
    elif veri.islem in ("tahsil", "ode"):
        banka = None if veri.kasa else banka or c.banka_hesap
        if not banka and not veri.kasa:
            raise HTTPException(400, "Banka hesabını ya da kasayı seçin.")
        c.banka_hesap_id = banka.id if banka else None
        yon, tur, ne = ("giris", "cek_tahsil", "tahsil edildi") if veri.islem == "tahsil" else ("cikis", "cek_odeme", "ödendi")
        if banka and (e := cek_ekstre_satiri(db, c, banka, veri.tarih, yon)):
            _ekstre_satirini_cek_yap(c, e)
        else:
            # Kasadan: banka hesabı boş hareket Nakit Kasa'dır
            db.add(_hareket(c, veri.tarih, yon, tur, banka_hesap_id=banka.id if banka else None,
                            aciklama=ne + ("" if banka else " (kasadan)")))
    elif veri.islem == "karsiliksiz":
        # Çeki veren cari tekrar borçlanır; ciro edilmişse ciro edilen carinin alacağı geri döner.
        if c.cari_id:
            db.add(_hareket(c, veri.tarih, "cikis", "cek_karsiliksiz", cari_id=c.cari_id, aciklama="karşılıksız"))
        if c.ciro_cari_id:
            db.add(_hareket(c, veri.tarih, "giris", "cek_karsiliksiz", cari_id=c.ciro_cari_id, aciklama="karşılıksız, ciro geri döndü"))
    elif veri.islem == "iade" and c.cari_id:
        if c.yon == "alinan":
            db.add(_hareket(c, veri.tarih, "cikis", "diger", cari_id=c.cari_id, aciklama="iade edildi"))
        else:
            db.add(_hareket(c, veri.tarih, "giris", "diger", cari_id=c.cari_id, aciklama="iade alındı"))
    c.durum = yeni_durum
    c.islem_tarihi = None if yeni_durum in ("portfoyde", "verildi") else veri.tarih


def _cari_oner(db: Session, k: Kullanici, unvan: str | None, vkn: str | None) -> Cari | None:
    """Keşideci caride var mı: VKN/TCKN ya da (ekleri yok sayılarak) aynı ad."""
    if vkn and (c := db.scalar(select(Cari).where(Cari.sirket_id == k.sirket_id, Cari.vkn == vkn))):
        return c
    if unvan:
        from .temel import ayni_adli_cari
        return ayni_adli_cari(db, k.sirket_id, unvan, vkn)
    return None


def _okunanlari_hazirla(db: Session, k: Kullanici, okunanlar: list[dict], kaynak_dosya: str | None, dosya_adi: str,
                        cekten: bool = True) -> list[dict]:
    satirlar = []
    # Aynı hesaptan daha önce kaydedilmiş (kullanıcının kontrol ettiği) çek varsa keşideci, banka ve şube oradan alınır:
    # karekod ve MICR satırı hesabı kesin verir, basılı ad ise çoğu zaman eksik okunur
    son8 = lambda h: re.sub(r"\D", "", h or "")[-8:] or None  # noqa: E731
    onceki: dict[str, Cek] = {}
    for c in db.scalars(select(Cek).where(Cek.sirket_id == k.sirket_id, Cek.hesap_no.is_not(None)).order_by(Cek.id)):
        if son8(c.hesap_no):
            onceki[son8(c.hesap_no)] = c
    sirket = db.get(Sirket, k.sirket_id)
    for o in okunanlar:
        cek_okuma.lehtari_belirle(o, sirket.unvan if sirket else None)
        o.pop("_tani", None)
        o.pop("_bant", None)
        if (eski := onceki.get(son8(o.get("hesap_no")))) is not None and "hesap_no" not in (o.get("belirsiz") or []):
            for alan in ("kesideci", "banka", "sube"):
                if getattr(eski, alan):
                    o[alan] = getattr(eski, alan)
                    o["belirsiz"] = [b for b in (o.get("belirsiz") or []) if b != alan]
            if len(re.sub(r"\D", "", o.get("hesap_no") or "")) > 16 and eski.hesap_no:
                o["hesap_no"] = eski.hesap_no  # IBAN okunduysa kayıtlı hesap no yazılır
        # Çekten okunan ad ve VKN çeki yazan firmanındır. Cari kayıtta bundan kurulur (toplu_ekle); Excel şablonunda Cari
        # sütunu yazılmışsa o cari kullanılır
        vkn = o.get("vkn")
        if vkn and not re.fullmatch(r"\d{10,11}", vkn):
            vkn = None
        r = {**o, "kesideci_vkn": o.get("kesideci_vkn") or vkn, "kaynak_dosya": kaynak_dosya, "dosya_adi": dosya_adi,
             "cari_id": None, "cari_unvan": None, "cari_vkn": None}
        if o.get("cari_unvan") or o.get("cari_vkn"):
            cari = _cari_oner(db, k, o.get("cari_unvan"), o.get("cari_vkn"))
            r.update(cari_id=cari.id if cari else None, cari_unvan=cari.unvan if cari else o.get("cari_unvan"),
                     cari_vkn=o.get("cari_vkn"))
            if not cari:  # caride yok: kaydedince yeni cari açılır; kullanıcı görsün diye kırmızı
                r["belirsiz"] = list(dict.fromkeys([*(o.get("belirsiz") or []), "cari_unvan"]))
        if (ayni := ayni_cek(db, k.sirket_id, o.get("cek_no"), o.get("banka"), o.get("hesap_no"), o.get("tutar"))) is not None:
            r["sorun"] = f"Bu çek zaten kayıtlı (vade {ayni.vade:%d.%m.%Y})."
        satirlar.append(r)
    return satirlar


def _dosya_sakla(icerik: bytes, ad: str | None) -> str:
    uzanti = (ad or "").rsplit(".", 1)[-1].lower()[:5] or "bin"
    if not re.fullmatch(r"[a-z0-9]{1,5}", uzanti):
        uzanti = "bin"
    return _dosya_kaydet(icerik, uzanti)


YZ_ANAHTAR_YOK = ("Yapay zekayla okuma için Claude API anahtarı gerekir. Program klasöründeki .env dosyasına "
                  "ANTHROPIC_API_KEY=anahtarınız satırını yazıp programı baslat.bat ile yeniden açın. "
                  "Anahtar olmadan da çekler normal okunur.")


@router.post("/oku-toplu")
async def oku_toplu(dosyalar: list[UploadFile] = File(...), yapay_zeka: bool = False,
                    db: Session = Depends(get_db), k: Kullanici = Depends(yazabilir)):
    """Çek/senet fotoğrafları ya da taranmış PDF'ler (bir sayfada birden çok çek olabilir), yapay zekasız okunur.
    yapay_zeka: isteğe bağlı; kural okumasının boş ya da kırmızı bıraktığı alanlar yapay zekayla doldurulur
    (Claude API anahtarı gerekir). Kaydetmez: okunanlar toplu giriş ekranına gelir, emin olunamayan alanlar
    'belirsiz' döner."""
    from starlette.concurrency import run_in_threadpool
    if yapay_zeka and not ai.anahtar_var():
        raise HTTPException(400, YZ_ANAHTAR_YOK)
    satirlar, okunamayan = [], []
    for d in dosyalar:
        try:
            icerik = dosyayi_oku(d)
        except DosyaBuyuk as e:
            okunamayan.append(e.detail)
            continue
        try:
            okunanlar = await run_in_threadpool(cek_okuma.dosyadan_oku, icerik, d.filename or "", d.content_type or "")
        except kural.KuralHatasi as e:
            if not yapay_zeka:
                okunamayan.append(f"{d.filename}: {e}")
                continue
            okunanlar = []
        if yapay_zeka:
            try:
                okunanlar = await run_in_threadpool(cek_okuma.yapay_zekayla_eksikleri_oku, icerik, d.filename or "", okunanlar)
            except (ai.OkumaHatasi, kural.KuralHatasi) as e:
                okunamayan.append(f"{d.filename}: yapay zekayla okunamadı ({e}).")
        if not okunanlar:
            okunamayan.append(f"{d.filename}: çek bulunamadı. Sayfada çek formu (karekod, çek seri no) görünmüyor; çekin kendisini tarayın ya da daha net bir fotoğraf deneyin.")
            continue
        satirlar += _okunanlari_hazirla(db, k, okunanlar, _dosya_sakla(icerik, d.filename), d.filename or "")
    from ..surum import ek_paketler
    durum = ek_paketler()
    eksik = [m for var, m in ((durum["karekod"], "Karekod okuma paketi kurulu değil: çek no, banka ve hesap no karekoddan okunamıyor."),
                              (durum["el_yazisi"], "El yazısı okuma paketi kurulu değil: vade ve tutar okunamıyor.")) if not var]
    return {"satirlar": satirlar, "okunamayan": okunamayan, "eksik": eksik}


@router.post("/okuma-raporu")
async def okuma_raporu(dosyalar: list[UploadFile] = File(...), k: Kullanici = Depends(yazabilir)):
    """İsteğe bağlı okuma raporu (ZIP): çek neden boş ya da kırmızı okundu sorusunun cevabı (okuma ayrıntısı)."""
    from starlette.concurrency import run_in_threadpool
    icerikler = [(d.filename or "cek", dosyayi_oku(d), d.content_type or "") for d in dosyalar]
    zip_ = await run_in_threadpool(cek_okuma.okuma_raporu, icerikler)
    return Response(zip_, media_type="application/zip",
                    headers={"Content-Disposition": 'attachment; filename="cek-okuma-raporu.zip"'})


class TopluCekSatiri(schemas.CekGiris):
    akibet: schemas.CekIslem | None = None  # kaydedilirken uygulanacak işlem (ciro, takas, teminat, ödendi...)
    tutar: float | None = None
    vade: date | None = None
    cari_unvan: str | None = None
    cari_vkn: str | None = None


class TopluCek(BaseModel):
    satirlar: list[TopluCekSatiri]


@router.post("/toplu")
def toplu_ekle(istek: TopluCek, db: Session = Depends(get_db), k: Kullanici = Depends(yazabilir)):
    """Toplu giriş ekranındaki satırları kaydeder. Her satır ayrı denenir: kaydedilemeyenin nedeni döner, ötekiler kaydedilir.
    Cari verilmemişse alınan çekte çeki yazan firma, verilen çekte lehtar (çekin yazıldığı firma) cari olur: VKN ya da
    aynı adla caride varsa ona işlenir, yoksa açılır (faturadaki cari kuralı). Ciro edilen firma akıbette seçilir."""
    from .temel import kendi_vkn_reddet
    sirket = db.get(Sirket, k.sirket_id)
    sonuc, yeni_cari = [], 0
    for r in istek.satirlar:
        try:
            if not r.tutar or r.tutar <= 0:
                raise HTTPException(400, "Tutar yok.")
            if not r.vade:
                raise HTTPException(400, "Vade yok.")
            with db.begin_nested():
                cari_id = r.cari_id
                if not cari_id and not (r.cari_unvan or r.cari_vkn):
                    if r.yon == "alinan":
                        r.cari_unvan, r.cari_vkn = r.kesideci, r.kesideci_vkn
                    elif r.lehtar and not kural.kendi_unvani_mi(r.lehtar, sirket.unvan):
                        r.cari_unvan = r.lehtar
                if not cari_id and (r.cari_unvan or r.cari_vkn):
                    vkn = re.sub(r"\D", "", r.cari_vkn or "") or None
                    if vkn:
                        kendi_vkn_reddet(db, k, vkn)
                    if not vkn and kural.kendi_unvani_mi(r.cari_unvan, sirket.unvan):
                        raise HTTPException(400, "Kendi firmanız cari olamaz.")
                    cari = _cari_oner(db, k, r.cari_unvan, vkn)
                    if cari is None:
                        if not r.cari_unvan:
                            raise HTTPException(400, "Cari adı yok.")
                        cari = Cari(sirket_id=k.sirket_id, unvan=r.cari_unvan.strip(), vkn=vkn,
                                    tur="musteri" if r.yon == "alinan" else "tedarikci")
                        db.add(cari)
                        db.flush()
                        yeni_cari += 1
                    elif vkn and not cari.vkn:
                        cari.vkn = vkn
                    cari_id = cari.id
                veri = schemas.CekGiris(**{**r.model_dump(exclude={"cari_unvan", "cari_vkn", "akibet"}), "cari_id": cari_id})
                c = cek_olustur(db, veri, k)
                if r.akibet and r.akibet.islem:
                    db.flush()
                    islem_uygula(db, c, r.akibet, k)
                else:
                    cekten_ekstreyi_esle(db, c)
            sonuc.append({"ok": True, "id": c.id})
        except HTTPException as e:
            sonuc.append({"ok": False, "hata": e.detail})
    db.commit()
    return {"sonuc": sonuc, "kaydedilen": sum(1 for x in sonuc if x["ok"]), "yeni_cari": yeni_cari}


@router.post("/oku")
async def oku(dosya: UploadFile = File(...), db: Session = Depends(get_db), k: Kullanici = Depends(yazabilir)):
    """Tek çek formu için: görsel yapay zekasız okunur (yapay zeka anahtarı varsa ve yerel okuma çek bulamazsa o denenir).
    Sonuç forma doldurulur (kaydetmez)."""
    from starlette.concurrency import run_in_threadpool
    icerik = dosyayi_oku(dosya)
    try:
        okunanlar = await run_in_threadpool(cek_okuma.dosyadan_oku, icerik, dosya.filename or "", dosya.content_type or "")
    except kural.KuralHatasi as e:
        okunanlar, hata = [], str(e)
    else:
        hata = "Çek bulunamadı (tarih ve tutar okunamadı). Daha net bir fotoğraf deneyin."
    if not okunanlar:
        if not ai.anahtar_var():
            raise HTTPException(422, hata)
        try:
            okunan = ai.cek_oku(icerik, dosya.content_type or "")
        except ai.OkumaHatasi as e:
            raise HTTPException(422, str(e)) from e
        return {**okunan, "kaynak_dosya": _dosya_sakla(icerik, dosya.filename)}
    r = _okunanlari_hazirla(db, k, okunanlar[:1], _dosya_sakla(icerik, dosya.filename), dosya.filename or "")[0]
    if len(okunanlar) > 1:
        r["notlar"] = f"Dosyada {len(okunanlar)} çek var; hepsi için Toplu Çek Girişi'ni kullanın."
    return r
