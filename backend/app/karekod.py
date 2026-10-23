"""e-Fatura / e-Arşiv karekodu (GİB): faturanın sağ üstündeki karekodda satıcı ve alıcı VKN'si, fatura numarası,
tarih ve KDV oranı başına matrah/KDV ile ödenecek tutar yazar. Yazısı çıkmayan PDF'te (tarayıcıdan bozuk basılmış,
yazı katmanı olmayan) ya da fotoğrafta bu bilgiler karekoddan yapay zekasız ve kesin okunur. Kalemler karekodda
yoktur; uydurulmaz.

Okuyucu zxing-cpp kütüphanesidir; kurulu değilse karekod atlanır, öteki yöntemler çalışır.
"""
import json

from . import kural


def var_mi() -> bool:
    try:
        import zxingcpp  # noqa: F401
    except ImportError:
        return False
    return True


_ONBELLEK: dict[tuple[str, bool], dict | None] = {}


def oku(veri: bytes, pdf: bool) -> dict | None:
    """Sayfalardaki GİB karekodunun içeriği (sözlük) ya da None. Aynı belge bir yüklemede birkaç kez sorulur (yön, karşı
    taraf); son belgelerin sonucu saklanır."""
    if not var_mi():
        return None
    import hashlib
    anahtar = (hashlib.sha1(veri).hexdigest(), pdf)
    if anahtar not in _ONBELLEK:
        if len(_ONBELLEK) > 16:
            _ONBELLEK.clear()
        _ONBELLEK[anahtar] = _oku(veri, pdf)
    return _ONBELLEK[anahtar]


def yonu(k: dict | None, sirket_vkn: str | None) -> str | None:
    """Karekoddaki taraflara göre yön: alıcı bizsek alış (gelen), satıcı bizsek satış (giden)."""
    vkn = "".join(c for c in str(sirket_vkn or "") if c.isdigit())
    if not (k and vkn):
        return None
    satici, alici = (("".join(c for c in str(k.get(a) or "") if c.isdigit())) for a in ("vkntckn", "avkntckn"))
    if alici == vkn and satici != vkn:
        return "gelen"
    if satici == vkn and alici != vkn:
        return "giden"
    return None


def _oku(veri: bytes, pdf: bool) -> dict | None:
    import zxingcpp

    from .ocr import _goruntuler
    try:
        sayfalar = _goruntuler(veri, pdf)
    except kural.KuralHatasi:
        return None
    for img in sayfalar[:2]:
        for kod in zxingcpp.read_barcodes(img.convert("L")):
            try:
                d = json.loads(kod.text)
            except ValueError:
                continue
            if isinstance(d, dict) and d.get("no") and (d.get("vkntckn") or d.get("odenecek")):
                return {str(a).lower(): v for a, v in d.items()}
    return None


def _sayi(x) -> float | None:
    try:
        return round(float(str(x).replace(",", ".")), 2)
    except (TypeError, ValueError):
        return None


def toplamlar(k: dict) -> dict:
    kdv = [_sayi(v) for a, v in k.items() if a.startswith("hesaplanankdv") and "tevkifat" not in a]
    matrah = [_sayi(v) for a, v in k.items() if a.startswith("kdvmatrah")]
    tevk = [_sayi(v) for a, v in k.items() if "tevkifat" in a and "tabi" not in a and "matrah" not in a]
    ara = _sayi(k.get("malhizmettoplam"))
    kdv_t = round(sum(x for x in kdv if x), 2) if kdv else None
    dahil = _sayi(k.get("vergidahil"))
    if matrah and None not in matrah and (ara is None or sum(matrah) < ara - 0.05) \
            and (dahil is None or abs(sum(matrah) + (kdv_t or 0) - dahil) <= 0.05):
        ara = round(sum(matrah), 2)  # iskonto mal/hizmet toplamından düşülmüş (KDV'siz kalemler ve ÖİV varsa değil)
    tevk_t = round(sum(x for x in tevk if x), 2)
    genel = _sayi(k.get("odenecek") or k.get("vergidahil"))
    if dahil is not None and genel is not None and abs(genel - (dahil - tevk_t)) > 1:
        genel = round(dahil - tevk_t, 2)  # ödenecek tutardan önceki ödeme/mahsup düşülmüş: fatura tutarı esas
    return {"ara_toplam": ara, "kdv_toplam": kdv_t, "tevkifat": tevk_t, "genel_toplam": genel,
            "para_birimi": (k.get("parabirimi") or "TRY")[:3].upper()}


def _taraflar(k: dict, sirket_vkn: str | None, yon: str) -> tuple[str | None, str | None]:
    satici, alici = k.get("vkntckn"), k.get("avkntckn")
    if yon == "gelen" and sirket_vkn and satici == sirket_vkn and alici != sirket_vkn:
        satici, alici = alici, satici
    if yon == "gelen" and satici == sirket_vkn:
        satici = None  # kendi VKN'miz satıcı olmaz
    return satici, alici


def fatura(k: dict, sirket_vkn: str | None = None, yon: str = "gelen") -> dict:
    """Yalnız karekoddan okunan fatura: başlık ve toplamlar tam, kalemler elle girilir (kırmızı)."""
    satici, alici = _taraflar(k, sirket_vkn, yon)
    t = toplamlar(k)
    return {
        "belge_fatura_mi": True, "fatura_no": k.get("no"), "tarih": kural.tarih_coz(k.get("tarih")) and str(kural.tarih_coz(k.get("tarih"))),
        "vade": None,
        "satici": {"unvan": None, "vkn": satici, "vergi_dairesi": None, "adres": None, "telefon": None, "iban": None},
        "alici": {"unvan": None, "vkn": alici},
        "kalemler": [], **t, "diger_vergiler": 0,
        "onerilen_santiye": None, "onerilen_gider_turu": None,
        "notlar": "Faturada okunabilir yazı yok; fatura numarası, tarih, VKN ve toplamlar faturanın karekodundan okundu. "
                  "Kalemler karekodda yazmaz; faturadaki kalemleri (Mal Hizmet Adı, Miktar, Birim Fiyat, KDV) girin.",
        "kalemler_okunamadi": True,
        "okuma_yontemi": "Karekod",
        "karekod": k,
    }


def uygula(okunan: dict, k: dict, sirket_vkn: str | None = None, yon: str = "gelen") -> dict:
    """Yazıdan/resimden okunan faturada karekodun kesin bilgileri esas alınır (numara, tarih, VKN, toplamlar)."""
    satici, _ = _taraflar(k, sirket_vkn, yon)
    t = {a: v for a, v in toplamlar(k).items() if v is not None}
    sonuc = {**okunan, **t, "karekod": k, "belge_fatura_mi": True}  # geçerli GİB karekodu: belge faturadır
    if k.get("no"):
        sonuc["fatura_no"] = k["no"]
    if kural.tarih_coz(k.get("tarih")):
        sonuc["tarih"] = str(kural.tarih_coz(k["tarih"]))
    if satici and (okunan.get("satici") or {}).get("vkn") != satici:
        sonuc["satici"] = {**(okunan.get("satici") or {}), "vkn": satici}
    if any(okunan.get(a) != sonuc.get(a) for a in ("fatura_no", "tarih", "ara_toplam", "kdv_toplam", "genel_toplam")) \
            or sonuc["satici"] is not okunan.get("satici"):
        sonuc["notlar"] = " ".join(x for x in (okunan.get("notlar"), "Fatura numarası, tarih, VKN ve toplamlar "
                                                 "faturanın karekodundan doğrulandı.") if x)
    return sonuc
