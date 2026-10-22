"""Fatura işlemleri: elle giriş, yapay zeka ile okuma, onay."""
import hashlib
import re
import threading
from datetime import date

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .. import ai, karekod, kural, ocr, schemas, tani
from ..auth import aktif_kullanici, yazabilir
from ..db import VERI_KLASORU, get_db
from ..models import GIDER_TURLERI, Cari, Depo, Fatura, FaturaKalem, Kullanici, RedFatura, Santiye, Sirket
from ..yukleme import dosyayi_oku
from .temel import sirket_kaydi

router = APIRouter(prefix="/api/faturalar")

DOSYA_KLASORU = VERI_KLASORU / "belgeler"
DOSYA_KLASORU.mkdir(parents=True, exist_ok=True)
# Toplu yüklemede dosyalar aynı anda okunur ama kayıt kısmı sırayla yapılır: aynı firmanın iki faturası aynı anda
# gelince firma iki kez cari açılmaz, veritabanı "kilitli" hatası vermez.
KAYIT_KILIDI = threading.Lock()


def cikis(f: Fatura) -> schemas.FaturaCikis:
    c = schemas.FaturaCikis.model_validate(f)
    c.cari_unvan = f.cari.unvan if f.cari else None
    c.zaten_var = getattr(f, "_zaten_var", False)
    # Kalemlerde farklı şantiye seçildiyse hepsi listelenir.
    adlar = [x.ad for x in dict.fromkeys(kl.santiye or f.santiye for kl in f.kalemler) if x] if f.kalemler else []
    c.santiye_ad = ", ".join(adlar) if adlar else (f.santiye.ad if f.santiye else None)
    return c


def kalemleri_yaz(f: Fatura, kalemler: list[schemas.KalemGiris]):
    """Toplamları kalemlerden hesaplar. Kalemlerde tevkifat oranı varsa faturanın tevkifatı satırların toplamıdır;
    hiçbir satırda oran yoksa (eski kayıt, Excel'den gelen) faturaya yazılan tevkifat kalır."""
    f.kalemler.clear()
    ara = kdv = tevk = stop = 0.0
    oranli = stopajli = False
    for k in kalemler:
        brut = round(k.miktar * k.birim_fiyat, 2)
        isk_t = float(k.iskonto_tutari or 0)
        if not isk_t and k.iskonto_orani:
            isk_t = round(brut * float(k.iskonto_orani) / 100, 2)
        tutar = k.tutar if k.tutar is not None else round(brut - isk_t, 2)
        isk_o = float(k.iskonto_orani or 0) or (round(isk_t / brut * 100, 2) if isk_t and brut else 0)
        pay = max(0.0, min(float(k.tevkifat_orani or 0), 10.0))
        f.kalemler.append(FaturaKalem(
            aciklama=k.aciklama, miktar=k.miktar, birim=k.birim,
            birim_fiyat=k.birim_fiyat, kdv_orani=k.kdv_orani, tutar=tutar, santiye_id=k.santiye_id, depo_id=k.depo_id,
            tevkifat_orani=pay, tevkifat_kodu=(k.tevkifat_kodu or None) if pay else None, kdv_tutari=k.kdv_tutari,
            iskonto_orani=isk_o, iskonto_tutari=isk_t, stopaj_orani=max(0.0, min(float(k.stopaj_orani or 0), 100.0)),
        ))
        ara += tutar
        kdv += f.kalemler[-1].kdv
        if pay:
            oranli = True
            tevk += kural.tevkifat_tutari(tutar, k.kdv_orani, pay, k.kdv_tutari)
        if k.stopaj_orani:
            stopajli = True
            stop += kural.stopaj_tutari(tutar, k.stopaj_orani)
    f.ara_toplam = round(ara, 2)
    f.kdv_toplam = round(kdv, 2)
    if oranli:
        f.tevkifat = round(tevk, 2)
    if stopajli:
        f.stopaj = round(stop, 2)
    f.genel_toplam = round(ara + kdv - (f.tevkifat or 0) - float(f.stopaj or 0) + (f.diger_vergiler or 0) + float(f.yuvarlama or 0), 2)


def kalem_giris(kl: dict, santiye_id: int | None = None, kdv_varsayilan: float = 0) -> schemas.KalemGiris:
    """Okunan (PDF/XML) kalemi standart kalem sütunlarına çevirir."""
    return schemas.KalemGiris(
        aciklama=kl.get("aciklama") or "-", miktar=kl.get("miktar") or 1, birim=kl.get("birim"),
        birim_fiyat=kl.get("birim_fiyat") or 0, kdv_orani=kl["kdv_orani"] if kl.get("kdv_orani") is not None else kdv_varsayilan,
        tutar=kl.get("tutar"), santiye_id=santiye_id, tevkifat_orani=kl.get("tevkifat_orani") or 0,
        tevkifat_kodu=kl.get("tevkifat_kodu"), kdv_tutari=kl.get("kdv_tutari"), stopaj_orani=kl.get("stopaj_orani") or 0,
        iskonto_orani=kl.get("iskonto_orani") or 0, iskonto_tutari=kl.get("iskonto_tutari") or 0)


def toplam_farki(f: Fatura, okunan: dict) -> list[str]:
    """Kalemlerden hesaplanan KDV ve ödenecek tutar faturada yazanı tutmuyorsa uyarı (kırmızı gösterilir)."""
    uyari = []
    if okunan.get("kdv_toplam") is not None and abs(float(f.kdv_toplam) - okunan["kdv_toplam"]) > 0.05:
        uyari.append(f"Hesaplanan KDV ({f.kdv_toplam:.2f}) faturadaki KDV'den ({okunan['kdv_toplam']:.2f}) farklı.")
    if okunan.get("genel_toplam") is not None and abs(float(f.genel_toplam) - okunan["genel_toplam"]) > 0.05:
        uyari.append(f"Hesaplanan toplam ({f.genel_toplam:.2f}) faturadaki toplamdan ({okunan['genel_toplam']:.2f}) farklı.")
    return uyari


def mukerrer_mi(db: Session, f: Fatura) -> bool:
    if not (f.fatura_no and f.cari_id):
        return False
    return bool(db.scalar(select(Fatura.id).where(
        Fatura.sirket_id == f.sirket_id, Fatura.yon == f.yon, Fatura.cari_id == f.cari_id,
        Fatura.fatura_no == f.fatura_no, Fatura.durum == "onayli", Fatura.id != f.id,
    )))


@router.get("", response_model=list[schemas.FaturaCikis])
def listele(
    yon: str | None = None, durum: str | None = None, cari_id: int | None = None,
    santiye_id: int | None = None, baslangic: date | None = None, bitis: date | None = None,
    db: Session = Depends(get_db), k: Kullanici = Depends(aktif_kullanici),
):
    q = select(Fatura).where(Fatura.sirket_id == k.sirket_id)
    for alan, deger in [(Fatura.yon, yon), (Fatura.durum, durum), (Fatura.cari_id, cari_id)]:
        if deger is not None:
            q = q.where(alan == deger)
    if santiye_id is not None:  # faturanın ya da herhangi bir kaleminin şantiyesi
        q = q.where(or_(Fatura.santiye_id == santiye_id, Fatura.kalemler.any(FaturaKalem.santiye_id == santiye_id)))
    if baslangic:
        q = q.where(Fatura.tarih >= baslangic)
    if bitis:
        q = q.where(Fatura.tarih <= bitis)
    q = q.order_by(Fatura.tarih.desc().nulls_first(), Fatura.id.desc())
    return [cikis(f) for f in db.scalars(q).all()]


@router.get("/sonraki-no")
def sonraki_no(yon: str = "giden", db: Session = Depends(get_db), k: Kullanici = Depends(aktif_kullanici)):
    """Yeni faturaya önerilen numara: GİB biçimi SERİ + YIL + 9 haneli sıra (ör. AFS2026000000012).
    Seri firma bilgilerindeki fatura serisidir; yoksa bu yönde kullanılan son serinin devamı alınır."""
    yil = date.today().year
    seri = db.get(Sirket, k.sirket_id).fatura_seri if yon == "giden" else None
    en_buyuk, son_seri = 0, None
    for no in db.scalars(select(Fatura.fatura_no).where(Fatura.sirket_id == k.sirket_id, Fatura.yon == yon,
                                                         Fatura.fatura_no.is_not(None)).order_by(Fatura.id)):
        m = re.fullmatch(r"([A-Z0-9]{3})(\d{4})(\d{9})", no or "")
        if m and int(m.group(2)) == yil and (seri is None or m.group(1) == seri):
            son_seri = m.group(1)
            en_buyuk = max(en_buyuk, int(m.group(3)))
    seri = seri or son_seri
    return {"fatura_no": f"{seri}{yil}{en_buyuk + 1:09d}" if seri else None}


@router.get("/tcmb-kuru")
def tcmb_kuru(para: str, tarih: date, k: Kullanici = Depends(aktif_kullanici)):
    """Dövizli faturada kur yazmıyorsa fatura tarihindeki TCMB döviz alış kuru (internet gerekir)."""
    from .. import tcmb
    if (para or "TRY").upper()[:3] in ("TRY", "TL"):
        raise HTTPException(400, "TL faturada kur gerekmez.")
    try:
        deger, gun = tcmb.kur(para, tarih)
    except tcmb.KurAlinamadi as e:
        raise HTTPException(503, str(e)) from e
    return {"kur": deger, "liste_tarihi": gun.isoformat(), "aciklama": f"TCMB döviz alış kuru ({gun.strftime('%d.%m.%Y')})"}


def fatura_sorunlari(f: Fatura) -> list[str]:
    """Onay ekranında kırmızı/sarı görünen nedenler (arayüzdeki sorunu() ile aynı kurallar)."""
    okuma = f.ai_okuma or {}
    nedenler = []
    if not f.cari_id and not (okuma.get("satici" if f.yon == "gelen" else "alici") or {}).get("unvan"):
        nedenler.append("Firma okunamadı.")
    if not f.kalemler or okuma.get("kalemler_okunamadi"):
        nedenler.append("Kalemler tek tek okunamadı.")
    if not float(f.genel_toplam or 0):
        nedenler.append("Tutar okunamadı.")
    if (f.para_birimi or "TRY") not in ("TRY", "TL") and not float(f.kur or 0):
        nedenler.append(f"Fatura {f.para_birimi} cinsinden; kuru girin.")
    nedenler += toplam_farki(f, okuma)
    eski = [u for u in okuma.get("uyarilar") or [] if u and not re.search(r"okundu\.?$|yeni cari açıldı", u)]
    nedenler += [u for u in eski if not u.startswith(("Hesaplanan KDV (", "Hesaplanan toplam ("))]  # güncel hali yukarıda
    return list(dict.fromkeys(nedenler))


@router.get("/hatali-disa-aktar")
def hatali_disa_aktar(yon: str = "gelen", db: Session = Depends(get_db), k: Kullanici = Depends(aktif_kullanici)):
    """Onay bekleyen hatalı/uyarılı faturaların belgeleri ve nedenleri tek ZIP: toplu olarak incelemeye göndermek için."""
    import csv
    import io
    import zipfile
    faturalar = db.scalars(select(Fatura).where(Fatura.sirket_id == k.sirket_id, Fatura.yon == yon,
                                                Fatura.durum == "taslak").order_by(Fatura.id)).all()
    tampon, satirlar = io.BytesIO(), []
    with zipfile.ZipFile(tampon, "w", zipfile.ZIP_DEFLATED) as z:
        for f in faturalar:
            nedenler = fatura_sorunlari(f)
            if not nedenler:
                continue
            ad = re.sub(r"[^\w.-]", "_", f.fatura_no or f"fatura-{f.id}")
            dosyalar = []
            for kaynak in dict.fromkeys(x for x in (f.kaynak_dosya, f.xml_dosya) if x):
                yol = DOSYA_KLASORU / kaynak
                if yol.exists():
                    dosyalar.append(f"{ad}.{kaynak.rsplit('.', 1)[-1]}")
                    z.write(yol, dosyalar[-1])
            firma = f.cari.unvan if f.cari else ((f.ai_okuma or {}).get("satici") or {}).get("unvan")
            satirlar.append([", ".join(dosyalar) or "(belge yok)", f.fatura_no or "", firma or "", f"{float(f.genel_toplam or 0):.2f}",
                             " ".join(nedenler)])
        metin = io.StringIO()
        csv.writer(metin, delimiter=";").writerows([["Dosya", "Fatura No", "Firma", "Genel Toplam", "Neden"], *satirlar])
        z.writestr("nedenler.csv", "\ufeff" + metin.getvalue())
    if not satirlar:
        raise HTTPException(404, "Hatalı ya da uyarılı fatura yok.")
    from fastapi.responses import Response
    return Response(tampon.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": 'attachment; filename="hatali-faturalar.zip"'})


def _taslaklar(db: Session, k: Kullanici, yon: str | None):
    q = select(Fatura).where(Fatura.sirket_id == k.sirket_id, Fatura.durum == "taslak")
    if yon:
        q = q.where(Fatura.yon == yon)
    return db.scalars(q.order_by(Fatura.tarih.nulls_first(), Fatura.id)).all()


@router.get("/okuma-raporu/ozet")
def okuma_raporu_ozet(yon: str | None = None, db: Session = Depends(get_db), k: Kullanici = Depends(aktif_kullanici)):
    """Onay bekleyen faturaların kaçı sorunsuz, kaçı hangi nedenle sorunlu; okunamayan dosya sayısı."""
    return tani.ozet(_taslaklar(db, k, yon), db.get(Sirket, k.sirket_id))


@router.get("/okuma-raporu")
def okuma_raporu(yon: str | None = None, db: Session = Depends(get_db), k: Kullanici = Depends(aktif_kullanici)):
    """Okuma Hata Raporu (ZIP): Excel (her sorun bir satır), belgeler, PDF metni ve tablo dökümü."""
    from fastapi.responses import Response
    veri = tani.rapor_zip(_taslaklar(db, k, yon), db.get(Sirket, k.sirket_id), DOSYA_KLASORU)
    return Response(veri, media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="okuma-hata-raporu-{date.today():%Y%m%d}.zip"'})


@router.delete("/okuma-raporu/okunamayanlar")
def okunamayanlari_temizle(db: Session = Depends(get_db), k: Kullanici = Depends(yazabilir)):
    return {"silinen": tani.okunamayanlari_temizle(k.sirket_id)}


@router.get("/{fatura_id}", response_model=schemas.FaturaCikis)
def getir(fatura_id: int, db: Session = Depends(get_db), k: Kullanici = Depends(aktif_kullanici)):
    return cikis(sirket_kaydi(db, Fatura, fatura_id, k))


@router.post("", response_model=schemas.FaturaCikis)
def ekle(veri: schemas.FaturaGiris, db: Session = Depends(get_db), k: Kullanici = Depends(yazabilir)):
    f = Fatura(sirket_id=k.sirket_id)
    _doldur(db, f, veri, k)
    db.add(f)
    db.commit()
    return cikis(f)


@router.put("/{fatura_id}", response_model=schemas.FaturaCikis)
def guncelle(fatura_id: int, veri: schemas.FaturaGiris, db: Session = Depends(get_db), k: Kullanici = Depends(yazabilir)):
    f = sirket_kaydi(db, Fatura, fatura_id, k)
    if f.durum == "iptal":
        raise HTTPException(400, "İptal edilmiş fatura değiştirilemez; önce iptali geri alın.")
    _doldur(db, f, veri, k)
    db.commit()
    return cikis(f)


def _doldur(db: Session, f: Fatura, veri: schemas.FaturaGiris, k: Kullanici):
    if veri.cari_id:
        c = sirket_kaydi(db, Cari, veri.cari_id, k)
        if kendi_firmamiz_mi(db, c, k.sirket_id):
            raise HTTPException(400, "Kendi firmanız faturanın carisi olamaz; faturadaki karşı firmayı seçin.")
    for sid in {veri.santiye_id, *(kl.santiye_id for kl in veri.kalemler)} - {None}:
        sirket_kaydi(db, Santiye, sid, k)
    for did in {kl.depo_id for kl in veri.kalemler} - {None}:
        sirket_kaydi(db, Depo, did, k)
    for alan, deger in veri.model_dump(exclude={"kalemler"}).items():
        setattr(f, alan, deger)
    f.para_birimi = (f.para_birimi or "TRY").strip().upper()[:3] or "TRY"
    if f.para_birimi == "TL":
        f.para_birimi = "TRY"
    if f.para_birimi == "TRY" or not (f.kur and float(f.kur) > 0):
        f.kur = None
    f.fatura_tipi = (f.fatura_tipi or "").strip().upper() or None
    kalemleri_yaz(f, veri.kalemler)


@router.delete("/{fatura_id}")
def sil(fatura_id: int, db: Session = Depends(get_db), k: Kullanici = Depends(yazabilir)):
    db.delete(sirket_kaydi(db, Fatura, fatura_id, k))
    db.commit()
    return {"ok": True}


@router.post("/{fatura_id}/onayla", response_model=schemas.FaturaCikis)
def onayla(fatura_id: int, db: Session = Depends(get_db), k: Kullanici = Depends(yazabilir)):
    f = sirket_kaydi(db, Fatura, fatura_id, k)
    if not f.cari_id:
        satici = (f.ai_okuma or {}).get("satici" if f.yon == "gelen" else "alici") or {}
        c, _ = cari_bul_ya_ac(db, k, satici, "tedarikci" if f.yon == "gelen" else "musteri")
        if not c:
            raise HTTPException(400, "Onaylamak için bir cari seçin.")
        f.cari_id = c.id
    elif kendi_firmamiz_mi(db, f.cari, k.sirket_id):
        raise HTTPException(400, "Kendi firmanız faturanın carisi olamaz; faturadaki karşı firmayı seçin.")
    if not f.kalemler:
        raise HTTPException(400, "Faturada kalem yok.")
    if (f.para_birimi or "TRY") not in ("TRY", "TL") and not float(f.kur or 0):
        raise HTTPException(400, f"Fatura {f.para_birimi} cinsinden; onaylamak için kuru (1 {f.para_birimi} kaç TL) girin.")
    if mukerrer_mi(db, f):
        raise HTTPException(409, f"{f.fatura_no} numaralı fatura bu cari için zaten kayıtlı.")
    f.durum = "onayli"
    db.commit()
    db.refresh(f)
    return cikis(f)


class TopluOnay(BaseModel):
    idler: list[int]


@router.post("/toplu-onayla")
def toplu_onayla(istek: TopluOnay, db: Session = Depends(get_db), k: Kullanici = Depends(yazabilir)):
    """Seçilen taslak faturaları onaylar; onaylanamayanları nedeniyle döndürür."""
    onaylanan, hatalar = 0, []
    for fid in istek.idler:
        try:
            onayla(fid, db, k)
            onaylanan += 1
        except HTTPException as e:
            db.rollback()
            hatalar.append(f"#{fid}: {e.detail}")
    return {"onaylanan": onaylanan, "hatalar": hatalar}


class TopluIslem(BaseModel):
    idler: list[int]
    santiye_id: int | None = None
    gider_turu: str | None = None
    depo_id: int | None = None  # verilirse bütün kalemler bu depoya ayrılır; 0 = depoyu kaldır (şantiyenin kendisi)


@router.post("/toplu-guncelle")
def toplu_guncelle(istek: TopluIslem, db: Session = Depends(get_db), k: Kullanici = Depends(yazabilir)):
    """Seçilen faturalara (onaylı olanlar da) şantiye ve/veya gider türü atar (verilmeyen alan değişmez)."""
    if istek.santiye_id:
        sirket_kaydi(db, Santiye, istek.santiye_id, k)
    if istek.gider_turu and istek.gider_turu not in GIDER_TURLERI:
        raise HTTPException(422, "Geçersiz gider türü.")
    depo = sirket_kaydi(db, Depo, istek.depo_id, k) if istek.depo_id else None
    n = 0
    for fid in istek.idler:
        f = sirket_kaydi(db, Fatura, fid, k)
        if istek.santiye_id:
            f.santiye_id = istek.santiye_id
            # Toplu atama faturanın tüm kalemlerine geçer: kalemlerdeki ayrı şantiye seçimi kalkar, kalemler fatura şantiyesini alır
            for kl in f.kalemler:
                kl.santiye_id = None
        if istek.gider_turu:
            f.gider_turu = istek.gider_turu
        if istek.depo_id is not None:
            for kl in f.kalemler:
                kl.depo_id = depo.id if depo else None
            # Depo bir şantiyeye bağlıysa şantiyesi boş fatura o şantiyeyi alır
            if depo and depo.santiye_id and not f.santiye_id and not any(kl.santiye_id for kl in f.kalemler):
                f.santiye_id = depo.santiye_id
        n += 1
    db.commit()
    return {"guncellenen": n}


class TopluSil(BaseModel):
    idler: list[int]
    onaylilar_dahil: bool = False  # ekranda onaylı faturalar için ayrıca onay alındı


@router.post("/toplu-sil")
def toplu_sil(istek: TopluSil, db: Session = Depends(get_db), k: Kullanici = Depends(yazabilir)):
    """Seçilen faturaları siler. Onaylı faturalar yalnız onaylilar_dahil ile silinir. Cari bakiyesi, şantiye, KDV ve
    tevkifat raporları onaylı faturalardan hesaplandığı için silinen fatura hepsinden kendiliğinden düşer."""
    silinen = atlanan = 0
    for fid in istek.idler:
        f = sirket_kaydi(db, Fatura, fid, k)
        if f.durum != "taslak" and not istek.onaylilar_dahil:
            atlanan += 1
            continue
        db.delete(f)
        silinen += 1
    db.commit()
    return {"silinen": silinen, "atlanan": atlanan}


@router.get("/{fatura_id}/belge")
def belge(fatura_id: int, tur: str = "gorunum", db: Session = Depends(get_db), k: Kullanici = Depends(aktif_kullanici)):
    """tur=gorunum: PDF/HTML/resim. tur=xml: e-Fatura XML'i (indirilir)."""
    f = sirket_kaydi(db, Fatura, fatura_id, k)
    ad = f.xml_dosya if tur == "xml" else f.kaynak_dosya
    if not ad:
        raise HTTPException(404, "Bu faturanın XML'i yok." if tur == "xml" else "Bu faturanın belgesi yok.")
    if tur == "xml":
        return FileResponse(DOSYA_KLASORU / ad, media_type="application/xml", filename=f"{f.fatura_no or f.id}.xml")
    # Firmaların e-Fatura HTML'leri betik içerebilir; programın oturumuna erişemesinler.
    return FileResponse(DOSYA_KLASORU / ad, headers={"Content-Security-Policy": "sandbox"} if ad.endswith((".html", ".htm")) else None)


def _dosya_kaydet(icerik: bytes, uzanti: str) -> str:
    # Ad içeriğin özetidir: aynı dosya ikinci kez yüklenince yeniden saklanmaz (belgeler ve yedekler büyümez)
    ad = f"{hashlib.sha256(icerik).hexdigest()[:32]}.{uzanti}"
    if not (DOSYA_KLASORU / ad).exists():
        (DOSYA_KLASORU / ad).write_bytes(icerik)
    return ad


def _yon_bul(okunan: dict, secilen: str, sirket_vkn: str | None) -> str:
    """e-Fatura XML'inde satıcı biz isek satış, alıcı biz isek alış faturasıdır; seçilen tür ne olursa olsun."""
    vkn = re.sub(r"\D", "", sirket_vkn or "")
    if vkn:
        if re.sub(r"\D", "", (okunan.get("satici") or {}).get("vkn") or "") == vkn:
            return "giden"
        if re.sub(r"\D", "", (okunan.get("alici") or {}).get("vkn") or "") == vkn:
            return "gelen"
    return secilen


def _resimden_oku(icerik: bytes, pdf: bool, mime: str, yontem: str, santiye_adlari, sirket, yon,
                  pdf_hatasi: Exception | None = None) -> dict:
    """Taranmış PDF ya da fotoğraf: metin tanımayla okunur; olmazsa (izin ve anahtar varsa) yapay zekaya gider.

    Metni olan ama düzeni tanınmayan PDF'te resim okuma da sonuç vermezse PDF'in kendi hatası gösterilir."""
    taranmis = pdf_hatasi is None or "taranmış" in str(pdf_hatasi)
    if ocr.var_mi() or karekod.var_mi():
        try:
            okunan = ocr.resimden_fatura_oku(icerik, pdf, santiye_adlari, sirket.unvan, sirket.vkn, yon)
            if okunan["genel_toplam"] or okunan["fatura_no"]:
                return okunan
            hata = kural.KuralHatasi("Resimde fatura bilgisi bulunamadı. Daha net ve düz bir fotoğraf çekin ya da "
                                     "faturanın XML/PDF dosyasını yükleyin.")
        except kural.KuralHatasi as e:
            hata = e
    else:
        hata = kural.KuralHatasi(ocr.KURULU_DEGIL)
    if not taranmis:
        hata = pdf_hatasi
    if yontem == "kural" or not ai.anahtar_var():
        raise hata
    return ai.fatura_oku(icerik, mime, santiye_adlari, GIDER_TURLERI)


XML_TURLERI = {"application/xml", "text/xml", "application/zip", "application/x-zip-compressed"}


@router.post("/oku")
def oku(dosya: UploadFile = File(...), yon: str = "gelen", yontem: str = "otomatik", reddedilen: bool = False,
        db: Session = Depends(get_db), k: Kullanici = Depends(yazabilir)) -> list[dict]:
    """Faturayı okur ve taslak olarak kaydeder.

    Reddedilmiş/iptal edilmiş fatura (üstünde red yazısı, e-Fatura red yanıtı ya da reddedilenler listesinde) kaydedilmez;
    yanıtta {"reddedildi": true, ...} olarak döner. reddedilen=True: yüklenen faturaların hepsi reddedilmiş sayılır
    (portaldan indirilen reddedilen faturalar) ve reddedilenler listesine eklenir.

    yontem: otomatik | kural (yapay zekasız) | ai. e-Fatura XML (veya XML'li zip) her zaman
    yapay zekasız okunur. PDF önce metninden okunur; taranmış PDF ve fotoğraflar bilgisayardaki
    metin tanımayla (Tesseract) okunur. Bunlar da okunamazsa ve anahtar varsa yapay zekaya gider.

    Okuma sunucunun ana akışını durdurmaz (ayrı iş parçacığında çalışır): yükleme sürerken öteki ekranlar çalışır.
    """
    icerik = dosyayi_oku(dosya)
    ozet = hashlib.sha256(icerik).hexdigest()
    adi_k = (dosya.filename or "").lower()
    if not adi_k.endswith((".xml", ".zip")):  # XML her zaman okunur: PDF'ten açılmış taslağı düzeltebilir
        if onceki := _ayni_dosya(db, k.sirket_id, ozet):
            # Daha önce yüklenmiş dosya: sonradan reddedilenler listesine girdiyse kayıtlı fatura iptal için gösterilir
            with KAYIT_KILIDI:
                sonuc = []
                for f in onceki:
                    o = _faturadan_okunan(f)
                    red = reddedilen or red_mi(db, k.sirket_id, o, f.yon)
                    sonuc.append(_redde_isle(db, k, o, f.yon) if red else _cikis_json(f))
                db.commit()
            return sonuc
    santiyeler = db.scalars(select(Santiye).where(Santiye.sirket_id == k.sirket_id, Santiye.durum == "aktif")).all()
    santiye_adlari = [ad for s in santiyeler for ad in kural.kayit_adlari(s)]  # eski adlar da tanınır
    adi = (dosya.filename or "").lower()
    mime = dosya.content_type or ""
    if adi.endswith(".pdf"):
        mime = "application/pdf"
    sirket = db.get(Sirket, k.sirket_id)
    if not re.sub(r"\D", "", sirket.vkn or ""):
        # VKN'miz bilinmezse kendi firmamız satıcı sanılabilir: önce kayıtlı faturalardan, olmazsa bu faturanın
        # karekodundan (alış faturasının alıcısı biziz) öğrenilir; okuma ondan sonra yapılır.
        from ..onarim import kendi_vkn_ogren
        if not kendi_vkn_ogren(db, sirket) and adi.endswith(".pdf") and karekod.var_mi():
            kod = karekod.oku(icerik, True) or {}
            v = re.sub(r"\D", "", str(kod.get("avkntckn" if yon == "gelen" else "vkntckn") or ""))
            if len(v) in (10, 11):
                sirket.vkn = v
        if sirket.vkn:
            db.commit()
    try:
        if adi.endswith((".xml", ".zip")) or mime in XML_TURLERI:
            parcalar = _xml_parcalari(icerik, adi, santiye_adlari)
            with KAYIT_KILIDI:
                sonuc = _xml_kaydet(db, k, parcalar, yon, santiyeler, sirket, dosya.filename, reddedilen)
            tani.okundu(k.sirket_id, dosya.filename)
            return sonuc
        elif mime == "application/pdf" and yontem != "ai":
            # Satış faturası alış ekranından (ya da tersi) yüklendiyse belgedeki taraflar esas alınır
            yon = kural.pdf_yonu(icerik, sirket.vkn) or yon
            # Önce yapay zekasız; okunamazsa ve izin varsa yapay zekaya düş.
            try:
                okunan = kural.pdf_fatura_oku(icerik, santiye_adlari, sirket.unvan, sirket.vkn, yon)
                if not (okunan["genel_toplam"] or okunan["fatura_no"]):
                    raise kural.KuralHatasi("PDF'te fatura bilgisi bulunamadı. XML dosyasını yükleyin ya da elle girin.")
                # Kalemler PDF yazısından okunamadıysa ya da tutmadıysa sayfa resminden de okunur
                okunan = ocr.pdf_kalemlerini_tamamla(okunan, icerik, santiye_adlari, sirket.unvan, sirket.vkn, yon)
                okunan = karsi_tarafi_karekoddan(okunan, icerik, sirket, yon)
            except kural.KuralHatasi as e:
                okunan = _resimden_oku(icerik, True, mime, yontem, santiye_adlari, sirket, yon, e)
            okunanlar = [okunan]
        elif ocr.resim_mi(adi, mime) and yontem != "ai":
            okunanlar = [_resimden_oku(icerik, False, mime, yontem, santiye_adlari, sirket, yon)]
        elif yontem == "kural" or (yontem == "otomatik" and not ai.anahtar_var()):
            raise kural.KuralHatasi("Bu dosya türü okunamaz. Faturanın XML, PDF ya da fotoğrafını (JPG, PNG, HEIC) yükleyin.")
        else:
            okunanlar = [ai.fatura_oku(icerik, mime, santiye_adlari, GIDER_TURLERI)]
    except (ai.OkumaHatasi, kural.KuralHatasi) as e:
        tani.okunamayan_kaydet(k.sirket_id, dosya.filename, icerik, str(e), yon)
        raise HTTPException(422, str(e)) from e
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001  okuyucudaki bir hata tek dosyayı düşürsün, raporda görünsün
        import traceback
        db.rollback()
        iz = traceback.format_exc(limit=-4)
        tani.okunamayan_kaydet(k.sirket_id, dosya.filename, icerik, f"Programda okuma hatası: {e!r}\n{iz}", yon)
        raise HTTPException(422, f"Programda okuma hatası ({type(e).__name__}); Okuma Hata Raporu'na eklendi.") from e

    ad = _dosya_kaydet(icerik, adi.rsplit(".", 1)[-1][:5] if "." in adi else "bin")

    faturalar, redler = [], []
    with KAYIT_KILIDI:
        for okunan in okunanlar:
            if reddedilen or red_mi(db, k.sirket_id, okunan, yon):
                redler.append(_redde_isle(db, k, okunan, _yon_bul(okunan, yon, sirket.vkn)))
                continue
            f = taslak_olustur(db, k, okunan, yon, santiyeler, dosya.filename)
            if getattr(f, "_zaten_var", False):  # aynı fatura zaten listede/kayıtlı: ikinci kez eklenmedi
                if not f.kaynak_dosya or f.kaynak_dosya.endswith((".xml", ".zip")):
                    f.kaynak_dosya = ad  # XML'den okunmuş faturaya PDF görüntüsü eklenir
                faturalar.append(f)
                continue
            f.kaynak_dosya = ad
            f.dosya_ozeti = ozet
            faturalar.append(f)
        db.commit()
        kendi_vkn = re.sub(r"\D", "", sirket.vkn or "")
        if kendi_vkn and db.scalar(select(Cari.id).where(Cari.sirket_id == k.sirket_id, Cari.vkn == kendi_vkn).limit(1)):
            # VKN'miz öğrenilmeden (aynı anda) okunan faturalar kendi firmamıza cari açmış olabilir: hemen düzeltilir
            from ..onarim import carileri_duzelt
            carileri_duzelt(db, sirket, yalniz_sorunlu=True)
            db.commit()
            for f in faturalar:
                db.refresh(f)
    tani.okundu(k.sirket_id, dosya.filename)
    return [_cikis_json(f) for f in faturalar] + redler


def _cikis_json(f: Fatura) -> dict:
    return cikis(f).model_dump(mode="json")


def _karsi(okunan: dict, yon: str) -> dict:
    return (okunan.get("satici") if yon == "gelen" else okunan.get("alici")) or {}


def _faturadan_okunan(f: Fatura) -> dict:
    """Kayıtlı faturanın red listesi için bilgileri (okunan sözlüğü biçiminde)."""
    karsi = {"unvan": f.cari.unvan if f.cari else None, "vkn": f.cari.vkn if f.cari else None}
    return {"fatura_no": f.fatura_no, "ettn": (f.ai_okuma or {}).get("ettn"), "tarih": f.tarih.isoformat() if f.tarih else None,
            "genel_toplam": float(f.genel_toplam or 0), "satici" if f.yon == "gelen" else "alici": karsi}


def _red_kaydi(db: Session, sirket_id: int, okunan: dict, yon: str) -> RedFatura | None:
    """Reddedilenler listesinde bu fatura var mı: ETTN aynı, ya da numara aynı ve (biliniyorsa) karşı firmanın VKN'si aynı."""
    ettn = (okunan.get("ettn") or "").lower() or None
    if ettn and (r := db.scalar(select(RedFatura).where(RedFatura.sirket_id == sirket_id, RedFatura.ettn == ettn).limit(1))):
        return r
    no = okunan.get("fatura_no")
    if not no:
        return None
    vkn = re.sub(r"\D", "", str(_karsi(okunan, yon).get("vkn") or ""))
    for r in db.scalars(select(RedFatura).where(RedFatura.sirket_id == sirket_id, RedFatura.fatura_no == no)):
        if not (ettn and r.ettn) and (not vkn or not r.vkn or r.vkn == vkn):
            return r
    return None


def red_mi(db: Session, sirket_id: int, okunan: dict, yon: str, red_kimlikleri: set[str] = frozenset()) -> bool:
    if okunan.get("red_isareti"):
        return True
    if red_kimlikleri and {(okunan.get("ettn") or "").lower(), (okunan.get("fatura_no") or "").lower()} & red_kimlikleri:
        return True
    return _red_kaydi(db, sirket_id, okunan, yon) is not None


def _kayitli_fatura(db: Session, sirket_id: int, okunan: dict, yon: str) -> Fatura | None:
    """Reddedilen faturanın programda kayıtlı (taslak/onaylı) karşılığı."""
    no = okunan.get("fatura_no")
    if not no:
        return None
    ettn = (okunan.get("ettn") or "").lower()
    vkn = re.sub(r"\D", "", str(_karsi(okunan, yon).get("vkn") or ""))
    for f in db.scalars(select(Fatura).where(Fatura.sirket_id == sirket_id, Fatura.fatura_no == no).order_by(Fatura.id)):
        f_ettn = ((f.ai_okuma or {}).get("ettn") or "").lower()
        f_vkn = re.sub(r"\D", "", (f.cari.vkn if f.cari else "") or "")
        if (ettn and f_ettn and ettn == f_ettn) or (not (ettn and f_ettn) and (not vkn or not f_vkn or vkn == f_vkn)):
            return f
    return None


def _redde_isle(db: Session, k: Kullanici, okunan: dict, yon: str) -> dict:
    """Reddedilen fatura kaydedilmez. Reddedilenler listesine eklenir; aynı fatura taslak olarak bekliyorsa silinir,
    onaylıysa (deftere işlenmişse) iptal edilmesi önerilir (kayitli_id)."""
    karsi = _karsi(okunan, yon)
    vkn = re.sub(r"\D", "", str(karsi.get("vkn") or "")) or None
    if vkn and vkn == re.sub(r"\D", "", db.get(Sirket, k.sirket_id).vkn or ""):
        vkn = None
    r = _red_kaydi(db, k.sirket_id, okunan, yon)
    if r is None:
        r = RedFatura(sirket_id=k.sirket_id, yon=yon, ettn=(okunan.get("ettn") or "").lower() or None,
                      fatura_no=okunan.get("fatura_no"), vkn=vkn, unvan=(karsi.get("unvan") or "").strip() or None,
                      tarih=_tarih(okunan.get("tarih")), tutar=okunan.get("genel_toplam") or 0)
        db.add(r)
        db.flush()
    f = _kayitli_fatura(db, k.sirket_id, okunan, yon)
    kayitli_id = taslak_silindi = None
    if f is not None and f.durum == "taslak":
        taslak_silindi = True
        db.delete(f)
    elif f is not None and f.durum == "onayli":
        kayitli_id = f.id
    unvan = r.unvan or (f.cari.unvan if f is not None and f.cari else None)
    return {"reddedildi": True, "yon": yon, "fatura_no": r.fatura_no, "tarih": r.tarih.isoformat() if r.tarih else None,
            "cari_unvan": unvan, "genel_toplam": float(r.tutar or 0), "kayitli_id": kayitli_id,
            "taslak_silindi": bool(taslak_silindi), "iptal_edilmis": f is not None and f.durum == "iptal"}


_OZETI_TAMAM: set[int] = set()


def _ayni_dosya(db: Session, sirket_id: int, ozet: str) -> list[Fatura]:
    """Aynı dosya daha önce yüklendiyse o faturalar ("zaten kayıtlı" işaretiyle); dosya yeniden okunmaz.
    Önceki sürümde yüklenmiş faturaların özeti ilk seferde sakladıkları belgeden bir kez çıkarılır."""
    if sirket_id not in _OZETI_TAMAM:
        with KAYIT_KILIDI:
            for f in db.scalars(select(Fatura).where(Fatura.sirket_id == sirket_id, Fatura.dosya_ozeti.is_(None),
                                                     Fatura.kaynak_dosya.is_not(None))):
                yol = DOSYA_KLASORU / f.kaynak_dosya
                if yol.is_file() and not f.kaynak_dosya.endswith((".xml", ".zip")):
                    f.dosya_ozeti = hashlib.sha256(yol.read_bytes()).hexdigest()
            db.commit()
        _OZETI_TAMAM.add(sirket_id)
    faturalar = db.scalars(select(Fatura).where(Fatura.sirket_id == sirket_id, Fatura.dosya_ozeti == ozet)).all()
    for f in faturalar:
        f._zaten_var = True
    return list(faturalar)


def _xml_parcalari(icerik: bytes, adi: str, santiye_adlari) -> list[tuple[bytes, tuple | None, dict]]:
    """e-Fatura XML'i ya da XML'li zip okunur (veritabanına dokunmadan): [(xml, görüntü, okunan)].

    Zip'teki e-Fatura yanıt belgeleri (kabul/red) fatura değildir: RED yanıtının gösterdiği faturalar "red_isareti" alır."""
    parcalar, red_kimlikleri, yanit_var = [], set(), False
    for xml, gorunum in kural.xml_ve_gorunumler(icerik, adi):
        yanit = kural.red_yanitlari(xml)
        if yanit is not None:
            red_kimlikleri |= yanit
            yanit_var = True
        else:
            parcalar.append((xml, gorunum))
    if not parcalar:
        if yanit_var:
            raise kural.KuralHatasi("Bu dosya bir e-Fatura yanıtı (kabul/red); fatura yok. Faturanın kendisini yükleyin.")
        raise kural.KuralHatasi("Zip içinde e-Fatura XML dosyası bulunamadı.")
    sonuc = []
    for xml, gorunum in parcalar:
        okunan = kural.efatura_xml_oku(xml, santiye_adlari)
        if red_kimlikleri & {(okunan.get("ettn") or "").lower(), (okunan.get("fatura_no") or "").lower()}:
            okunan["red_isareti"] = True
        sonuc.append((xml, gorunum, okunan))
    return sonuc


def _xml_kaydet(db: Session, k: Kullanici, parcalar, yon: str, santiyeler, sirket,
                dosya_adi: str | None, reddedilen: bool = False) -> list[dict]:
    """Okunan e-Faturalar: her fatura ayrı taslak olur; XML ve görüntüsü faturaya bağlanır.

    Aynı fatura daha önce PDF'ten okunduysa yeni taslak açılmaz: taslak XML'deki bilgilerle güncellenir,
    PDF görüntü olarak kalır.
    """
    faturalar, redler = [], []
    for xml, gorunum, okunan in parcalar:
        f_yon = _yon_bul(okunan, yon, sirket.vkn)
        if reddedilen or red_mi(db, k.sirket_id, okunan, f_yon):
            redler.append(_redde_isle(db, k, okunan, f_yon))
            continue
        f = taslak_olustur(db, k, okunan, f_yon, santiyeler, dosya_adi)
        if getattr(f, "_zaten_var", False) and f.xml_dosya:
            faturalar.append(f)
            continue
        f.xml_dosya = _dosya_kaydet(xml, "xml")
        if gorunum and (not f.kaynak_dosya or f.kaynak_dosya.endswith((".xml", ".zip"))):
            f.kaynak_dosya = _dosya_kaydet(*gorunum)
        elif not f.kaynak_dosya:
            f.kaynak_dosya = f.xml_dosya
        faturalar.append(f)
    db.commit()
    return [_cikis_json(f) for f in faturalar] + redler


def karsi_tarafi_karekoddan(okunan: dict, icerik: bytes, sirket: Sirket, yon: str) -> dict:
    """PDF yazısında karşı firmanın VKN'si bulunamadıysa ya da bizimki çıktıysa VKN faturanın GİB karekodundan alınır;
    kendi VKN'miz hiçbir yoldan cari olmaz."""
    taraf = "satici" if yon == "gelen" else "alici"
    vkn = re.sub(r"\D", "", str((okunan.get(taraf) or {}).get("vkn") or ""))
    kendi = re.sub(r"\D", "", sirket.vkn or "")
    if vkn and kendi and vkn != kendi:
        return okunan
    k = karekod.oku(icerik, True) if karekod.var_mi() else None
    if k and not kendi:
        # Firma bilgisinde VKN'miz yok: karekodda alış faturasının alıcısı, satış faturasının satıcısı biziz
        kendi = re.sub(r"\D", "", str(k.get("avkntckn" if yon == "gelen" else "vkntckn") or ""))
        if len(kendi) in (10, 11):
            sirket.vkn = kendi
        if vkn and vkn != kendi:
            return okunan
    if k and yon == "gelen":
        okunan = karekod.uygula(okunan, k, sirket.vkn, yon)
    if re.sub(r"\D", "", str((okunan.get(taraf) or {}).get("vkn") or "")) == kendi:
        okunan = {**okunan, taraf: {**okunan[taraf], "vkn": None}}
    return okunan


def kendi_firmamiz_mi(db: Session, c: Cari, sirket_id: int) -> bool:
    s = db.get(Sirket, sirket_id)
    vkn = re.sub(r"\D", "", s.vkn or "")
    return bool(vkn and re.sub(r"\D", "", c.vkn or "") == vkn) or (not c.vkn and kural.kendi_unvani_mi(c.unvan, s.unvan))


def cari_bul_ya_ac(db: Session, k: Kullanici, karsi: dict, tur: str) -> tuple[Cari | None, bool]:
    vkn = re.sub(r"\D", "", str(karsi.get("vkn") or "")) or None
    if vkn and vkn == re.sub(r"\D", "", db.get(Sirket, k.sirket_id).vkn or ""):
        vkn = None  # kendi VKN'miz hiçbir cariye yazılmaz (alıcı bilgisi satıcıya karışmış)
    sirket = db.get(Sirket, k.sirket_id)
    unvan = (karsi.get("unvan") or "").strip()
    if kural.kotu_unvan(unvan) or (not vkn and kural.kendi_unvani_mi(unvan, sirket.unvan)):
        unvan = ""  # "Ticaret Sicil No" gibi etiketle ya da (başka VKN yokken) kendi adımızla cari açılmaz / seçilmez
    if vkn:
        cari = db.scalar(select(Cari).where(Cari.sirket_id == k.sirket_id, Cari.vkn == vkn))
        if cari:
            if (cari.ad_otomatik or kural.kotu_unvan(cari.unvan)) and kural.daha_iyi_unvan(cari.unvan, unvan):
                cari.unvan = unvan  # eski sürümün yanlış okuduğu ad düzelir; fatura VKN ile aynı cariye bağlı kalır
            return cari, False
    if unvan:
        # Aynı ad ("Ltd." / "Ltd. Şti." gibi ek farkı yok sayılır); VKN'leri farklı iki firma ayrı kalır
        aranan = kural.unvan_cekirdegi(unvan) or kural.ad_anahtari(unvan)
        kendi_vkn = re.sub(r"\D", "", sirket.vkn or "")
        cari = next((c for c in db.scalars(select(Cari).where(Cari.sirket_id == k.sirket_id).order_by(Cari.id))
                     if (kural.unvan_cekirdegi(c.unvan) or kural.ad_anahtari(c.unvan)) == aranan
                     and not (vkn and c.vkn and re.sub(r"\D", "", c.vkn) != vkn)
                     and not (kendi_vkn and re.sub(r"\D", "", c.vkn or "") == kendi_vkn)), None)
        if cari:
            if vkn and not cari.vkn:
                cari.vkn = vkn
            return cari, False
        cari = Cari(sirket_id=k.sirket_id, tur=tur, unvan=unvan, vkn=vkn, ad_otomatik=True,
                    **{a: karsi.get(a) for a in ["vergi_dairesi", "adres", "telefon", "iban"]})
        db.add(cari)
        db.flush()
        return cari, True
    if vkn:
        # Firmanın adı faturada yazmıyor (yalnız karekodda VKN var): cari VKN'siyle açılır, kullanıcı adını bir kez yazar;
        # bu VKN'li sonraki faturalar aynı cariye işlenir. Belgeden okunan gerçek ad gelirse bu geçici ad değişir.
        cari = Cari(sirket_id=k.sirket_id, tur=tur, unvan=f"VKN {vkn}", vkn=vkn, ad_otomatik=True)
        db.add(cari)
        db.flush()
        return cari, True
    return None, False


def taslak_olustur(db: Session, k: Kullanici, okunan: dict, yon: str, santiyeler, dosya_adi: str | None = None) -> Fatura:
    karsi = okunan.get("satici") if yon == "gelen" else okunan.get("alici")
    karsi = karsi or {}
    # Cari VKN ya da ünvanla bulunur; yoksa faturadaki bilgilerle hemen açılır.
    cari, yeni_cari = cari_bul_ya_ac(db, k, karsi, "tedarikci" if yon == "gelen" else "musteri")
    if cari and okunan.get("fatura_no") and not yeni_cari:
        # Aynı PDF ikinci kez yüklendiyse yeni taslak açma; mevcut kaydı döndür.
        mevcut = db.scalar(select(Fatura).where(Fatura.sirket_id == k.sirket_id, Fatura.yon == yon, Fatura.cari_id == cari.id,
                                                Fatura.fatura_no == okunan["fatura_no"]))
        if mevcut:
            xml_geldi = okunan.get("okuma_yontemi") == "e-Fatura XML"
            if xml_geldi and mevcut.durum == "taslak" and (mevcut.ai_okuma or {}).get("okuma_yontemi") != "e-Fatura XML":
                return _xml_ile_guncelle(db, mevcut, okunan, santiyeler)
            mevcut._zaten_var = True  # kaydedilmeyen işaret; ekranda "zaten listede" yazar
            return mevcut
    santiye = next((s for s in santiyeler if kural.adi_bu_mu(s, okunan.get("onerilen_santiye"))), None)
    # Kullanıcının bu firmanın son onaylı faturasında seçtiği gider türü tahminden önce gelir.
    onceki_gider = db.scalar(select(Fatura.gider_turu).where(
        Fatura.sirket_id == k.sirket_id, Fatura.cari_id == cari.id, Fatura.yon == yon, Fatura.durum == "onayli",
        Fatura.gider_turu.is_not(None)).order_by(Fatura.tarih.desc(), Fatura.id.desc()).limit(1)) if cari and not yeni_cari else None
    if onceki_gider in GIDER_TURLERI:
        okunan = {**okunan, "onerilen_gider_turu": onceki_gider}

    f = Fatura(
        sirket_id=k.sirket_id, yon=yon, durum="taslak",
        fatura_no=okunan.get("fatura_no"), tarih=_tarih(okunan.get("tarih")), vade=_tarih(okunan.get("vade")),
        cari_id=cari.id if cari else None, santiye_id=santiye.id if santiye else None,
        gider_turu=okunan.get("onerilen_gider_turu") if okunan.get("onerilen_gider_turu") in GIDER_TURLERI else None,
        tevkifat=okunan.get("tevkifat") or 0, stopaj=okunan.get("stopaj") or 0,
        diger_vergiler=okunan.get("diger_vergiler") or 0, yuvarlama=okunan.get("yuvarlama") or 0,
        aciklama=okunan.get("aciklama"), para_birimi=_para_birimi(okunan), kur=_kur(okunan),
        fatura_tipi=(okunan.get("fatura_tipi") or "").upper() or None,
    )
    kalemleri_yaz(f, [
        kalem_giris(kl, kdv_varsayilan=20)
        for kl in okunan.get("kalemler", [])
    ])
    db.add(f)
    db.flush()

    # uyarilar: kontrol edilmesi gereken sorunlar. bilgi: işlemi anlatan notlar (uyarı sayılmaz).
    uyarilar = ai.tutarlilik_uyarilari(okunan)
    bilgi = []
    uyarilar += toplam_farki(f, okunan)
    if cari and cari.unvan == f"VKN {cari.vkn}":
        uyarilar.append("Firmanın adı faturada yazmıyor; cariye adını bir kez yazın.")
    elif yeni_cari:
        bilgi.append(f"'{cari.unvan}' carilerde yoktu; yeni cari açıldı.")
    elif not cari:
        uyarilar.append("Faturadaki firma okunamadı; cariyi seçin.")
    if not f.kalemler or not float(f.genel_toplam):
        uyarilar.append("Kalemler ve tutarlar okunamadı; bu PDF düzeni tanınmıyor.")
    if mukerrer_mi(db, f):
        uyarilar.append("Bu fatura daha önce kaydedilmiş görünüyor.")
    u, b = notlari_ayir(okunan.get("notlar"))
    uyarilar += u
    bilgi += b
    if not f.kalemler and okunan.get("karekod") and not (okunan.get("resimden") or {}).get("yalniz_kalemler"):
        # Yazısı olmayan PDF: tek, sade uyarı (teknik ayrıntılar yerine ne yapılacağı)
        uyarilar = [u for u in uyarilar if u.startswith("Firmanın adı")] + [
            "Faturanın PDF'inde okunacak yazı yok; toplamlar karekoddan alındı. Kalemleri girin ya da faturanın XML'ini yükleyin."]
    if resim := okunan.get("resimden"):
        if resim.get("belirsiz"):
            uyarilar.append(f"Resimde net seçilemeyen tutarlar var ({', '.join(resim['belirsiz'][:6])}); belgeyle karşılaştırın.")
        if (resim.get("guven") or 0) < 60:
            uyarilar.append(f"Resim bulanık (okuma güveni %{resim.get('guven')}); bütün alanları belgeyle karşılaştırın.")
        bilgi.append("Kalemler sayfanın resminden okundu; toplamları faturayı tutuyor, adları belgeyle bir kez karşılaştırın."
                     if resim.get("yalniz_kalemler") else
                     "Fatura resimden metin tanımayla okundu; ad ve tutarları belgeyle bir kez karşılaştırın.")
    f.ai_okuma = {**okunan, "uyarilar": uyarilar, "bilgi": bilgi, "dosya_adi": dosya_adi}
    return f


_BILGI_NOTU = re.compile(r"okundu|yuvarlama farkı|cinsinden \(kur|fatura tutarıyla kaydedildi|karekodundan doğrulandı")


def notlari_ayir(notlar: str | None) -> tuple[list[str], list[str]]:
    """Okuma notları: kontrol gerektirenler uyarı, işlemi anlatanlar ("kur 55,28 TL", "yuvarlama farkı") bilgi."""
    uyari, bilgi = [], []
    for not_ in re.split(r"(?<=\.)\s+", notlar or ""):
        if not_:
            yuv = re.search(r"Faturada ([\d.,]+) TL yuvarlama farkı", not_)
            buyuk = yuv and (kural.para_coz(yuv.group(1)) or 0) > 1  # 1 TL'yi aşan fark kontrol edilsin
            (bilgi if _BILGI_NOTU.search(not_) and not buyuk else uyari).append(not_)
    return uyari, bilgi


def _xml_ile_guncelle(db: Session, f: Fatura, okunan: dict, santiyeler) -> Fatura:
    """PDF'ten okunmuş taslağı aynı faturanın XML'iyle düzeltir; kullanıcının seçtiği şantiye/gider türü korunur."""
    santiye = next((s for s in santiyeler if kural.adi_bu_mu(s, okunan.get("onerilen_santiye"))), None)
    eski_santiyeler = {kl.santiye_id for kl in f.kalemler if kl.santiye_id}
    f.tarih, f.vade = _tarih(okunan.get("tarih")) or f.tarih, _tarih(okunan.get("vade")) or f.vade
    f.santiye_id = f.santiye_id or (santiye.id if santiye else None)
    oneri = okunan.get("onerilen_gider_turu")
    f.gider_turu = f.gider_turu or (oneri if oneri in GIDER_TURLERI else None)
    f.tevkifat, f.diger_vergiler = okunan.get("tevkifat") or 0, okunan.get("diger_vergiler") or 0
    f.stopaj = okunan.get("stopaj") or 0
    f.yuvarlama = okunan.get("yuvarlama") or 0
    f.para_birimi, f.kur = _para_birimi(okunan), _kur(okunan) or f.kur
    f.fatura_tipi = (okunan.get("fatura_tipi") or "").upper() or f.fatura_tipi
    tek_santiye = next(iter(eski_santiyeler)) if len(eski_santiyeler) == 1 else None
    kalemleri_yaz(f, [kalem_giris(kl, tek_santiye) for kl in okunan.get("kalemler", [])])
    uyarilar = ai.tutarlilik_uyarilari(okunan)
    uyarilar += toplam_farki(f, okunan)
    uyarilar += notlari_ayir(okunan.get("notlar"))[0]
    f.ai_okuma = {**okunan, "uyarilar": uyarilar,
                  "bilgi": ["PDF'ten okunan taslak, aynı faturanın e-Fatura XML'iyle güncellendi."]}
    db.flush()
    return f


def _para_birimi(okunan: dict) -> str:
    p = (okunan.get("para_birimi") or "TRY")[:3].upper()
    return "TRY" if p == "TL" else p


def _kur(okunan: dict) -> float | None:
    kur = okunan.get("kur")
    return float(kur) if _para_birimi(okunan) != "TRY" and isinstance(kur, (int, float)) and kur > 0 else None


def _tarih(metin: str | None) -> date | None:
    try:
        return date.fromisoformat(metin) if metin else None
    except ValueError:
        return None
