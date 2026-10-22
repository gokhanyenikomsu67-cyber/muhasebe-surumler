"""Zaman kazandıran kısayollar: hızlı arama, ödeme takvimi / nakit akışı, düzenli ödemeler, fatura kopyalama."""
import calendar
import re
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import schemas
from ..auth import aktif_kullanici, yazabilir
from ..db import get_db
from ..hesap import banka_bakiyeleri, kasa_bakiyesi
from ..models import ACIK_CEK_DURUMLARI, BankaHesabi, Cari, Cek, DuzenliOdeme, Fatura, Hareket, Kullanici, Santiye
from .faturalar import cikis, kalemleri_yaz, sonraki_no
from .mali import yaslandirma_veri
from .temel import sirket_kaydi

router = APIRouter(prefix="/api")


# --- Hızlı arama -------------------------------------------------------------

def _sade(metin) -> str:
    """Büyük-küçük harf ve Türkçe karakter farkını yok sayar."""
    m = str(metin or "").replace("I", "ı").replace("İ", "i").lower()
    return m.translate(str.maketrans("ıçğöşü", "icgosu"))


def _tutar(q: str) -> float | None:
    """'12.500,50' / '12500.5' / '12500' gibi yazılan tutar."""
    q = q.strip().replace(" ", "").replace("₺", "").replace("TL", "")
    if not re.fullmatch(r"\d[\d.,]*", q):
        return None
    if "," in q:
        q = q.replace(".", "").replace(",", ".")
    elif q.count(".") > 1 or re.fullmatch(r"\d{1,3}(\.\d{3})+", q):
        q = q.replace(".", "")
    try:
        return float(q)
    except ValueError:
        return None


@router.get("/ara")
def hizli_ara(q: str = "", db: Session = Depends(get_db), k: Kullanici = Depends(aktif_kullanici)):
    """Tek kutudan arama: cari (ünvan, VKN, telefon), fatura (no, cari, tutar), şantiye, çek (no, keşideci, tutar)."""
    aranan, tutar, sinir = _sade(q.strip()), _tutar(q), 8
    sonuc = {"cariler": [], "faturalar": [], "santiyeler": [], "cekler": []}
    if len(aranan) < 2 and tutar is None:
        return sonuc
    icinde = lambda *alanlar: aranan and any(aranan in _sade(a) for a in alanlar if a)  # noqa: E731
    ayni_tutar = lambda v: tutar is not None and abs(float(v or 0) - tutar) < 0.01  # noqa: E731
    for c in db.scalars(select(Cari).where(Cari.sirket_id == k.sirket_id).order_by(Cari.unvan)):
        if icinde(c.unvan, c.vkn, c.telefon):
            sonuc["cariler"].append({"id": c.id, "unvan": c.unvan, "vkn": c.vkn})
    for s in db.scalars(select(Santiye).where(Santiye.sirket_id == k.sirket_id).order_by(Santiye.ad)):
        if icinde(s.ad):
            sonuc["santiyeler"].append({"id": s.id, "ad": s.ad})
    for f in db.scalars(select(Fatura).where(Fatura.sirket_id == k.sirket_id)
                        .order_by(Fatura.tarih.desc().nulls_last(), Fatura.id.desc())):
        if icinde(f.fatura_no, f.cari.unvan if f.cari else None) or ayni_tutar(f.genel_toplam):
            sonuc["faturalar"].append({"id": f.id, "fatura_no": f.fatura_no, "tarih": f.tarih, "yon": f.yon, "durum": f.durum,
                                       "cari": f.cari.unvan if f.cari else None, "genel_toplam": float(f.genel_toplam)})
    for c in db.scalars(select(Cek).where(Cek.sirket_id == k.sirket_id).order_by(Cek.vade.desc())):
        if icinde(c.cek_no, c.kesideci, c.cari.unvan if c.cari else None) or ayni_tutar(c.tutar):
            sonuc["cekler"].append({"id": c.id, "cek_no": c.cek_no, "yon": c.yon, "vade": c.vade, "tutar": float(c.tutar),
                                    "cari": c.cari.unvan if c.cari else c.kesideci})
    return {ad: liste[:sinir] for ad, liste in sonuc.items()}


# --- Düzenli ödemeler --------------------------------------------------------

class DuzenliGiris(BaseModel):
    ad: str
    yon: str = "cikis"
    tutar: float
    gun: int = 1
    periyot: int = 1
    baslangic: date
    bitis: date | None = None
    cari_id: int | None = None
    banka_hesap_id: int | None = None
    aciklama: str | None = None
    aktif: bool = True


def _donem(t: date) -> str:
    return f"{t.year:04d}-{t.month:02d}"


def vadeler(d: DuzenliOdeme, bitis: date):
    """Başlangıçtan itibaren her periyotta bir vade günü (ay kısaysa ayın son günü)."""
    yil, ay, adim = d.baslangic.year, d.baslangic.month, max(int(d.periyot or 1), 1)
    while True:
        gun = min(max(int(d.gun or 1), 1), calendar.monthrange(yil, ay)[1])
        t = date(yil, ay, gun)
        if t > bitis or (d.bitis and t > d.bitis):
            return
        yield t
        ay += adim
        yil, ay = yil + (ay - 1) // 12, (ay - 1) % 12 + 1


def bekleyen_vadeler(d: DuzenliOdeme, bitis: date) -> list[date]:
    """Henüz ödendi işaretlenmemiş vadeler (geçmişte kalan en çok 12 tanesi)."""
    if not d.aktif:
        return []
    liste = [t for t in vadeler(d, bitis) if not d.son_donem or _donem(t) > d.son_donem]
    gecmis = [t for t in liste if t < date.today()]
    return gecmis[-12:] + [t for t in liste if t >= date.today()]


def _duzenli_cikis(d: DuzenliOdeme) -> dict:
    sonraki = bekleyen_vadeler(d, date.today() + timedelta(days=400))
    return {"id": d.id, "ad": d.ad, "yon": d.yon, "tutar": float(d.tutar), "gun": d.gun, "periyot": d.periyot,
            "baslangic": d.baslangic, "bitis": d.bitis, "cari_id": d.cari_id, "cari_unvan": d.cari.unvan if d.cari else None,
            "banka_hesap_id": d.banka_hesap_id, "banka_hesap_ad": d.banka_hesap.ad if d.banka_hesap else None,
            "aciklama": d.aciklama, "aktif": d.aktif, "son_donem": d.son_donem,
            "sonraki_vade": sonraki[0] if sonraki else None,
            "geciken": sum(1 for t in sonraki if t < date.today())}


def _duzenli_doldur(db: Session, d: DuzenliOdeme, v: DuzenliGiris, k: Kullanici):
    if v.yon not in ("giris", "cikis"):
        raise HTTPException(400, "Yön giriş ya da çıkış olmalı.")
    if v.tutar <= 0:
        raise HTTPException(400, "Tutar sıfırdan büyük olmalı.")
    if v.cari_id:
        sirket_kaydi(db, Cari, v.cari_id, k)
    if v.banka_hesap_id:
        sirket_kaydi(db, BankaHesabi, v.banka_hesap_id, k)
    for alan, deger in v.model_dump().items():
        setattr(d, alan, deger)
    d.gun = min(max(v.gun, 1), 31)
    d.periyot = min(max(v.periyot, 1), 12)


@router.get("/duzenli-odemeler")
def duzenli_liste(db: Session = Depends(get_db), k: Kullanici = Depends(aktif_kullanici)):
    return [_duzenli_cikis(d) for d in db.scalars(select(DuzenliOdeme).where(DuzenliOdeme.sirket_id == k.sirket_id)
                                                  .order_by(DuzenliOdeme.gun, DuzenliOdeme.ad))]


@router.post("/duzenli-odemeler")
def duzenli_ekle(v: DuzenliGiris, db: Session = Depends(get_db), k: Kullanici = Depends(yazabilir)):
    d = DuzenliOdeme(sirket_id=k.sirket_id)
    _duzenli_doldur(db, d, v, k)
    db.add(d)
    db.commit()
    return _duzenli_cikis(d)


@router.put("/duzenli-odemeler/{kayit_id}")
def duzenli_guncelle(kayit_id: int, v: DuzenliGiris, db: Session = Depends(get_db), k: Kullanici = Depends(yazabilir)):
    d = sirket_kaydi(db, DuzenliOdeme, kayit_id, k)
    _duzenli_doldur(db, d, v, k)
    db.commit()
    return _duzenli_cikis(d)


@router.delete("/duzenli-odemeler/{kayit_id}")
def duzenli_sil(kayit_id: int, db: Session = Depends(get_db), k: Kullanici = Depends(yazabilir)):
    db.delete(sirket_kaydi(db, DuzenliOdeme, kayit_id, k))
    db.commit()
    return {"ok": True}


class OdendiGiris(BaseModel):
    hareket: bool = False  # True: banka/kasa hareketi de kaydedilir; False: yalnız işaretlenir (ekstreden gelecek)
    banka_hesap_id: int | None = None
    tarih: date | None = None


@router.post("/duzenli-odemeler/{kayit_id}/odendi")
def duzenli_odendi(kayit_id: int, v: OdendiGiris, db: Session = Depends(get_db), k: Kullanici = Depends(yazabilir)):
    """Ödenmemiş en eski vadeyi ödendi sayar; istenirse tahsilat/ödeme hareketini de kaydeder."""
    d = sirket_kaydi(db, DuzenliOdeme, kayit_id, k)
    bekleyen = bekleyen_vadeler(d, date.today() + timedelta(days=400))
    if not bekleyen:
        raise HTTPException(400, "Bu kaydın ödenecek vadesi yok.")
    vade = bekleyen[0]
    d.son_donem = _donem(vade)
    if v.hareket:
        if v.banka_hesap_id:
            sirket_kaydi(db, BankaHesabi, v.banka_hesap_id, k)
        tur = ("tahsilat" if d.yon == "giris" else "odeme") if d.cari_id else ("diger" if d.yon == "giris" else "masraf")
        db.add(Hareket(sirket_id=k.sirket_id, durum="onayli", tarih=v.tarih or date.today(), yon=d.yon, tur=tur,
                       tutar=d.tutar, cari_id=d.cari_id, banka_hesap_id=v.banka_hesap_id, kaynak="elle",
                       aciklama=f"{d.ad} ({vade.strftime('%m.%Y')})"))
    db.commit()
    return _duzenli_cikis(d)


# --- Ödeme takvimi ve nakit akışı -------------------------------------------

def nakit_akisi_veri(db: Session, k: Kullanici, gun: int = 90) -> dict:
    """Bugünkü banka + kasa bakiyesinden başlayıp açık fatura vadeleri, çekler ve düzenli ödemelerle
    önümüzdeki haftaların beklenen bakiyesi. Vadesi geçmişler bugüne sayılır."""
    bugun = date.today()
    son = bugun + timedelta(days=max(7, min(gun, 366)))
    kalemler = []

    def ekle(tarih_, yon, tur, aciklama, cari, tutar, **ref):
        kalemler.append({"tarih": tarih_, "yon": yon, "tur": tur, "aciklama": aciklama, "cari": cari,
                         "tutar": round(float(tutar), 2), "gecikmis": tarih_ < bugun,
                         "gecikme_gun": (bugun - tarih_).days if tarih_ < bugun else 0, **ref})

    for a in yaslandirma_veri(db, k, bugun)["acik_faturalar"]:
        if a["vade"] and a["vade"] <= son:
            ekle(a["vade"], "giris" if a["tur"] == "alacak" else "cikis", "fatura",
                 f"Fatura {a['belge'] or ''}".strip(), a["unvan"], a["acik_tutar"], fatura_id=a["fatura_id"], cari_id=a["cari_id"])
    for c in db.scalars(select(Cek).where(Cek.sirket_id == k.sirket_id, Cek.durum.in_(ACIK_CEK_DURUMLARI),
                                          Cek.vade <= son)):
        ekle(c.vade, "giris" if c.yon == "alinan" else "cikis", "cek", f"{'Alınan' if c.yon == 'alinan' else 'Verilen'} çek {c.cek_no or ''}".strip(),
             c.cari.unvan if c.cari else c.kesideci, c.tutar, cek_id=c.id, cek_yon=c.yon)
    for d in db.scalars(select(DuzenliOdeme).where(DuzenliOdeme.sirket_id == k.sirket_id, DuzenliOdeme.aktif.is_(True))):
        for t in bekleyen_vadeler(d, son):
            ekle(t, d.yon, "duzenli", d.ad, d.cari.unvan if d.cari else None, d.tutar, duzenli_id=d.id)
    # Kredi kartı borcu eldeki paradan düşülmez; ekstrenin son ödeme gününde ödenecek çıkış olarak görünür.
    kartlar = list(db.scalars(select(BankaHesabi).where(BankaHesabi.sirket_id == k.sirket_id, BankaHesabi.tur == "kredi_karti")))
    for b in kartlar:
        if b.son_odeme_tarihi and b.ekstre_bakiye is not None and float(b.ekstre_bakiye) < 0 and b.son_odeme_tarihi <= son:
            odenen = sum(float(h.tutar) for h in db.scalars(select(Hareket).where(
                Hareket.banka_hesap_id == b.id, Hareket.durum == "onayli", Hareket.yon == "giris", Hareket.tarih > b.ekstre_tarihi)))
            if (kalan := -float(b.ekstre_bakiye) - odenen) > 0.005:
                ekle(b.son_odeme_tarihi, "cikis", "kart", f"{b.ad} kart borcu", None, kalan, banka_hesap_id=b.id)
    kalemler.sort(key=lambda x: (x["tarih"], x["yon"] == "cikis"))

    kart_idleri = {b.id for b in kartlar}
    mevcut = round(sum(v for i, v in banka_bakiyeleri(db, k.sirket_id).items() if i not in kart_idleri)
                   + kasa_bakiyesi(db, k.sirket_id), 2)
    donemler, bakiye = [], mevcut
    pazartesi = bugun - timedelta(days=bugun.weekday())
    araliklar = [("Vadesi geçmiş", date.min, bugun - timedelta(days=1))]
    bas = bugun
    while bas <= son:
        bit = min(pazartesi + timedelta(days=6), son)
        araliklar.append((f"{bas.strftime('%d.%m')} - {bit.strftime('%d.%m')}", bas, bit))
        pazartesi += timedelta(days=7)
        bas = pazartesi
    for ad, b, s in araliklar:
        icinde = [x for x in kalemler if b <= x["tarih"] <= s]
        giris = round(sum(x["tutar"] for x in icinde if x["yon"] == "giris"), 2)
        cikis_ = round(sum(x["tutar"] for x in icinde if x["yon"] == "cikis"), 2)
        if ad == "Vadesi geçmiş" and not icinde:
            continue
        bakiye = round(bakiye + giris - cikis_, 2)
        donemler.append({"ad": ad, "baslangic": None if b == date.min else b, "bitis": s, "giris": giris, "cikis": cikis_,
                         "bakiye": bakiye, "adet": len(icinde)})

    def toplam(yon, sart):
        return round(sum(x["tutar"] for x in kalemler if x["yon"] == yon and sart(x)), 2)
    hafta = bugun + timedelta(days=7)
    ay = bugun + timedelta(days=30)
    return {
        "bugun": bugun, "mevcut": mevcut, "kalemler": kalemler, "donemler": donemler,
        "ozet": {"gecikmis_giris": toplam("giris", lambda x: x["gecikmis"]), "gecikmis_cikis": toplam("cikis", lambda x: x["gecikmis"]),
                 "hafta_giris": toplam("giris", lambda x: bugun <= x["tarih"] <= hafta),
                 "hafta_cikis": toplam("cikis", lambda x: bugun <= x["tarih"] <= hafta),
                 "ay_giris": toplam("giris", lambda x: bugun <= x["tarih"] <= ay),
                 "ay_cikis": toplam("cikis", lambda x: bugun <= x["tarih"] <= ay),
                 "en_dusuk_bakiye": min([mevcut] + [d["bakiye"] for d in donemler])},
    }


@router.get("/raporlar/nakit-akisi")
def nakit_akisi(gun: int = 90, db: Session = Depends(get_db), k: Kullanici = Depends(aktif_kullanici)):
    return nakit_akisi_veri(db, k, gun)


@router.get("/excel/nakit-akisi")
def excel_nakit_akisi(gun: int = 90, db: Session = Depends(get_db), k: Kullanici = Depends(aktif_kullanici)):
    from .raporlar import _excel
    v = nakit_akisi_veri(db, k, gun)
    turler = {"fatura": "Fatura", "cek": "Çek", "duzenli": "Düzenli ödeme"}
    satirlar = [[x["tarih"], "Gecikmiş" if x["gecikmis"] else "", turler[x["tur"]], x["aciklama"], x["cari"],
                 x["tutar"] if x["yon"] == "giris" else None, x["tutar"] if x["yon"] == "cikis" else None] for x in v["kalemler"]]
    return _excel("Ödeme Takvimi", ["Vade", "Durum", "Tür", "Açıklama", "Cari", "Tahsil Edilecek", "Ödenecek"],
                  satirlar, f"odeme-takvimi-{v['bugun']}")


# --- Fatura kopyalama --------------------------------------------------------

@router.post("/faturalar/{fatura_id}/kopyala", response_model=schemas.FaturaCikis)
def fatura_kopyala(fatura_id: int, db: Session = Depends(get_db), k: Kullanici = Depends(yazabilir)):
    """Aynı cari, şantiye ve kalemlerle bugün tarihli yeni taslak fatura (satışta sıradaki numarayla)."""
    eski = sirket_kaydi(db, Fatura, fatura_id, k)
    bugun = date.today()
    f = Fatura(sirket_id=k.sirket_id, yon=eski.yon, durum="taslak", tarih=bugun,
               vade=bugun + (eski.vade - eski.tarih) if eski.vade and eski.tarih else None,
               fatura_no=sonraki_no(eski.yon, db, k)["fatura_no"] if eski.yon == "giden" else None,
               cari_id=eski.cari_id, santiye_id=eski.santiye_id, gider_turu=eski.gider_turu, tevkifat=eski.tevkifat or 0, stopaj=eski.stopaj or 0,
               diger_vergiler=eski.diger_vergiler or 0, yuvarlama=0, para_birimi=eski.para_birimi, aciklama=eski.aciklama)
    kalemleri_yaz(f, [schemas.KalemGiris(
        aciklama=kl.aciklama, miktar=float(kl.miktar), birim=kl.birim, birim_fiyat=float(kl.birim_fiyat),
        kdv_orani=float(kl.kdv_orani), tutar=float(kl.tutar), santiye_id=kl.santiye_id,
        tevkifat_orani=float(kl.tevkifat_orani or 0), tevkifat_kodu=kl.tevkifat_kodu, stopaj_orani=float(kl.stopaj_orani or 0),
        kdv_tutari=float(kl.kdv_tutari) if kl.kdv_tutari is not None else None,
        iskonto_orani=float(kl.iskonto_orani or 0), iskonto_tutari=float(kl.iskonto_tutari or 0)) for kl in eski.kalemler])
    db.add(f)
    db.commit()
    return cikis(f)
