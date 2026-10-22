"""Değişiklik geçmişi. Kayıtlı (onaylı) fatura ve para hareketleriyle çek, cari ve banka hesaplarındaki her ekleme,
değişiklik, iptal ve silme veritabanı katmanında yakalanır: kim, ne zaman, hangi alan neyken ne oldu.
Ekranların ayrıca yazması gerekmez; program kendi başına (açılış onarımı gibi) değiştirdiyse kullanıcı boş kalır."""
import logging
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

from .models import BankaHesabi, Cari, Cek, Degisiklik, Fatura, FaturaKalem, Hareket

IZLENEN = {Fatura: "fatura", Hareket: "hareket", Cek: "cek", Cari: "cari", BankaHesabi: "banka_hesabi"}
TASLAKLI = (Fatura, Hareket)  # taslakken yapılan düzenlemeler geçmişe yazılmaz, onaydan sonrakiler yazılır
ATLANAN = {"id", "sirket_id", "ai_okuma", "olusturma", "ekstre_anahtari", "kaynak_dosya", "xml_dosya", "bagli_hareket_id",
           "acilis_ekstreden", "ekstre_tarihi", "ekstre_bakiye"}
KALEM_ALANLARI = ("aciklama", "miktar", "birim_fiyat", "kdv_orani", "tutar", "kdv_tutari", "tevkifat_orani", "stopaj_orani", "iskonto_tutari",
                  "santiye_id")
ALAN_ADLARI = {
    "durum": "Durum", "tarih": "Tarih", "vade": "Vade", "tutar": "Tutar", "yon": "Yön", "tur": "Tür", "cari_id": "Cari",
    "banka_hesap_id": "Banka hesabı", "santiye_id": "Şantiye", "gider_turu": "Gider türü", "aciklama": "Açıklama",
    "fatura_no": "Fatura no", "ara_toplam": "KDV hariç", "kdv_toplam": "KDV", "tevkifat": "Tevkifat", "stopaj": "Stopaj",
    "genel_toplam": "Genel toplam", "iptal_nedeni": "İptal nedeni", "unvan": "Ünvan", "vkn": "VKN", "iban": "IBAN",
    "acilis_bakiyesi": "Açılış bakiyesi", "cek_no": "Çek no", "kalemler": "Kalemler", "kur": "Kur",
    "para_birimi": "Para birimi", "ciro_cari_id": "Ciro edilen cari",
}


def _deger(v):
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    return v


def _esit(a, b) -> bool:
    a, b = _deger(a), _deger(b)
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) < 0.005
    return a == b


def _sutunlar(obj) -> list[str]:
    return [c.key for c in inspect(obj).mapper.column_attrs if c.key not in ATLANAN]


def _son_hal(obj) -> dict:
    hal = {k: _deger(getattr(obj, k)) for k in _sutunlar(obj)}
    if isinstance(obj, Fatura):
        hal["kalemler"] = [{a: _deger(getattr(kl, a)) for a in KALEM_ALANLARI} for kl in obj.kalemler]
    return hal


def _farklar(obj) -> dict:
    durum = inspect(obj)
    fark = {}
    for k in _sutunlar(obj):
        h = durum.attrs[k].history
        if not h.has_changes():
            continue
        eski = h.deleted[0] if h.deleted else None
        yeni = h.added[0] if h.added else getattr(obj, k)
        if not _esit(eski, yeni):
            fark[k] = [_deger(eski), _deger(yeni)]
    return fark


def _eski_durum(obj) -> str | None:
    if hasattr(obj, "_gecmis_eski_durum"):
        return obj._gecmis_eski_durum
    h = inspect(obj).attrs.durum.history
    return h.deleted[0] if h.deleted else obj.durum


def _ad(obj) -> str:
    if isinstance(obj, Fatura):
        return f"{'Satış' if obj.yon == 'giden' else 'Alış'} faturası {obj.fatura_no or ''}".strip()
    if isinstance(obj, Hareket):
        return f"{_deger(obj.tarih)} {float(obj.tutar or 0):,.2f} TL {obj.tur}".replace(",", "X").replace(".", ",").replace("X", ".")
    if isinstance(obj, Cek):
        return f"Çek {obj.cek_no or ''} {float(obj.tutar or 0):,.2f} TL".replace(",", "X").replace(".", ",").replace("X", ".")
    if isinstance(obj, Cari):
        return obj.unvan
    return obj.ad


def _kalem_anahtari(degerler: dict) -> tuple:
    return tuple(round(v, 4) if isinstance(v, float) else v for v in (_deger(degerler.get(a)) for a in KALEM_ALANLARI))


def _ozet(islem: str, ad: str, fark: dict | None) -> str:
    if islem == "degisti" and fark:
        parcalar = []
        for k, (eski, yeni) in fark.items():
            if k == "kalemler":
                parcalar.append("kalemler değişti")
            else:
                parcalar.append(f"{ALAN_ADLARI.get(k, k)}: {eski if eski not in (None, '') else '-'} → {yeni if yeni not in (None, '') else '-'}")
        return f"{ad}: " + "; ".join(parcalar)
    return {"eklendi": f"{ad} eklendi", "onaylandi": f"{ad} onaylandı", "iptal": f"{ad} iptal edildi",
            "iptal_geri": f"{ad} iptali geri alındı", "silindi": f"{ad} silindi"}.get(islem, ad)


def _kayitlar(session: Session) -> list[tuple]:
    """Flush öncesi değişiklikler: (nesne, tablo, işlem, alanlar). Yeni kayıtların id'si flush sonrası doldurulur."""
    sonuc = []
    kalem_degisen: dict[Fatura, dict] = {}
    for kl in list(session.new) + list(session.dirty) + list(session.deleted):
        if not isinstance(kl, FaturaKalem):
            continue
        f = kl.fatura or (session.get(Fatura, kl.fatura_id) if kl.fatura_id else None)
        if f is None or f in session.new:
            continue
        d = kalem_degisen.setdefault(f, {"eski": [], "yeni": []})
        if kl in session.new:
            d["yeni"].append({a: getattr(kl, a) for a in KALEM_ALANLARI})
        elif kl in session.deleted:
            d["eski"].append({a: getattr(kl, a) for a in KALEM_ALANLARI})
        else:
            ins = inspect(kl)
            eski = {a: (ins.attrs[a].history.deleted or [getattr(kl, a)])[0] for a in KALEM_ALANLARI}
            d["eski"].append(eski)
            d["yeni"].append({a: getattr(kl, a) for a in KALEM_ALANLARI})

    for obj in session.new:
        if type(obj) not in IZLENEN:
            continue
        durum = (obj.durum or type(obj).__table__.c.durum.default.arg) if isinstance(obj, TASLAKLI) else None
        if durum != "taslak":
            sonuc.append((obj, IZLENEN[type(obj)], "eklendi", None))
    for obj in session.deleted:
        if type(obj) in IZLENEN and not (isinstance(obj, TASLAKLI) and _eski_durum(obj) == "taslak"):
            sonuc.append((obj, IZLENEN[type(obj)], "silindi", _son_hal(obj)))
    for obj in set(session.dirty) | set(kalem_degisen):
        if type(obj) not in IZLENEN or obj in session.deleted or obj in session.new:
            continue
        fark = _farklar(obj) if session.is_modified(obj, include_collections=False) else {}
        if obj in kalem_degisen:
            d = kalem_degisen[obj]
            eski = sorted(_kalem_anahtari(x) for x in d["eski"])
            yeni = sorted(_kalem_anahtari(x) for x in d["yeni"])
            if eski != yeni:
                fark["kalemler"] = [[dict(zip(KALEM_ALANLARI, x)) for x in eski], [dict(zip(KALEM_ALANLARI, x)) for x in yeni]]
        if not fark:
            continue
        eski_durum, yeni_durum = (fark["durum"] if "durum" in fark else [getattr(obj, "durum", None)] * 2)
        if yeni_durum == "silinecek":  # silinmeden önceki ara adım; silme ayrıca yazılır
            obj._gecmis_eski_durum = eski_durum
            continue
        if isinstance(obj, TASLAKLI) and eski_durum == "taslak" and yeni_durum == "taslak":
            continue  # onaylanmamış kaydın düzenlemesi
        if isinstance(obj, TASLAKLI) and "durum" in fark:
            islem = {"onayli": "iptal_geri" if eski_durum == "iptal" else "onaylandi", "iptal": "iptal"}.get(yeni_durum, "degisti")
        else:
            islem = "degisti"
        sonuc.append((obj, IZLENEN[type(obj)], islem, fark))
    return sonuc


def kur(session_sinifi) -> None:
    @event.listens_for(session_sinifi, "before_flush")
    def _once(session, flush_context, instances):
        try:
            session.info["_gecmis"] = session.info.get("_gecmis", []) + _kayitlar(session)
        except Exception:  # geçmiş yazılamadı diye kayıt engellenmez
            logging.getLogger(__name__).exception("Değişiklik geçmişi yazılamadı")
            session.info["_gecmis"] = []

    @event.listens_for(session_sinifi, "after_flush")
    def _sonra(session, flush_context):
        bekleyen = session.info.pop("_gecmis", [])
        if not bekleyen:
            return
        kullanici = session.info.get("kullanici_id")
        satirlar = []
        for obj, tablo, islem, alanlar in bekleyen:
            if obj.id is None or getattr(obj, "sirket_id", None) is None:
                continue
            satirlar.append({"sirket_id": obj.sirket_id, "kullanici_id": kullanici, "zaman": datetime.now(), "tablo": tablo,
                             "kayit_id": obj.id, "islem": islem, "ozet": _ozet(islem, _ad(obj), alanlar), "alanlar": alanlar})
        if satirlar:
            session.connection().execute(Degisiklik.__table__.insert(), satirlar)
