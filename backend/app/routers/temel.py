"""Giriş, cari ve şantiye işlemleri."""
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .. import ai, kural, ocr, schemas, yetki
from ..auth import aktif_kullanici, oturum_ac, sifre_dogru, sifre_hashle, yazabilir
from ..db import get_db
from ..surum import SURUM
from ..models import GIDER_TURLERI, Cari, Fatura, FaturaKalem, HataliGiris, Kullanici, Santiye, Sirket

router = APIRouter(prefix="/api")


# --- Giriş ---------------------------------------------------------------

def yerel_mi(request: Request) -> bool:
    return (request.client.host if request.client else "") in ("127.0.0.1", "::1", "localhost", "testclient")  # testclient: otomatik testler


@router.post("/kayit")
def kayit(istek: schemas.KayitIstegi, request: Request, db: Session = Depends(get_db)):
    """Yeni şirket hesabı yalnız programın çalıştığı bilgisayardan açılır (ya da henüz hiç hesap yoksa).
    Program ağa açıldığında başka bilgisayardan kimse kendine hesap açamaz; kullanıcıları şirket sahibi ekler."""
    if not yerel_mi(request) and db.scalar(select(Kullanici.id).limit(1)) is not None:
        raise HTTPException(403, "Yeni hesap yalnız programın kurulu olduğu bilgisayardan açılabilir. "
                                 "Kullanıcı eklemek için şirket sahibine başvurun.")
    istek.eposta = istek.eposta.strip()
    if len(istek.sifre) < 6:
        raise HTTPException(422, "Şifre en az 6 karakter olmalı.")
    if db.scalar(select(Kullanici).where(Kullanici.eposta == istek.eposta.lower())):
        raise HTTPException(409, "Bu e-posta ile kayıtlı bir kullanıcı var.")
    sirket = Sirket(unvan=istek.sirket_unvan)
    db.add(sirket)
    db.flush()
    k = Kullanici(eposta=istek.eposta.lower(), ad=istek.ad, sifre_hash=sifre_hashle(istek.sifre), sirket_id=sirket.id)
    db.add(k)
    db.commit()
    return {"token": oturum_ac(db, k)}


HATALI_GIRIS_SINIRI, HATALI_GIRIS_SURESI = 5, 600


@router.post("/giris")
def giris(istek: schemas.GirisIstegi, request: Request, db: Session = Depends(get_db)):
    ip = request.client.host if request.client else ""
    simdi = time.time()
    # Denemeler veritabanında tutulur: program yeniden açılınca kilit sıfırlanmaz
    db.execute(delete(HataliGiris).where(HataliGiris.zaman < simdi - HATALI_GIRIS_SURESI))
    db.commit()
    if db.scalar(select(func.count()).where(HataliGiris.ip == ip)) >= HATALI_GIRIS_SINIRI:  # şifre deneme saldırısına karşı
        raise HTTPException(429, "Çok sayıda hatalı giriş denendi. 10 dakika sonra tekrar deneyin.")
    k = db.scalar(select(Kullanici).where(Kullanici.eposta == istek.eposta.strip().lower()))
    if not k or not sifre_dogru(istek.sifre, k.sifre_hash):
        db.add(HataliGiris(ip=ip, zaman=simdi))
        db.commit()
    if not k:
        raise HTTPException(401, "Bu e-posta ile kayıtlı hesap bulunamadı. E-postayı kontrol edin; "
                                 "bu bilgisayarda hiç hesap açmadıysanız 'Yeni şirket hesabı aç'a tıklayın.")
    if not sifre_dogru(istek.sifre, k.sifre_hash):
        raise HTTPException(401, "Şifre yanlış. Unuttuysanız program klasöründeki sifre_sifirla.bat ile yenileyin.")
    return {"token": oturum_ac(db, k)}


@router.get("/ben")
def ben(k: Kullanici = Depends(aktif_kullanici)):
    return {"ad": k.ad, "eposta": k.eposta, "rol": k.rol, "sirket": k.sirket.unvan, "gider_turleri": GIDER_TURLERI,
            "yetkiler": yetki.yetkileri(k),
            "ai_var": ai.anahtar_var(),
            "ocr_var": ocr.var_mi(), "surum": SURUM,
            "tevkifat_kodlari": [{"kod": kod, "oran": oran, "aciklama": ac} for kod, (oran, ac) in kural.TEVKIFAT_KODLARI.items()]}


# --- Ortak yardımcı ------------------------------------------------------

def sirket_kaydi(db: Session, model, kayit_id: int, k: Kullanici):
    kayit = db.get(model, kayit_id)
    if not kayit or kayit.sirket_id != k.sirket_id:
        raise HTTPException(404, "Kayıt bulunamadı.")
    return kayit


# --- Cariler -------------------------------------------------------------

def bagli_kayitlar(db: Session, cari_id: int | None = None, santiye_id: int | None = None) -> str | None:
    """Silinmek istenen cari/şantiyeye bağlı kayıtlar ("12 faturası, 3 banka/kasa hareketi"); yoksa None.
    Bağlı kaydı olan silinmez: silinirse faturalar ve hareketler sahipsiz kalır, bakiyeler bozulur."""
    from sqlalchemy import distinct, func, or_

    from ..models import Cek, Depo, Hareket, TaseronGider
    if cari_id is not None:
        sayilar = [(db.scalar(select(func.count()).where(Fatura.cari_id == cari_id)), "faturası"),
                   (db.scalar(select(func.count()).where(or_(Cek.cari_id == cari_id, Cek.ciro_cari_id == cari_id))), "çeki"),
                   (db.scalar(select(func.count()).where(Hareket.cari_id == cari_id)), "banka/kasa hareketi"),
                   (db.scalar(select(func.count()).where(Depo.cari_id == cari_id)), "bağlı deposu"),
                   (db.scalar(select(func.count()).where(TaseronGider.cari_id == cari_id)), "taşeron gideri")]
    else:
        faturalar = db.scalar(select(func.count(distinct(Fatura.id))).select_from(Fatura).outerjoin(FaturaKalem)
                              .where(or_(Fatura.santiye_id == santiye_id, FaturaKalem.santiye_id == santiye_id)))
        sayilar = [(faturalar, "faturası"), (db.scalar(select(func.count()).where(Cek.santiye_id == santiye_id)), "çeki"),
                   (db.scalar(select(func.count()).where(Hareket.santiye_id == santiye_id)), "banka/kasa hareketi"),
                   (db.scalar(select(func.count()).where(Depo.santiye_id == santiye_id)), "deposu")]
    return ", ".join(f"{n} {ad}" for n, ad in sayilar if n) or None


@router.get("/cariler", response_model=list[schemas.CariCikis])
def cariler(ara: str = "", db: Session = Depends(get_db), k: Kullanici = Depends(aktif_kullanici)):
    q = select(Cari).where(Cari.sirket_id == k.sirket_id).order_by(Cari.unvan)
    if ara:
        q = q.where(Cari.unvan.ilike(f"%{ara}%") | Cari.vkn.ilike(f"%{ara}%"))
    return db.scalars(q).all()


def kendi_vkn_reddet(db: Session, k: Kullanici, vkn: str | None) -> None:
    import re
    kendi = re.sub(r"\D", "", db.get(Sirket, k.sirket_id).vkn or "")
    if kendi and re.sub(r"\D", "", vkn or "") == kendi:
        raise HTTPException(400, "Bu VKN firmanızın kendi VKN'si; kendi firmanız cari olarak açılamaz.")


def ayni_adli_cari(db: Session, sirket_id: int, unvan: str | None, vkn: str | None = None, haric: int | None = None) -> Cari | None:
    """Aynı ad: ekler ("Ltd. Şti.", "A.Ş."), Türkçe karakter, nokta ve boşluk farkı yok sayılır."""
    anahtar = kural.unvan_cekirdegi(unvan) or kural.ad_anahtari(unvan)
    return next((c for c in db.scalars(select(Cari).where(Cari.sirket_id == sirket_id).order_by(Cari.id))
                 if c.id != haric and anahtar and (kural.unvan_cekirdegi(c.unvan) or kural.ad_anahtari(c.unvan)) == anahtar
                 and not (vkn and c.vkn and c.vkn != vkn)), None)


def ayni_adli_santiye(db: Session, sirket_id: int, ad: str | None, haric: int | None = None) -> Santiye | None:
    anahtar = kural.ad_anahtari(ad)
    return next((s for s in db.scalars(select(Santiye).where(Santiye.sirket_id == sirket_id).order_by(Santiye.id))
                 if s.id != haric and anahtar and kural.adi_bu_mu(s, ad)), None)


@router.post("/cariler", response_model=schemas.CariCikis)
def cari_ekle(veri: schemas.CariGiris, db: Session = Depends(get_db), k: Kullanici = Depends(yazabilir)):
    kendi_vkn_reddet(db, k, veri.vkn)
    if veri.vkn and (ayni := db.scalar(select(Cari).where(Cari.sirket_id == k.sirket_id, Cari.vkn == veri.vkn))):
        return ayni  # aynı VKN'li cari ikinci kez açılmaz, var olan seçilir
    # Aynı adla ikinci cari açılmaz, var olan döner (VKN'leri farklı iki firma ayrı kalır)
    if (ayni := ayni_adli_cari(db, k.sirket_id, veri.unvan, veri.vkn)) is not None:
        if veri.vkn and not ayni.vkn:
            ayni.vkn = veri.vkn
            db.commit()
        return ayni
    c = Cari(sirket_id=k.sirket_id, **veri.model_dump())
    db.add(c)
    db.commit()
    return c


@router.get("/cariler/benzer")
def benzer_cariler(unvan: str = "", vkn: str = "", db: Session = Depends(get_db), k: Kullanici = Depends(aktif_kullanici)):
    """Yeni cari açılmadan önce: aynı VKN'li ya da adı benzeyen cariler (ekler, Türkçe karakter, küçük yazım farkı yok sayılır)."""
    vkn = "".join(ch for ch in vkn if ch.isdigit())
    sonuc = []
    for c in db.scalars(select(Cari).where(Cari.sirket_id == k.sirket_id).order_by(Cari.unvan)):
        ayni_vkn = bool(vkn and c.vkn and "".join(ch for ch in c.vkn if ch.isdigit()) == vkn)
        if ayni_vkn or (unvan.strip() and kural.benzer_unvan(unvan, c.unvan)
                        and not (vkn and c.vkn and "".join(ch for ch in c.vkn if ch.isdigit()) != vkn)):
            sonuc.append({"id": c.id, "unvan": c.unvan, "vkn": c.vkn, "ayni_vkn": ayni_vkn})
    return sorted(sonuc, key=lambda x: not x["ayni_vkn"])[:5]


@router.get("/cariler/kontrol")
def cari_kontrol(db: Session = Depends(get_db), k: Kullanici = Depends(aktif_kullanici)):
    """Adı etiket/adres gibi görünen ya da firmamızın VKN'sini taşıyan cariler ve açılıştaki onarımın sonucu."""
    from .. import onarim
    sirket = db.get(Sirket, k.sirket_id)
    sorunlu = [{"id": c.id, "unvan": c.unvan, "vkn": c.vkn, "neden": n}
               for c in db.scalars(select(Cari).where(Cari.sirket_id == k.sirket_id)) for n in [onarim.cari_sorunu(c, sirket)] if n]
    from .. import tani
    r = onarim.rapor_oku().get("sirketler", {}).get(str(k.sirket_id), {})
    # Açılış onarımının düzelttikleri kullanıcıya yalnız sayı olarak gösterilir
    duzelen = sum(len(r.get(a) or []) for a in ("duzelen_cariler", "birlesen_santiyeler", "birlesen_cariler", "kalemleri_okunan_faturalar", "yeniden_okunan_taslaklar",
                                                "yeniden_okunan_onaylilar", "tevkifati_kalemlere_yazilan", "kdv_tutari_duzeltilen", "satisa_alinan_taslaklar")) \
        + int(r.get("iskontosu_sutuna_tasinan_kalem") or 0)
    return {"sorunlu": sorunlu, "sorunlu_faturalar": tani.onayli_sorunlari(db, sirket),
            "otomatik_duzeltilen": duzelen, "tutari_degisen": len(r.get("tutari_degisen_onaylilar") or [])}


@router.put("/cariler/{cari_id}", response_model=schemas.CariCikis)
def cari_guncelle(cari_id: int, veri: schemas.CariGiris, db: Session = Depends(get_db), k: Kullanici = Depends(yazabilir)):
    c = sirket_kaydi(db, Cari, cari_id, k)
    kendi_vkn_reddet(db, k, veri.vkn)
    vkn = "".join(ch for ch in veri.vkn or "" if ch.isdigit())
    if vkn and (diger := next((x for x in db.scalars(select(Cari).where(Cari.sirket_id == k.sirket_id, Cari.id != c.id))
                               if "".join(ch for ch in x.vkn or "" if ch.isdigit()) == vkn), None)):
        raise HTTPException(409, f"Bu VKN '{diger.unvan}' carisinde kayıtlı; aynı VKN ile ikinci cari olmaz.")
    if veri.unvan != c.unvan:
        c.ad_otomatik = False  # kullanıcının verdiği ad faturalardan okunan adla değişmez
    # Vade günü gönderilmediyse (eski ekranlar) korunur
    for alan, deger in veri.model_dump(exclude=set() if "vade_gun" in veri.model_fields_set else {"vade_gun"}).items():
        setattr(c, alan, deger)
    db.commit()
    return c


@router.delete("/cariler/{cari_id}")
def cari_sil(cari_id: int, db: Session = Depends(get_db), k: Kullanici = Depends(yazabilir)):
    c = sirket_kaydi(db, Cari, cari_id, k)
    if neden := bagli_kayitlar(db, cari_id=c.id):
        raise HTTPException(409, f"{neden} var, silinemez.")
    db.delete(c)
    db.commit()
    return {"ok": True}


# --- Şantiyeler ----------------------------------------------------------

@router.get("/santiyeler", response_model=list[schemas.SantiyeCikis])
def santiyeler(db: Session = Depends(get_db), k: Kullanici = Depends(aktif_kullanici)):
    return db.scalars(select(Santiye).where(Santiye.sirket_id == k.sirket_id).order_by(Santiye.ad)).all()


@router.post("/santiyeler", response_model=schemas.SantiyeCikis)
def santiye_ekle(veri: schemas.SantiyeGiris, db: Session = Depends(get_db), k: Kullanici = Depends(yazabilir)):
    if (ayni := ayni_adli_santiye(db, k.sirket_id, veri.ad)) is not None:
        return ayni  # aynı adla ikinci şantiye açılmaz; var olan seçilir
    s = Santiye(sirket_id=k.sirket_id, **veri.model_dump())
    db.add(s)
    db.commit()
    return s


@router.put("/santiyeler/{santiye_id}", response_model=schemas.SantiyeCikis)
def santiye_guncelle(santiye_id: int, veri: schemas.SantiyeGiris, db: Session = Depends(get_db), k: Kullanici = Depends(yazabilir)):
    s = sirket_kaydi(db, Santiye, santiye_id, k)
    if not (veri.ad or "").strip():
        raise HTTPException(422, "Şantiye adını yazın.")
    if (ayni := ayni_adli_santiye(db, k.sirket_id, veri.ad, haric=s.id)) is not None:
        raise HTTPException(409, f"'{veri.ad}' adı '{ayni.ad}' şantiyesinde kullanılıyor.")
    # Ad değişince fatura, çek, hareket ve taşeron kayıtları aynı şantiyede kalır (kimlikle bağlı); eski ad saklanır
    kural.ad_degistir(s, veri.ad)
    for alan, deger in veri.model_dump(exclude={"ad"}).items():
        setattr(s, alan, deger)
    db.commit()
    return s


def _adlari_ekle(hedef, kaynak) -> None:
    """Kaynağın adı ve eski adları hedefin eski adlarına eklenir: eski adla gelen belge/Excel hedefe işlenir."""
    adlar = kural.kayit_adlari(hedef)
    for x in kural.kayit_adlari(kaynak):
        if all(kural.ad_anahtari(x) != kural.ad_anahtari(y) for y in adlar):
            adlar.append(x)
    hedef.eski_adlar = "\n".join(adlar[1:]) or None


def _wolvox_kaydi_tasi(db: Session, sirket_id: int, santiye_id: int, depo_id: int | None = None) -> None:
    """Wolvox aktarımının açtığı şantiye birleşince/depoya dönünce aktarım listesinden çıkar (geri almada silinmesin);
    depoya dönüştüyse yeni depo aktarımın açtıkları arasına girer."""
    from ..models import WolvoxAktarim
    for a in db.scalars(select(WolvoxAktarim).where(WolvoxAktarim.sirket_id == sirket_id)):
        if santiye_id in (a.acilan_santiyeler or []):
            a.acilan_santiyeler = [x for x in a.acilan_santiyeler if x != santiye_id]
            if depo_id:
                a.acilan_depolar = [*(a.acilan_depolar or []), depo_id]


class SantiyeBirlestir(schemas.BaseModel):
    idler: list[int]


@router.post("/santiyeler/{hedef_id}/birlestir", response_model=schemas.SantiyeCikis)
def santiye_birlestir(hedef_id: int, istek: SantiyeBirlestir, db: Session = Depends(get_db), k: Kullanici = Depends(yazabilir)):
    """Seçilen şantiyeler hedef şantiyede toplanır: faturaları, kalemleri (Wolvox aktarımı dahil), çekleri, hareketleri,
    depoları ve taşeron giderleri hedefe geçer; adları hedefin eski adı olur, kendileri silinir."""
    from sqlalchemy import update

    from ..models import Cek, Depo, Hareket, TaseronGider
    hedef = sirket_kaydi(db, Santiye, hedef_id, k)
    for sid in set(istek.idler) - {hedef.id}:
        s = sirket_kaydi(db, Santiye, sid, k)
        for model in (Fatura, FaturaKalem, Hareket, Cek, Depo, TaseronGider):
            db.execute(update(model).where(model.santiye_id == s.id).values(santiye_id=hedef.id))
        _adlari_ekle(hedef, s)
        _wolvox_kaydi_tasi(db, k.sirket_id, s.id)
        db.delete(s)
    db.commit()
    return hedef


class DepoyaCevir(schemas.BaseModel):
    santiye_id: int | None = None  # deponun bağlanacağı şantiye (boş: şantiyesiz depo)
    cari_id: int | None = None  # taşeron carisi (isteğe bağlı)


@router.post("/santiyeler/{santiye_id}/depoya-cevir")
def santiye_depoya_cevir(santiye_id: int, istek: DepoyaCevir, db: Session = Depends(get_db), k: Kullanici = Depends(yazabilir)):
    """Şantiyeyi taşeron deposu yapar: aynı adla (ya da aynı adlı var olan) depo seçilen şantiyenin içinde açılır;
    bu şantiyeye yazılmış bütün fatura kalemleri (Wolvox aktarımı dahil) o depoya, çek/hareket/taşeron giderleri
    seçilen şantiyeye geçer. Şantiyenin kendi depoları da seçilen şantiyeye taşınır. Şantiye silinir."""
    from sqlalchemy import or_, update

    from ..models import Cek, Depo, Hareket, TaseronGider
    s = sirket_kaydi(db, Santiye, santiye_id, k)
    ust = sirket_kaydi(db, Santiye, istek.santiye_id, k) if istek.santiye_id else None
    if ust is not None and ust.id == s.id:
        raise HTTPException(400, "Depo kendi şantiyesinin içine alınamaz; başka bir şantiye seçin.")
    if istek.cari_id:
        sirket_kaydi(db, Cari, istek.cari_id, k)
    ust_id = ust.id if ust else None
    d = next((x for x in db.scalars(select(Depo).where(Depo.sirket_id == k.sirket_id, Depo.santiye_id == ust_id))
              if kural.adi_bu_mu(x, s.ad)), None)
    if d is None:
        d = Depo(sirket_id=k.sirket_id, ad=s.ad, santiye_id=ust_id, cari_id=istek.cari_id)
        db.add(d)
        db.flush()
    elif istek.cari_id and not d.cari_id:
        d.cari_id = istek.cari_id
    _adlari_ekle(d, s)
    # Kalemi bu şantiyede olanlar (kalemin kendi şantiyesi ya da faturanın şantiyesi boş kalemde) depoya geçer
    kalemler = db.scalars(select(FaturaKalem).join(Fatura).where(Fatura.sirket_id == k.sirket_id, or_(
        FaturaKalem.santiye_id == s.id, (FaturaKalem.santiye_id.is_(None)) & (Fatura.santiye_id == s.id)))).all()
    for kl in kalemler:
        kl.santiye_id = ust_id
        if kl.depo_id is None:
            kl.depo_id = d.id
    db.flush()
    db.execute(update(TaseronGider).where(TaseronGider.santiye_id == s.id, TaseronGider.depo_id.is_(None)).values(depo_id=d.id))
    for model in (Fatura, Hareket, Cek, TaseronGider, Depo):
        db.execute(update(model).where(model.santiye_id == s.id).values(santiye_id=ust_id))
    _wolvox_kaydi_tasi(db, k.sirket_id, s.id, d.id)
    db.delete(s)
    db.commit()
    return {"depo_id": d.id, "depo": d.ad, "kalem_sayisi": len(kalemler)}


class DurumIstegi(schemas.BaseModel):
    idler: list[int]
    durum: str  # aktif | pasif


@router.post("/santiyeler/durum")
def santiye_durumu(istek: DurumIstegi, db: Session = Depends(get_db), k: Kullanici = Depends(yazabilir)):
    """Aktif / pasif: pasif şantiye seçim listelerinde görünmez (kayıtları ve raporları durur), istenince yeniden açılır."""
    if istek.durum not in ("aktif", "pasif"):
        raise HTTPException(422, "Durum aktif ya da pasif olmalı.")
    for i in istek.idler:
        sirket_kaydi(db, Santiye, i, k).durum = istek.durum
    db.commit()
    return {"ok": True}


@router.delete("/santiyeler/{santiye_id}")
def santiye_sil(santiye_id: int, db: Session = Depends(get_db), k: Kullanici = Depends(yazabilir)):
    s = sirket_kaydi(db, Santiye, santiye_id, k)
    if neden := bagli_kayitlar(db, santiye_id=s.id):
        raise HTTPException(409, f"{neden} var, silinemez.")
    db.delete(s)
    db.commit()
    return {"ok": True}


# --- Firma bilgileri ve kullanıcılar ---------------------------------------

SIRKET_ALANLARI = ("unvan", "vkn", "vergi_dairesi", "adres", "telefon", "eposta", "iban", "fatura_seri")
ROLLER = {"sahip": "Sahip (her şey)", "muhasebeci": "Muhasebeci (kayıt girer)", "izleyici": "İzleyici (yalnız görür)",
          "uye": "Üye (işaretlenen bölümler)"}


def sahip(k: Kullanici = Depends(aktif_kullanici)) -> Kullanici:
    if k.rol != "sahip":
        raise HTTPException(403, "Bu işlemi yalnız şirket sahibi yapabilir.")
    return k


@router.get("/sirket")
def sirket_bilgisi(db: Session = Depends(get_db), k: Kullanici = Depends(aktif_kullanici)):
    s = db.get(Sirket, k.sirket_id)
    return {a: getattr(s, a) for a in SIRKET_ALANLARI}


@router.put("/sirket")
def sirket_guncelle(veri: schemas.SirketBilgisi, db: Session = Depends(get_db), k: Kullanici = Depends(sahip)):
    s = db.get(Sirket, k.sirket_id)
    for a, v in veri.model_dump().items():
        setattr(s, a, (v.strip() or None) if isinstance(v, str) else v)
    if not s.unvan:
        raise HTTPException(422, "Ünvan boş olamaz.")
    s.fatura_seri = s.fatura_seri.upper() if s.fatura_seri else None
    if s.fatura_seri and not (len(s.fatura_seri) == 3 and s.fatura_seri.isalnum()):
        raise HTTPException(422, "Fatura serisi 3 harf/rakam olmalı (ör. AFS).")
    db.commit()
    return {a: getattr(s, a) for a in SIRKET_ALANLARI}


@router.get("/kullanicilar")
def kullanicilar(db: Session = Depends(get_db), k: Kullanici = Depends(aktif_kullanici)):
    return {"roller": ROLLER, "bolumler": yetki.BOLUMLER, "duzeyler": yetki.DUZEYLER, "kullanicilar": [
        {"id": x.id, "ad": x.ad, "eposta": x.eposta, "rol": x.rol, "ben": x.id == k.id, "yetkiler": yetki.yetkileri(x)}
        for x in db.scalars(select(Kullanici).where(Kullanici.sirket_id == k.sirket_id).order_by(Kullanici.id))]}


@router.post("/kullanicilar")
def kullanici_ekle(veri: schemas.KullaniciGiris, db: Session = Depends(get_db), k: Kullanici = Depends(sahip)):
    eposta = veri.eposta.strip().lower()
    if veri.rol not in ROLLER:
        raise HTTPException(422, "Geçersiz rol.")
    if not eposta or len(veri.sifre) < 6:
        raise HTTPException(422, "E-posta gerekli, şifre en az 6 karakter olmalı.")
    if db.scalar(select(Kullanici).where(Kullanici.eposta == eposta)):
        raise HTTPException(409, "Bu e-posta ile kayıtlı bir kullanıcı var.")
    x = Kullanici(eposta=eposta, ad=veri.ad.strip(), sifre_hash=sifre_hashle(veri.sifre), sirket_id=k.sirket_id, rol=veri.rol)
    if veri.yetkiler is not None and veri.rol != "sahip":
        x.rol, x.yetkiler = "uye", yetki.temizle(veri.yetkiler)
    db.add(x)
    db.commit()
    return {"id": x.id}


@router.put("/kullanicilar/{kullanici_id}")
def kullanici_rol(kullanici_id: int, veri: dict, db: Session = Depends(get_db), k: Kullanici = Depends(sahip)):
    x = sirket_kaydi(db, Kullanici, kullanici_id, k)
    if veri.get("rol") and veri["rol"] not in ROLLER:
        raise HTTPException(422, "Geçersiz rol.")
    if x.id == k.id and veri.get("rol") and veri["rol"] != "sahip":
        raise HTTPException(422, "Kendi sahip yetkinizi kaldıramazsınız.")
    if veri.get("rol"):
        x.rol = veri["rol"]
        if x.rol != "uye":
            x.yetkiler = None  # rolün varsayılan yetkileri
    if veri.get("yetkiler") is not None and x.rol != "sahip":
        x.rol, x.yetkiler = "uye", yetki.temizle(veri["yetkiler"])
    if veri.get("sifre"):
        if len(veri["sifre"]) < 6:
            raise HTTPException(422, "Şifre en az 6 karakter olmalı.")
        x.sifre_hash = sifre_hashle(veri["sifre"])
    db.commit()
    return {"ok": True}


@router.delete("/kullanicilar/{kullanici_id}")
def kullanici_sil(kullanici_id: int, db: Session = Depends(get_db), k: Kullanici = Depends(sahip)):
    x = sirket_kaydi(db, Kullanici, kullanici_id, k)
    if x.id == k.id:
        raise HTTPException(422, "Kendinizi silemezsiniz.")
    from ..models import Oturum
    db.query(Oturum).filter(Oturum.kullanici_id == x.id).delete()
    db.delete(x)
    db.commit()
    return {"ok": True}
