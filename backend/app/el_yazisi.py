"""Çekteki el yazısı (vade, rakamla ve yazıyla tutar): isteğe bağlı, bilgisayarda çalışan PaddleOCR modeli (RapidOCR,
ONNX) ile, internetsiz ve yapay zeka servisine gönderilmeden okunur. Paket kurulu değilse bu adım atlanır, alanlar
boş ve kırmızı kalır.

Güven kuralı: tutar rakamla ve yazıyla ayrı okunur; ikisi aynı tutarı verirse alan emin (yeşil) sayılır. Yalnız biri
okunursa değer yazılır ama kırmızı kalır (kontrol edin). Çek Kanunu gereği yazı ile rakam farklıysa yazıyla yazılan
geçerlidir; bu yüzden yazı net okunduysa o önerilir. Vade: gün.ay.yıl net okunursa emin; yıl okunamaz ya da imkânsızsa
(çekin basımından önce) gün ve aydan en yakın ileri tarih önerilir, kırmızı kalır.
"""
import difflib
import re
import threading
from datetime import date, timedelta

_KILIT = threading.Lock()
_MOTOR = None


def _paket() -> str | None:
    """Kurulu el yazısı paketi: "rapidocr" (3.x, ölçümde belirgin daha iyi) ya da eski "rapidocr_onnxruntime"."""
    for ad in ("rapidocr", "rapidocr_onnxruntime"):
        try:
            __import__(ad)
            return ad
        except Exception:  # noqa: BLE001
            continue
    return None


def var_mi() -> bool:
    return _paket() is not None


def motor_adi() -> str:
    ad = _paket() or "yok"
    try:
        from importlib.metadata import version
        return f"{ad} {version(ad.replace('_', '-'))}"
    except Exception:  # noqa: BLE001
        return ad


def ayrintili(img) -> list[dict]:
    """Resimdeki yazı kutuları (okuma sırasıyla): {"m": metin, "g": güven 0-1, "kutu": [x0, y0, x1, y1]}.
    Model bir kez yüklenir (rapidocr ilk çalışmada modelini bir kez indirir; sonra internetsiz çalışır)."""
    global _MOTOR
    import numpy as np
    with _KILIT:
        if _MOTOR is None:
            if _paket() == "rapidocr":
                from rapidocr import RapidOCR
            else:
                from rapidocr_onnxruntime import RapidOCR
            _MOTOR = RapidOCR()
        sonuc = _MOTOR(np.asarray(img.convert("RGB")))
    if isinstance(sonuc, tuple):  # rapidocr_onnxruntime: ([[köşeler, metin, güven], ...], süreler)
        uclu = sonuc[0] or []
    else:  # rapidocr 3: kutular, metinler ve güvenler ayrı listeler
        uclu = list(zip(sonuc.boxes if sonuc.boxes is not None else [], sonuc.txts or (), sonuc.scores or ()))
    kutular = []
    for koseler, t, g in uclu:
        xs, ys = [int(p[0]) for p in koseler], [int(p[1]) for p in koseler]
        kutular.append({"m": t, "g": round(float(g), 3), "kutu": [min(xs), min(ys), max(xs), max(ys)]})
    return kutular


def metinler(img) -> list[str]:
    """Resimdeki yazı kutularının metinleri (okuma sırasıyla)."""
    return [k["m"] for k in ayrintili(img)]


# --- Yazıyla tutar ---------------------------------------------------------------------------------------------

_BIRLER = ["", "bir", "iki", "uc", "dort", "bes", "alti", "yedi", "sekiz", "dokuz"]
_ONLAR = ["", "on", "yirmi", "otuz", "kirk", "elli", "altmis", "yetmis", "seksen", "doksan"]


def _uc_hane(n: int) -> str:
    y, o, b = n // 100, n // 10 % 10, n % 10
    return ("" if y == 0 else ("yuz" if y == 1 else _BIRLER[y] + "yuz")) + _ONLAR[o] + _BIRLER[b]


def sayi_yazisi(n: int) -> str:
    """Tam sayının Türkçe yazılışı, harfler sadeleştirilmiş: 350000 -> 'ucyuzellibin', 1000 -> 'bin'."""
    if n == 0:
        return "sifir"
    milyon, bin_, kalan = n // 1_000_000, n // 1000 % 1000, n % 1000
    s = (_uc_hane(milyon) + "milyon") if milyon else ""
    s += ("bin" if bin_ == 1 else _uc_hane(bin_) + "bin") if bin_ else ""
    return s + _uc_hane(kalan)


_SADE = str.maketrans({"ı": "i", "İ": "i", "ş": "s", "Ş": "s", "ç": "c", "Ç": "c", "ğ": "g", "Ğ": "g", "ü": "u",
                       "Ü": "u", "ö": "o", "Ö": "o", "2": "z", "0": "o", "1": "i", "5": "s", "8": "b"})
_BASILI = re.compile(r"(?i)yaln|emr|odey|kesid|tarih|tacir|findeks|mersis|banka|sube|karsil|soyad|imza|basim|iban|turk|lira")
_ADAYLAR = None


def _adaylar() -> list[tuple[int, str]]:
    global _ADAYLAR
    if _ADAYLAR is None:
        _ADAYLAR = [(n, sayi_yazisi(n)) for n in range(1000, 10_000_001, 1000)]
    return _ADAYLAR


def _sade(s: str) -> str:
    return re.sub(r"[^a-z]", "", s.translate(_SADE).lower())


def yazidan_tutar(kutular: list[str], ek_adaylar: tuple[int, ...] = (), basamak: int | None = None
                  ) -> tuple[int | None, float, dict[int, float]]:
    """Yazıyla yazılmış tutar ("üçyüzellibin"): kutular, sayıların Türkçe yazılışlarıyla karşılaştırılır.
    basamak: rakamla okunan tutarın basamak sayısı (yazı "yediyüzelli" ile "yedimilyonelli" arasında karar için).
    (en iyi tutar, benzerliği, {aday: benzerlik} ek adaylar için)."""
    en, en_puan, ek = None, 0.0, {n: 0.0 for n in ek_adaylar}
    adaylar = [(n, y) for n, y in _adaylar() if not basamak or len(str(n)) == basamak]
    adaylar += [(n, sayi_yazisi(n)) for n in ek_adaylar if n % 1000]
    for kutu in kutular:
        if _BASILI.search(_sade(kutu)) or len(re.findall(r"[^\W\d_]", kutu)) < 5:
            continue
        s = _sade(kutu)
        # Tutar yazısı "bin"/"milyon"/"lira" ile biter; el yazısında sonu "bn", "bln", "btn", "bh", "b" okunabilir
        if not (s.endswith(("n", "bia", "ib", "lira")) or "b" in s[-3:] or "bin" in s or "milyon" in s):
            continue
        for n, yazi in adaylar:
            if abs(len(yazi) - len(s)) > 6:
                continue
            p = difflib.SequenceMatcher(None, s, yazi).ratio()
            if p > en_puan:
                en, en_puan = n, p
            if n in ek:
                ek[n] = max(ek[n], p)
    return en, en_puan, ek


def rakamdan_tutar(kutular: list[str]) -> tuple[int | None, str | None]:
    """"TL #350.000#" kutusu: (binlik ayraçla düzgün okunan tutar ya da None, okunan rakamlar)."""
    for kutu in kutular:
        if "#" not in kutu and not re.match(r"(?i)\s*TL", kutu):
            continue
        govde = re.sub(r"(?<=\d)\s+(?=\d)", "", re.sub(r"(?i)^\s*T?L?\s*[-#+TF]*\s*", "", kutu)).strip("#+. ")
        if not re.search(r"\d{3}", govde):
            continue
        m = re.fullmatch(r"(\d{1,3}(?:[.,:;]\d{3})+)(?:,\d{2})?", govde)  # nokta bazen ":" okunur
        return (int(re.sub(r"[.,:;]", "", m.group(1))) if m else None), re.sub(r"\D", "", govde)
    return None, None


NEDEN_UYUSMAZ = "Rakamla yazılan tutar yazıyla yazılanı tutmuyor; yazıyla yazılan esas alındı."


def tutar_bul(kutular: list[str]) -> tuple[float | None, bool]:
    """(tutar, emin mi)."""
    return tutar_bul_nedenli(kutular)[:2]


def tutar_bul_nedenli(kutular: list[str]) -> tuple[float | None, bool, str | None]:
    """(tutar, emin mi, emin değilse kısa nedeni)."""
    rakam, rakamlar = rakamdan_tutar(kutular)
    # Rakam okunamasa da hane sayısı belliyse ("#000.000#": 6 hane) yazı o hanedeki tutarlarla karşılaştırılır
    basamak = len(str(rakam)) if rakam else (len(rakamlar) if rakamlar and len(rakamlar) >= 4 else None)
    yazi, puan, ek = yazidan_tutar(kutular, (rakam,) if rakam else (), basamak)
    # Rakam ve yazı aynı tutarsa emin. Yazı, rakamın basamak sayısına bakılmadan da en iyi bu tutara uymalı: "#750.000#"
    # "#+50.000#" okununca "yediyüzellibin" yazısı 5 haneliler içinde en çok "ellibin"e benzer, ama asıl uyduğu 750.000'dir
    serbest, serbest_puan, _ = yazidan_tutar(kutular) if rakam else (yazi, puan, {})
    if rakam and ek.get(rakam, 0) >= 0.6 and ek[rakam] >= max(puan, serbest_puan) - 0.05:
        return float(rakam), True, None  # rakam ve yazı aynı tutar
    if yazi and puan >= 0.7:
        uyumlu = bool(rakamlar) and len(rakamlar) >= 3 and str(yazi).startswith(rakamlar[:3])
        if uyumlu:
            return float(yazi), puan >= 0.75, None if puan >= 0.75 else "Yazıyla tutar tam okunamadı."
        if puan >= 0.85 or (not rakamlar and puan >= 0.8):
            return float(yazi), False, NEDEN_UYUSMAZ  # rakam başka okundu; yazı net: yazı geçerlidir
    if serbest and serbest_puan >= 0.85 and serbest != rakam:
        return float(serbest), False, NEDEN_UYUSMAZ  # yazı net, rakam başka okundu (ör. bir hanesi düştü)
    if rakam:
        return float(rakam), False, "Yazıyla yazılan tutar okunamadı; rakamla yazılan önerildi."
    return None, False, "Tutar okunamadı."


# --- Vade ------------------------------------------------------------------------------------------------------

_TARIH = re.compile(r"(?<!\d)(?:(\d{1,3})\s*[.,/-]\s*(\d{1,2})|(\d{2})(\d{2})(?=\s*[.,/-]\s*\d{4}))\s*[.,/-]?\s*(\d{2,4})?")

# "Tarih" yazısı el yazısı modelinde "Tah", "Tarh", "Trn" okunabilir; ardından ayraçsız ya da boşluklu gün ay yıl gelir.
# Etiket okunmadıysa da yalnız "gg aa yyyy" (boşluklu) ya da "ggaayyyy" (yıl 20 ile başlar) biçimi tarih sayılır
_ETIKETLI_TARIH = re.compile(r"(?i)(?:t[a-z]{0,3}[hn]|(?<![\d.])(?=\d{2}\s\d{2}\s\d{4}(?!\d))|(?<!\d)(?=\d{4}20\d{2}(?!\d)))[^\d]{0,4}(\d{2})\s*[.,/ -]?\s*(\d{2})\s*[.,/ -]?\s*(\d{4})(?!\d)")


YIL_YOK = "Yıl okunamadı; en yakın ileri tarih önerildi."


def vade_bul(kutular: list[str], bugun: date | None = None, basim: date | None = None) -> tuple[date | None, bool]:
    """(vade, emin mi)."""
    return vade_bul_nedenli(kutular, bugun, basim)[:2]


def vade_bul_nedenli(kutular: list[str], bugun: date | None = None, basim: date | None = None
                     ) -> tuple[date | None, bool, str | None]:
    """(vade, emin mi, emin değilse kısa nedeni). Gün ve ay okunup yıl okunamazsa ya da imkânsızsa en yakın ileri tarih
    önerilir (emin değil). basim: çekin basım tarihi; vade ondan önce olamaz (basım tarihi vade sanılmaz)."""
    bugun = bugun or date.today()
    sonuc = _vade(kutular, bugun)
    if sonuc[0] and basim and sonuc[0] <= basim:
        return None, False, "Okunan tarih çekin basım tarihinden önce; vade okunamadı."
    return sonuc


def _vade(kutular: list[str], bugun: date) -> tuple[date | None, bool, str | None]:
    for kutu in kutular:
        if re.search(r"(?i)bas[ıi]m", kutu):
            continue
        k = kutu.translate(str.maketrans({"O": "0", "o": "0", "l": "1", "I": "1"}))
        for m in _TARIH.finditer(k):
            g, a, y = m.group(1) or m.group(3), int(m.group(2) or m.group(4)), m.group(5)
            if len(g) == 3 and g[0] == "1":
                g = g[1:]  # tarihten önceki "/" çizgisi 1 okunur
            g = int(g)
            if not (1 <= g <= 31 and 1 <= a <= 12):
                continue
            if y and len(y) == 4 and bugun.year - 1 <= int(y) <= bugun.year + 3:
                try:
                    return date(int(y), a, g), True, None
                except ValueError:
                    continue
            for yil in (bugun.year - 1, bugun.year, bugun.year + 1, bugun.year + 2):
                try:
                    t = date(yil, a, g)
                except ValueError:
                    continue
                if t >= bugun - timedelta(days=60):
                    return t, False, YIL_YOK
    # Ayraçsız yazılan tarih ("Tarih: 05 12 2026", okunuşu "Tah.05122026"): "Tarih" yazısından sonraki gün, ay, yıl
    for kutu in kutular + [" ".join(kutular)]:
        k = kutu.translate(str.maketrans({"O": "0", "o": "0", "l": "1", "I": "1"}))
        for m in _ETIKETLI_TARIH.finditer(k):
            g, a, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if not (1 <= g <= 31 and 1 <= a <= 12):
                continue
            try:
                if bugun.year - 1 <= y <= bugun.year + 3:
                    return date(y, a, g), True, None
                for yil in (bugun.year, bugun.year + 1, bugun.year + 2):
                    if (t := date(yil, a, g)) >= bugun - timedelta(days=60):
                        return t, False, YIL_YOK
            except ValueError:
                continue
    # Yıl okunamadı: "Tarih" yazısından ya da "KÜTAHYA /" ayracından (yer adından sonra; kaşedeki telefonun "/"ı değil) sonraki gün ve ay ("Tain.0601 201T",
    # "/2101.20L3", "/ 22 01 -2024"): en yakın ileri tarih önerilir, kırmızı
    for kutu in kutular:
        k = kutu.translate(str.maketrans({"O": "0", "o": "0", "l": "1", "I": "1"}))
        if (m := re.search(r"(?i)(?:t[a-z]{0,3}[hn]|[a-z]\s*/)[^\d]{0,3}(\d{2})\s*[.,/ -]?\s*(\d{2})(?!\d{3})", k)):
            g, a = int(m.group(1)), int(m.group(2))
            if 1 <= g <= 31 and 1 <= a <= 12:
                for yil in (bugun.year, bugun.year + 1, bugun.year + 2):
                    try:
                        if (t := date(yil, a, g)) >= bugun - timedelta(days=60):
                            return t, False, YIL_YOK
                    except ValueError:
                        continue
    # Son çare: "Tarih" yazısından sonraki kısa parçadaki rakamlar ("Tarih:1O12.2026" -> 10122026) gün-ay-yıl sayılır
    for kutu in kutular:
        k = kutu.translate(str.maketrans({"O": "0", "o": "0", "l": "1", "I": "1"}))
        if (m := re.search(r"(?i)(?:ar[iı1]h|ta[hn]|tr[hn])[^\d]{0,3}([\d\s.,/:;-]{8,16})", k)):
            r = re.sub(r"\D", "", m.group(1))
            if len(r) >= 8 and r[4:6] == "20":
                g, a, y = int(r[:2]), int(r[2:4]), int(r[4:8])
                if 1 <= g <= 31 and 1 <= a <= 12:
                    try:
                        if bugun.year - 1 <= y <= bugun.year + 3:
                            return date(y, a, g), False, "Tarih net okunamadı."
                    except ValueError:
                        pass
    return None, False, "Vade okunamadı."
