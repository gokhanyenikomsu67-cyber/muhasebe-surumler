"""TCMB döviz kuru: dövizli faturada kur yazmıyorsa fatura tarihinin kuru Merkez Bankası'nın günlük kur listesinden
getirilir (internet gerekir; yoksa kur elle girilir). Fatura tarihinde geçerli kur, bir önceki iş günü yayımlanan
listedeki döviz alış kurudur (VUK 280); hafta sonu ve tatilde geriye doğru en fazla 10 gün aranır."""
import threading
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, timedelta

ADRES = "https://www.tcmb.gov.tr/kurlar/{yilay}/{gunayyil}.xml"
_ONBELLEK: dict[tuple[str, date], tuple[float, date] | None] = {}
_KILIT = threading.Lock()


class KurAlinamadi(Exception):
    pass


def _liste(gun: date) -> bytes | None:
    adres = ADRES.format(yilay=gun.strftime("%Y%m"), gunayyil=gun.strftime("%d%m%Y"))
    try:
        with urllib.request.urlopen(urllib.request.Request(adres, headers={"User-Agent": "Mozilla/5.0"}), timeout=8) as y:
            return y.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None  # o gün liste yayımlanmamış (hafta sonu, tatil)
        raise KurAlinamadi("TCMB kur listesine ulaşılamadı; kuru faturadan elle girin.") from e
    except OSError as e:
        raise KurAlinamadi("İnternete ulaşılamadı; kuru faturadan elle girin.") from e


def kur_bul(xml: bytes, para: str) -> float | None:
    kok = ET.fromstring(xml)
    for c in kok.iter("Currency"):
        if (c.get("Kod") or c.get("CurrencyCode")) == para:
            birim = float(c.findtext("Unit") or 1) or 1
            deger = c.findtext("ForexBuying") or c.findtext("BanknoteBuying")
            return round(float(deger) / birim, 6) if deger else None
    return None


def kur(para: str, tarih: date) -> tuple[float, date]:
    """(kur, listenin tarihi)."""
    para = (para or "").upper()[:3]
    anahtar = (para, tarih)
    with _KILIT:
        if anahtar in _ONBELLEK and _ONBELLEK[anahtar]:
            return _ONBELLEK[anahtar]
    gun = tarih - timedelta(days=1)
    for _ in range(10):
        if gun.weekday() < 5:
            xml = _liste(gun)
            if xml:
                deger = kur_bul(xml, para)
                if not deger:
                    raise KurAlinamadi(f"TCMB listesinde {para} kuru yok; kuru elle girin.")
                with _KILIT:
                    _ONBELLEK[anahtar] = (deger, gun)
                return deger, gun
        gun -= timedelta(days=1)
    raise KurAlinamadi("Bu tarih için TCMB kuru bulunamadı; kuru faturadan elle girin.")
