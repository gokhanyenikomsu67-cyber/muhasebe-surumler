"""Kredi kartı ekstresi işleme: harcamalar işyeri carisine ödeme, iadeler tahsilat, faiz/ücretler
MUHTELİF BANKA İŞLEMLERİ, nakit avans kasaya, kart borcu ödemesi banka hesabından virman olarak işlenir.
İşyeri için kullanıcının seçtiği cari öğrenilir; sonraki ekstrelerde aynı işyeri o cariye gider."""
from datetime import date, timedelta

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import kart, kural
from ..kart import kart_ekstresi_mi, tespit_metni
from ..auth import yazabilir
from ..db import get_db
from ..models import BankaHesabi, Cari, Hareket, IsyeriEslesme, Kullanici, Sirket
from ..yukleme import dosyayi_oku

router = APIRouter(prefix="/api")

KART = "kredi_karti"
GUN = 5  # kart ödemesinin bankadan çıkışı ile karta geçişi arasında olabilecek gün farkı
_ODEME_OLABILIR = ("virman", "kredi_odeme", "odeme", "diger", "masraf")


def tl(x: float) -> str:
    return f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def kartlar(db: Session, sirket_id: int) -> list[BankaHesabi]:
    return list(db.scalars(select(BankaHesabi).where(BankaHesabi.sirket_id == sirket_id, BankaHesabi.tur == KART)))


def odeme_karti(kart_listesi: list[BankaHesabi], aciklama: str, banka: str | None = None) -> BankaHesabi | None:
    """Banka ekstresindeki kart borcu ödemesinin hangi karta yapıldığı: açıklamadaki son 4 haneden; numara yazmıyorsa
    ödeyen bankanın tek kartı (banka bilinmiyorsa tek kart varsa o). Başka bankanın kartı tahmin edilmez."""
    if not kart_listesi or not kart.kart_odemesi_mi(aciklama):
        return None
    son4 = kart.kart_son4(aciklama)
    for k in kart_listesi:
        if k.kart_no and son4 and k.kart_no[-4:] == son4:
            return k
    if son4:
        return None
    adaylar = [k for k in kart_listesi if k.banka == banka] if banka else kart_listesi
    return adaylar[0] if len(adaylar) == 1 else None


def kart_ilgili(db: Session, *hesap_idleri: int | None) -> bool:
    return any(i and (b := db.get(BankaHesabi, i)) is not None and b.tur == KART for i in hesap_idleri)


def isyeri_ogren(db: Session, h: Hareket) -> None:
    """Kart satırının carisi seçildiyse/onaylandıysa işyeri -> cari eşleşmesini hatırlar."""
    anahtar = (h.ai_okuma or {}).get("isyeri_anahtari")
    if not anahtar or not h.cari_id:
        return
    e = db.scalar(select(IsyeriEslesme).where(IsyeriEslesme.sirket_id == h.sirket_id, IsyeriEslesme.anahtar == anahtar))
    if e:
        e.cari_id = h.cari_id
    else:
        db.add(IsyeriEslesme(sirket_id=h.sirket_id, anahtar=anahtar, cari_id=h.cari_id))


def kart_hesabi(db: Session, sirket_id: int, son4: str | None, banka: str | None) -> tuple[BankaHesabi, bool]:
    """Ekstredeki kartın hesabı: kart numarasının son 4 hanesinden bulunur, yoksa (tek kart tanımlıysa o) yeni açılır."""
    liste = kartlar(db, sirket_id)
    for b in liste:
        if son4 and b.kart_no and b.kart_no[-4:] == son4:
            return b, False
    bos = [b for b in liste if not b.kart_no]
    if len(bos) == 1 or (not son4 and len(liste) == 1):
        b = bos[0] if bos else liste[0]
        if son4 and not b.kart_no:
            b.kart_no = f"**** **** **** {son4}"
        return b, False
    b = BankaHesabi(sirket_id=sirket_id, tur=KART, ad=f"{banka or 'Kredi Kartı'} Kart {son4 or ''}".strip(), banka=banka,
                    kart_no=f"**** **** **** {son4}" if son4 else None)
    db.add(b)
    db.flush()
    return b, True


def _banka_odemesi(db: Session, hesap: BankaHesabi, tarih: date, tutar: float) -> Hareket | None:
    """Kart ekstresindeki ödemenin banka hesabındaki çıkışı (karşı hesabın ekstresi önceden yüklendiyse)."""
    q = select(Hareket).join(BankaHesabi, Hareket.banka_hesap_id == BankaHesabi.id).where(
        Hareket.sirket_id == hesap.sirket_id, BankaHesabi.tur != KART, Hareket.yon == "cikis",
        func.abs(Hareket.tutar - tutar) < 0.005, Hareket.tarih.between(tarih - timedelta(days=GUN), tarih + timedelta(days=1)),
        Hareket.tur.in_(_ODEME_OLABILIR), Hareket.cek_id.is_(None), Hareket.bagli_hareket_id.is_(None))
    adaylar = []
    for h in db.scalars(q):
        hedef = (h.ai_okuma or {}).get("karsi_hesap_id")
        if (hedef == hesap.id or (not hedef and kart.kart_odemesi_mi(h.aciklama))) and not db.scalar(
                select(Hareket.id).where(Hareket.bagli_hareket_id == h.id, Hareket.banka_hesap_id != hesap.id).limit(1)):
            adaylar.append(h)
    adaylar.sort(key=lambda h: abs((h.tarih - tarih).days))
    return adaylar[0] if adaylar else None


def _eslenen_kayit(db: Session, hesap: BankaHesabi, tarih: date, yon: str, tutar: float) -> Hareket | None:
    """Bankadaki ödemeden önceden karta yazılmış eşleme kaydı (ekstre satırı bunun yerine geçer)."""
    adaylar = list(db.scalars(select(Hareket).where(
        Hareket.banka_hesap_id == hesap.id, Hareket.kaynak == "esleme", Hareket.ekstre_anahtari.is_(None),
        Hareket.yon == yon, func.abs(Hareket.tutar - tutar) < 0.005,
        Hareket.tarih.between(tarih - timedelta(days=GUN), tarih + timedelta(days=GUN)))))
    adaylar.sort(key=lambda h: abs((h.tarih - tarih).days))
    return adaylar[0] if adaylar else None


def _ayni_banka_hesabi(db: Session, hesap: BankaHesabi) -> BankaHesabi | None:
    """Kartla aynı bankadaki tek TL banka hesabı (kart borcu genelde oradan ödenir)."""
    if not hesap.banka:
        return None
    adaylar = [b for b in db.scalars(select(BankaHesabi).where(BankaHesabi.sirket_id == hesap.sirket_id, BankaHesabi.tur != KART,
                                                               BankaHesabi.para_birimi == hesap.para_birimi))
               if kural.sade(b.banka or kural.iban_banka(b.iban) or "") == kural.sade(hesap.banka)]
    return adaylar[0] if len(adaylar) == 1 else None


def kart_ekstresi_isle(db: Session, k: Kullanici, hesap: BankaHesabi, okunan: dict, notlar: list[str]) -> dict:
    from .banka import MUHTELIF_CARI, atlanan_nedeni, ekstre_anahtari, ekstre_tazele, esle, muhtelif_cari_id
    sirket_unvan = db.get(Sirket, k.sirket_id).unvan
    kendi = kural.kendi_kelimeleri(sirket_unvan)
    cariler = [c for c in db.scalars(select(Cari).where(Cari.sirket_id == k.sirket_id))
               if not (kendi and kural.kendi_kelimeleri(c.unvan) == kendi)]
    cari_listesi = [{"id": c.id, "unvan": c.unvan, "vkn": c.vkn, "iban": c.iban, "eski_adlar": c.eski_adlar} for c in cariler]
    ogrenilen = {e.anahtar: e.cari_id for e in db.scalars(select(IsyeriEslesme).where(IsyeriEslesme.sirket_id == k.sirket_id))}
    cari_idleri = {c["id"] for c in cari_listesi}
    yeni_cari = 0
    acilan: dict[str, int] = {}

    def isyeri_carisi(isyeri: str, anahtar: str) -> int:
        nonlocal yeni_cari
        if ogrenilen.get(anahtar) in cari_idleri:
            return ogrenilen[anahtar]
        if anahtar in acilan:
            return acilan[anahtar]
        cari_id = kural.cari_eslestir(isyeri, cari_listesi)
        if not cari_id:
            benzer = [c["id"] for c in cari_listesi if kural.benzer_unvan(isyeri, c["unvan"])]
            cari_id = benzer[0] if len(benzer) == 1 else None
        if not cari_id:
            c = Cari(sirket_id=k.sirket_id, unvan=isyeri, tur="tedarikci", ad_otomatik=True)
            db.add(c)
            db.flush()
            cari_listesi.append({"id": c.id, "unvan": c.unvan, "vkn": None, "iban": None})
            cari_idleri.add(c.id)
            yeni_cari += 1
            cari_id = c.id
        acilan[anahtar] = cari_id
        return cari_id

    muhtelif_id = None

    def muhtelif() -> int:
        nonlocal muhtelif_id, yeni_cari
        if muhtelif_id is None:
            yeni_cari += not any(kural.sade(c["unvan"]) == kural.sade(MUHTELIF_CARI) for c in cari_listesi)
            muhtelif_id = muhtelif_cari_id(db, k.sirket_id)
        return muhtelif_id

    mevcut = set(db.scalars(select(Hareket.ekstre_anahtari).where(Hareket.banka_hesap_id == hesap.id,
                                                                  Hareket.ekstre_anahtari.is_not(None))))
    ilk_ekstre = not mevcut
    eklenen = atlanan = eslesen = 0
    atlananlar: list[str] = []
    islenemeyen: list[str] = []
    tekrar: dict[tuple, int] = {}
    for s in okunan["satirlar"]:
        tarih = date.fromisoformat(s["tarih"])
        tutar = float(s["tutar"])
        if not tutar:
            islenemeyen.append(f"{tarih:%d.%m.%Y} tutarı okunamadı: {s['aciklama']}")
            continue
        # Aynı gün aynı işyerinden aynı tutarlı iki harcama ayrı satırdır; ekstre yeniden yüklenince yine atlanır.
        sira = tekrar[(s["tarih"], s["aciklama"], tutar)] = tekrar.get((s["tarih"], s["aciklama"], tutar), 0) + 1
        anahtar = ekstre_anahtari(hesap.id, s["tarih"], tutar, s["aciklama"] + (f" #{sira}" if sira > 1 else ""), s.get("bakiye"))
        if anahtar in mevcut:
            atlanan += 1
            atlananlar.append(anahtar)
            continue
        mevcut.add(anahtar)
        yon = "giris" if tutar > 0 else "cikis"
        tur = s["onerilen_tur"]
        ek = {"bakiye": s.get("bakiye")}
        if s.get("taksit"):
            ek["taksit"] = s["taksit"]
        cari_id = None
        if tur == "virman":
            karsilik = _eslenen_kayit(db, hesap, tarih, yon, abs(tutar))
            banka_h = None if karsilik else _banka_odemesi(db, hesap, tarih, abs(tutar))
            if banka_h is not None:
                banka_h.tur, banka_h.cari_id = "virman", None
                banka_h.ai_okuma = {**(banka_h.ai_okuma or {}), "karsi_hesap_id": hesap.id}
                ek["karsi_hesap_id"] = banka_h.banka_hesap_id
                if banka_h.durum == "onayli":
                    esle(db, banka_h)  # karttaki karşılığı yazılır; aşağıda bu ekstre satırı onun yerine geçer
                    db.flush()
                    karsilik = _eslenen_kayit(db, hesap, tarih, yon, abs(tutar))
            if karsilik is None and banka_h is None and (varsayilan := _ayni_banka_hesabi(db, hesap)):
                ek["karsi_hesap_id"] = varsayilan.id  # "hesaptan otomatik ödeme": kartın bankasındaki tek hesap
            if karsilik is not None:
                karsilik.kaynak, karsilik.ekstre_anahtari, karsilik.tarih = "ekstre", anahtar, tarih
                karsilik.aciklama, karsilik.ai_okuma = s["aciklama"], ek
                eslesen += 1
                continue
        elif tur in ("odeme", "tahsilat") and s.get("isyeri"):
            ek["isyeri"] = s["isyeri"]
            ek["isyeri_anahtari"] = kart.isyeri_anahtari(s["isyeri"]) or kural.ad_anahtari(s["isyeri"])
            cari_id = isyeri_carisi(s["isyeri"], ek["isyeri_anahtari"])
        elif tur in ("banka_masrafi", "diger"):
            cari_id = muhtelif()
        db.add(Hareket(sirket_id=k.sirket_id, durum="taslak", tarih=tarih, yon=yon, tur=tur, tutar=abs(tutar), cari_id=cari_id,
                       banka_hesap_id=hesap.id, aciklama=s["aciklama"], kaynak="ekstre", ekstre_anahtari=anahtar, ai_okuma=ek))
        eklenen += 1

    if ilk_ekstre and not float(hesap.acilis_bakiyesi or 0):
        hesap.acilis_ekstreden = True  # açılış = önceki dönem borcu
    if okunan.get("son_odeme"):
        hesap.son_odeme_tarihi = date.fromisoformat(okunan["son_odeme"])
    if okunan.get("asgari") is not None:
        hesap.asgari_odeme = okunan["asgari"]
    ekstre_tazele(db, hesap)
    if okunan.get("donem_borcu") is not None:
        notlar.append(f"Dönem borcu {tl(okunan['donem_borcu'])} TL"
                      + (f", son ödeme {date.fromisoformat(okunan['son_odeme']):%d.%m.%Y}" if okunan.get("son_odeme") else "") + ".")
    else:
        notlar.append("Ekstrede dönem borcu okunamadı; kart bakiyesi ekstreyle karşılaştırılamaz.")
    if okunan.get("fark"):
        islenemeyen.append(f"Satırların toplamı dönem borcuyla {tl(abs(okunan['fark']))} TL tutmuyor; "
                           "okunamayan satır olabilir, ekstreyle karşılaştırın.")
    db.commit()
    return {"eklenen": eklenen, "atlanan": atlanan, "atlanan_nedeni": atlanan_nedeni(db, hesap.id, atlananlar),
            "eslesen": eslesen, "yeni_cari": yeni_cari, "hesap": hesap.ad, "yeni_hesap": [], "islenemeyen": islenemeyen, "notlar": " ".join(n for n in notlar if n), "kart": True}


def oku(icerik: bytes, mime: str) -> dict:
    try:
        return kart.ekstre_oku(icerik, mime)
    except kural.KuralHatasi as e:
        raise HTTPException(422, str(e)) from e


@router.post("/kredi-karti-ekstresi")
async def kart_ekstresi_yukle(dosya: UploadFile = File(...), db: Session = Depends(get_db), k: Kullanici = Depends(yazabilir)):
    """Kart ekstresini yükler; kart hesabı kart numarasının son 4 hanesinden bulunur, yoksa açılır."""
    from .banka import dosya_turu
    icerik = dosyayi_oku(dosya)
    mime = dosya_turu(dosya)
    okunan = oku(icerik, mime)
    # Banka hesap ekstresi (kart numarası yok, kart ekstresi izleri yok) kart hesabına işlenmez
    if not okunan.get("kart_son4") and not kart_ekstresi_mi(tespit_metni(icerik, mime)):
        raise HTTPException(422, "Bu dosya kredi kartı ekstresi değil, banka hesap ekstresi (kart numarası ve dönem borcu yok). "
                                 "Hesap listesinden ilgili banka hesabını seçip yükleyin. Hiçbir satır eklenmedi.")
    hesap, yeni = kart_hesabi(db, k.sirket_id, okunan.get("kart_son4"), okunan.get("banka"))
    notlar = [f"Yeni kart hesabı açıldı: {hesap.ad}."] if yeni else []
    sonuc = kart_ekstresi_isle(db, k, hesap, okunan, notlar)
    sonuc["yeni_hesap"] = [hesap.ad] if yeni else []
    return sonuc
