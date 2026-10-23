"""WhatsApp botu: numaralar, bağlantı durumu, programdan soru sorma ve köprünün (whatsapp/kopru.mjs) mesaj ucu."""
import hmac
import os
import threading

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import bot, kural, soru
from ..auth import aktif_kullanici
from ..db import get_db
from ..models import BotNumarasi, Kullanici
from .temel import sahip, sirket_kaydi

router = APIRouter(prefix="/api/bot")


class NumaraGiris(BaseModel):
    ad: str
    telefon: str | None = None
    kimlik: str | None = None
    kullanici_id: int
    aktif: bool = True


class KopruMesaji(BaseModel):
    gonderen: str               # WhatsApp'taki kimlik (numara@s.whatsapp.net ya da gizli kimlik@lid)
    gonderen_alt: str | None = None  # öteki biçim (WhatsApp verirse)
    ad: str | None = None       # kişinin WhatsApp'taki adı
    metin: str
    grup: str | None = None     # grup adı (özel mesajda boş)
    hitap: bool = False         # bota yazıldı: @bahsedildi, botun mesajına yanıt ya da özel mesaj


class KopruDurumu(BaseModel):
    durum: str                  # qr | bagli | baglaniyor | cikis | hata
    qr: str | None = None       # QR resmi (data:image/png;base64,...)
    numara: str | None = None
    hata: str | None = None
    gruplar: list[str] | None = None  # botun içinde olduğu grupların adları


def _numara_cikis(n: BotNumarasi) -> dict:
    return {"id": n.id, "ad": n.ad, "telefon": n.telefon, "kimlik": n.kimlik, "kullanici_id": n.kullanici_id,
            "kullanici": n.kullanici.ad if n.kullanici else None, "aktif": n.aktif}


def _numara_doldur(db: Session, n: BotNumarasi, veri: NumaraGiris, k: Kullanici) -> None:
    sirket_kaydi(db, Kullanici, veri.kullanici_id, k)
    telefon, kimlik = bot.rakamlar(veri.telefon), bot.rakamlar(veri.kimlik)
    if not telefon and not kimlik:
        raise HTTPException(422, "Telefon numarası gerekli (ör. 0532 123 45 67).")
    if telefon and len(telefon) < 10:
        raise HTTPException(422, "Telefon numarası eksik görünüyor.")
    if not veri.ad.strip():
        raise HTTPException(422, "Ad gerekli.")
    n.ad, n.telefon, n.kimlik, n.kullanici_id, n.aktif = veri.ad.strip(), telefon or None, kimlik or None, veri.kullanici_id, veri.aktif


@router.get("/numaralar")
def numaralar(db: Session = Depends(get_db), k: Kullanici = Depends(sahip)):
    return [_numara_cikis(n) for n in db.scalars(select(BotNumarasi).where(BotNumarasi.sirket_id == k.sirket_id)
                                                 .order_by(BotNumarasi.id))]


@router.post("/numaralar")
def numara_ekle(veri: NumaraGiris, db: Session = Depends(get_db), k: Kullanici = Depends(sahip)):
    n = BotNumarasi(sirket_id=k.sirket_id)
    _numara_doldur(db, n, veri, k)
    db.add(n)
    db.commit()
    return _numara_cikis(n)


@router.put("/numaralar/{numara_id}")
def numara_guncelle(numara_id: int, veri: NumaraGiris, db: Session = Depends(get_db), k: Kullanici = Depends(sahip)):
    n = sirket_kaydi(db, BotNumarasi, numara_id, k)
    _numara_doldur(db, n, veri, k)
    db.commit()
    return _numara_cikis(n)


@router.delete("/numaralar/{numara_id}")
def numara_sil(numara_id: int, db: Session = Depends(get_db), k: Kullanici = Depends(sahip)):
    db.delete(sirket_kaydi(db, BotNumarasi, numara_id, k))
    db.commit()
    return {"ok": True}


@router.get("/sor")
def sor(metin: str, db: Session = Depends(get_db), k: Kullanici = Depends(aktif_kullanici)):
    """Programdaki "Soru sor" kutusu: botun vereceği cevabın aynısı, soranın yetkisiyle."""
    return {"cevap": soru.cevapla(db, k, metin) or "Anlayamadım.\n\n" + soru.YARDIM}


# --- Bağlantı (yalnız sahip) ---------------------------------------------------

def _durum() -> dict:
    return {**bot.DURUM, "acik": bool(bot.ayarlar().get("acik")), "calisiyor": bot.calisiyor_mu(),
            "kurulu": bot.kurulu_mu(), "izinli_gruplar": bot.izinli_gruplar(), "windows": os.name == "nt", "kurulum": bot.KURULUM, "mesajlar": bot.MESAJLAR}


@router.get("/durum")
def durum(k: Kullanici = Depends(sahip)):
    return _durum()


class AyarGiris(BaseModel):
    gruplar: list[str]


@router.put("/ayar")
def ayar(veri: AyarGiris, k: Kullanici = Depends(sahip)):
    bot.ayar_yaz(gruplar=[g.strip() for g in veri.gruplar if g.strip()])
    return _durum()


@router.post("/kur")
def kur(k: Kullanici = Depends(sahip)):
    if bot.KURULUM.get("durum") != "kuruluyor":
        bot.KURULUM.update(durum="kuruluyor", hata=None)
        threading.Thread(target=bot.kur, daemon=True).start()
    return _durum()


@router.post("/ac")
def ac(k: Kullanici = Depends(sahip)):
    if not bot.kurulu_mu():
        raise HTTPException(409, "Önce \"Kur\" düğmesiyle WhatsApp bağlantısını kurun.")
    bot.ayar_yaz(acik=True)
    bot.baslat()
    return _durum()


@router.post("/kapat")
def kapat(k: Kullanici = Depends(sahip)):
    bot.ayar_yaz(acik=False)
    bot.durdur()
    return _durum()


@router.post("/cikis")
def cikis(k: Kullanici = Depends(sahip)):
    bot.ayar_yaz(acik=False)
    bot.cikis_yap()
    return _durum()


# --- Köprü uçları (yalnız bu bilgisayardaki köprü, gizli anahtarla) ------------

YEREL = {"127.0.0.1", "::1", "localhost"}


def kopru(request: Request, x_bot_anahtari: str = Header(default="")) -> None:
    """Yalnız bu bilgisayardaki köprü, programın açılışta ürettiği anahtarla (gövde okunmadan önce denetlenir)."""
    yerel = request.client and request.client.host in YEREL
    if not yerel or not hmac.compare_digest(x_bot_anahtari or "", bot.ANAHTAR):
        raise HTTPException(401, "Geçersiz köprü.")


@router.post("/kopru-durum")
def kopru_durum(veri: KopruDurumu, _: None = Depends(kopru)):
    bot.DURUM.update(durum=veri.durum, qr=veri.qr if veri.durum == "qr" else None, hata=veri.hata)
    if veri.numara:
        bot.DURUM["numara"] = bot.rakamlar(veri.numara)
    if veri.gruplar is not None:
        bot.DURUM["gruplar"] = sorted(set(veri.gruplar), key=kural.tr_sira)
    if veri.durum == "cikis":  # telefondan "bağlı cihazlar"dan çıkarıldı: yeni QR için oturum silinir
        import shutil
        shutil.rmtree(bot.OTURUM, ignore_errors=True)
    return {"ok": True, "acik": bool(bot.ayarlar().get("acik"))}


@router.post("/mesaj")
def mesaj(veri: KopruMesaji, _: None = Depends(kopru), db: Session = Depends(get_db)):
    """Gelen WhatsApp yazısı. Kayıtlı ve etkin numaradan geliyorsa cevap döner; yoksa cevap yok (sessiz kalınır)."""
    adaylar = {bot.rakamlar(x) for x in (veri.gonderen, veri.gonderen_alt) if x} - {""}
    if not adaylar:
        return {"cevap": None}
    # Yalnız seçilen gruplardaki yazılara cevap verilir; özel sohbet ve başka gruplara hiçbir şey yazılmaz
    if not veri.grup or kural.ad_anahtari(veri.grup) not in {kural.ad_anahtari(g) for g in bot.izinli_gruplar()}:
        bot.mesaj_kaydet(veri.gonderen, veri.gonderen_alt, veri.ad, veri.metin,
                         f"Cevap verilmedi: {'özel sohbet' if not veri.grup else 'seçilmemiş grup (' + veri.grup + ')'}", tanindi=True)
        return {"cevap": None}
    kayit = db.scalars(select(BotNumarasi).where(BotNumarasi.aktif.is_(True))
                       .where((BotNumarasi.telefon.in_(adaylar)) | (BotNumarasi.kimlik.in_(adaylar)))).first()
    if not kayit or not kayit.kullanici:
        bot.mesaj_kaydet(veri.gonderen, veri.gonderen_alt, veri.ad, veri.metin, "Cevap verilmedi: kişi listede yok", tanindi=False)
        # Listede olmayan kişiye hiçbir şey yazılmaz (bot numarasına dışarıdan da yazılabilir); yalnız ekranda görünür
        return {"cevap": None}
    # Grupta numara yerine gizli kimlik (@lid) gelir: numarasıyla tanınan kişinin kimliği öğrenilir
    lid = next((bot.rakamlar(y) for y in (veri.gonderen, veri.gonderen_alt) if y and y.endswith("@lid")), None)
    if lid and kayit.kimlik != lid:
        kayit.kimlik = lid
        db.commit()
    k = kayit.kullanici
    db.info["kullanici_id"] = k.id
    try:
        cevap = soru.cevapla(db, k, veri.metin, sohbet=True, hitap=veri.hitap)
    except Exception as e:  # noqa: BLE001
        bot.mesaj_kaydet(veri.gonderen, veri.gonderen_alt, kayit.ad, veri.metin, f"Hata: {e}")
        return {"cevap": "Bir hata oluştu, programda WhatsApp Botu ekranına bakın."}
    finally:
        db.rollback()  # bot hiçbir şeyi değiştirmez
    bot.mesaj_kaydet(veri.gonderen, veri.gonderen_alt, kayit.ad, veri.metin,
                     "Cevap verildi" if cevap else "Cevap verilmedi: sohbet sayıldı", cevap)
    return {"cevap": cevap}
