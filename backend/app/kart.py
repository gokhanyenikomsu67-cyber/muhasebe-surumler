"""Kredi kartı ekstresi: yapay zekasız okuma (PDF, Excel, CSV; taranmış PDF/görsel yerel OCR ile),
işyeri adının temizlenmesi ve satırın türü.

İşaret kuralı banka ekstresiyle aynıdır: tutar > 0 karta para girdi (borç ödemesi, iade),
tutar < 0 kartla harcama yapıldı (kart borcu arttı). Kart hesabının bakiyesi eksiyse o kadar borç vardır.
"""
import re
from datetime import date

from .kural import KuralHatasi, para_coz, pdf_metni, sade, tablo_satirlari, tr_buyuk

_PARA = r"(?<![\d.,])-?\d{1,3}(?:\.\d{3})+,\d{2}(?![\d,])-?|(?<![\d.,])-?\d+,\d{2}(?![\d,])-?"
_TARIH = r"\d{1,2}[./-]\d{1,2}[./-](?:\d{4}|\d{2})(?!\d)"
_DOVIZ = re.compile(r"\b(USD|EUR|EURO|GBP|CHF|\$|€|£)\s*$", re.I)
# "2/6", "(3/12)", "TAKSİT 2/6", "2. TAKSİT / 6": taksitli harcamanın kaçıncı taksiti
_TAKSIT = re.compile(r"\(?\s*(?:taksit\w*\s*:?\s*)?(\d{1,2})\s*\.?\s*(?:taksit\w*\s*)?/\s*(\d{1,2})\s*\)?(?:\s*taksit\w*)?", re.I)
KART_NO = re.compile(r"(?<![\d*xX])(\d{4})[\s-]?([\d*xX]{2}[*xX]{2})[\s-]?([*xX]{4})[\s-]?(\d{4})(?![\d*xX])")

# Ekstrenin özet bilgileri (sade yazımla aranır)
OZET = {
    "donem_borcu": r"(?:guncel\s+|toplam\s+)?donem\s+borcu(?:nuz)?|hesap\s+kesim\s+tarihindeki\s+borc\w*|ekstre\s+borcu(?:nuz)?|"
                   r"odenmesi\s+gereken\s+(?:toplam\s+)?tutar",
    "onceki_borc": r"(?:onceki|gecen)\s+(?:donem|ekstre)\s+borcu(?:nuz)?|devreden\s+borc\w*|onceki\s+bakiye",
    "asgari": r"asgari\s+odeme(?:\s+tutari)?|minimum\s+odeme(?:\s+tutari)?",
    "kesim_tarihi": r"hesap\s+kesim\s+tarihi|ekstre\s+(?:kesim\s+)?tarihi|kesim\s+tarihi",
    "son_odeme": r"son\s+odeme\s+tarihi",
}
_TARIH_ALANLARI = ("kesim_tarihi", "son_odeme")
_KART_IZI = ("son odeme tarihi", "asgari odeme", "donem borcu", "hesap kesim", "kart limiti", "kart numarasi", "kredi karti")

# Harcama olmayan satırlar
ODEME = re.compile(r"\b(odemeniz|odeme\s*(?:tesekkur|alindi|yapildi|islemi)|hesaptan\s+odeme|otomatik\s+odeme|"
                   r"(?:mobil|internet|atm|sube|eft|havale|fast)\w*\s+(?:kk\s+|kart\s+)?odeme|kart\s+borc\w*\s+odeme|"
                   r"borc\s+odeme)\b|^odeme\b")
IADE = re.compile(r"\b(iade|iptal|geri\s+odeme|ters\s+kayit|harcama\s+itiraz|chargeback|refund)\b")
NAKIT_AVANS = re.compile(r"\b(nakit\s+avans|nakit\s+cekim|atm\s+(?:nakit|para)|taksitli\s+nakit)\b")
KART_MASRAFI = re.compile(r"\b(?:akdi\s+|gecikme\s+|temerrut\s+)?faiz\w*|\bbsmv\b|\bkkdf\b|\bgecikme\b|"
                          r"\b(?:yillik\s+)?(?:kart\s+)?(?:uyelik|aidat)\s*(?:ucret\w*)?|\bkart\s+ucret\w*|\bekstre\s+ucret\w*|"
                          r"\bnakit\s+avans\s+(?:ucret|komisyon)\w*|\bhesap\s+isletim\w*|\bsigorta\s+prim\w*|"
                          r"\bvergi\s+kesinti\w*|\bkart\s+komisyon\w*")
PUAN = re.compile(r"\b(puan|bonus|parafpara|chip\s*para|maxipuan|worldpuan|cashback|nakit\s+iade\s+kazanim|kazanim)\b")

# Ödeme aracıları: "IYZICO*TRENDYOL", "PAYTR *HEPSIBURADA" -> asıl işyeri yıldızdan sonradır
_ARACI = re.compile(r"^(?:iyzico|iyz|paytr|param|ipara|payu|paypal|sumup|craftgate|moka|lidio|stripe|papara|sipay|"
                    r"esnekpos|paratika|garantipay|bkm\s*express|google|apple\.com/bill)\b\s*[*/:]?\s*", re.I)
_ULKE = {"tr", "tur", "turkey", "turkiye", "usa", "us", "gb", "gbr", "ie", "irl", "nl", "nld", "de", "deu", "lu", "lux", "fr", "uk"}
ILLER = {
    "adana", "adiyaman", "afyon", "afyonkarahisar", "agri", "aksaray", "amasya", "ankara", "antalya", "ardahan", "artvin",
    "aydin", "balikesir", "bartin", "batman", "bayburt", "bilecik", "bingol", "bitlis", "bolu", "burdur", "bursa",
    "canakkale", "cankiri", "corum", "denizli", "diyarbakir", "duzce", "edirne", "elazig", "erzincan", "erzurum",
    "eskisehir", "gaziantep", "giresun", "gumushane", "hakkari", "hatay", "igdir", "isparta", "istanbul", "izmir",
    "kahramanmaras", "karabuk", "karaman", "kars", "kastamonu", "kayseri", "kilis", "kirikkale", "kirklareli",
    "kirsehir", "kocaeli", "konya", "kutahya", "malatya", "manisa", "mardin", "mersin", "mugla", "mus", "nevsehir",
    "nigde", "ordu", "osmaniye", "rize", "sakarya", "samsun", "sanliurfa", "siirt", "sinop", "sirnak", "sivas",
    "tekirdag", "tokat", "trabzon", "tunceli", "usak", "van", "yalova", "yozgat", "zonguldak",
    # sık geçen ilçeler ve yazımlar
    "izmit", "gebze", "darica", "cayirova", "dilovasi", "kartal", "pendik", "tuzla", "kadikoy", "atasehir", "umraniye",
    "uskudar", "besiktas", "sisli", "beyoglu", "bakirkoy", "esenyurt", "beylikduzu", "basaksehir", "maltepe", "sariyer",
    "cankaya", "yenimahalle", "kecioren", "etimesgut", "sincan", "golbasi", "polatli", "karsiyaka", "bornova", "konak",
    "buca", "nilufer", "osmangazi", "yildirim", "selcuklu", "meram", "seyhan", "cukurova", "muratpasa", "konyaalti",
    "kepez", "alanya", "bodrum", "fethiye", "marmaris", "corlu", "cerkezkoy", "adapazari", "serdivan", "golcuk",
    "korfez", "derince", "kartepe", "basiskele", "merkez", "ist", "ank", "izm", "istanbu", "kocael",
}


def tarih(deger) -> date | None:
    """'05.10.2026', '5/10/26', '2026-10-05' ya da Excel tarih hücresi."""
    if isinstance(deger, date):
        return deger if not hasattr(deger, "date") else deger.date()
    s = str(deger or "").strip()
    m = re.match(r"(\d{1,2})[./-](\d{1,2})[./-](\d{4}|\d{2})(?!\d)", s) or None
    if m:
        g, a, y = (int(x) for x in m.groups())
        y += 2000 if y < 100 else 0
    elif m := re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", s):
        y, a, g = (int(x) for x in m.groups())
    else:
        return None
    try:
        return date(y, a, g)
    except ValueError:
        return None


def kart_ekstresi_mi(metin: str) -> bool:
    """Metin kredi kartı ekstresine mi ait (banka hesap ekstresi değil)?"""
    s = sade(metin)
    return sum(1 for iz in _KART_IZI if iz in s) >= 2


def kart_odemesi_mi(aciklama: str | None) -> bool:
    """Banka ekstresindeki satır kredi kartı borcu ödemesi mi ("KREDİ KARTI ÖDEMESİ 5528****1234")?"""
    s = sade(aciklama or "")
    return bool(re.search(r"kredi\s*kart|\bkk\b|\bk\.k\.|kart\w*\s+(?:borc|odeme)|paraf|bonus\s*kart|axess|world\s*kart|"
                          r"maximum\s*kart|cardfinans|bankkart", s)) and bool(re.search(r"odeme|borc|tahsil|virman|aktar", s)) \
        and not re.search(r"\b(iade|komisyon|masraf|faiz|bsmv)\b", s)


_BANKALAR = [(r"halk\s*bank|\bparaf", "Halkbank"), (r"garanti|\bbonus\b", "Garanti BBVA"), (r"akbank|\baxess\b", "Akbank"),
             (r"yapi\s*kredi|\bworld\b", "Yapı Kredi"), (r"is\s*bankasi|\bmaximum\b", "İş Bankası"),
             (r"ziraat|bankkart", "Ziraat Bankası"), (r"vakif\s*bank|vakiflar", "VakıfBank"), (r"qnb|cardfinans", "QNB"),
             (r"denizbank", "DenizBank"), (r"\bteb\b", "TEB"), (r"\bing\b", "ING"), (r"enpara", "Enpara"),
             (r"kuveyt", "Kuveyt Türk"), (r"albaraka", "Albaraka Türk"), (r"sekerbank", "Şekerbank")]


def banka_adi(metin: str) -> str | None:
    """Kart ekstresinin hangi bankaya ait olduğu (ilk sayfalardaki banka/kart adından)."""
    s = sade(metin[:3000])
    return next((ad for desen, ad in _BANKALAR if re.search(desen, s)), None)


def kart_son4(metin: str | None) -> str | None:
    m = KART_NO.search(metin or "")
    return m.group(4) if m else None


def taksit(aciklama: str) -> tuple[int, int] | None:
    """Açıklamadaki 'k/n' taksit bilgisi (tarih parçası değil)."""
    for m in _TAKSIT.finditer(aciklama):
        k, n = int(m.group(1)), int(m.group(2))
        parcali = "(" in m.group() or "taksit" in sade(m.group()) or "taksit" in sade(aciklama)
        if parcali and 1 <= k <= n and 2 <= n <= 48 and not re.match(r"[./-]\d", aciklama[m.end():m.end() + 2]):
            return k, n
    return None


_ON_KELIME = {"yurtici", "yurtdisi", "yurt", "ici", "disi", "internet", "eticaret", "e-ticaret", "sanal", "pos", "temassiz",
              "harcama", "harcamasi", "alisveris", "satis", "taksitli", "islem", "islemi", "mail", "order", "provizyon", "tutar"}


def isyeri_temizle(aciklama: str) -> str:
    """Ekstre açıklamasından işyeri adı: şehir, ülke kodu, POS/şube numaraları, taksit ve tutar bilgisi atılır.
    'IYZICO*TRENDYOL ISTANBUL TR' -> 'TRENDYOL'; 'MIGROS 4512 GEBZE KOCAELI' -> 'MIGROS'."""
    s = " " + aciklama + " "
    s = KART_NO.sub(" ", s)
    s = _TAKSIT.sub(lambda m: " " if taksit(m.group()) or "taksit" in sade(m.group()) else m.group(), s)
    s = re.sub(_TARIH, " ", s)
    s = re.sub(_PARA, " ", s)
    s = re.sub(r"(?<!\d)\d{1,2}[./]\d{1,2}(?![\d.,])", " ", s)  # gün.ay
    s = re.sub(r"(?i)\b(?:USD|EUR|EURO|GBP|CHF)\b|[$€£]", " ", s)
    s = re.sub(r"(?i)\b(?:ref|referans|prov|onay|auth|kod|no)\s*[:.]?\s*\w*\d\w*", " ", s)
    s = re.sub(r"(?i)(?:www\.)|(?<=\w)\.(?:com|net|org|co)(?:\.\w{2})?\b", " ", s)  # trendyol.com -> trendyol
    s = re.sub(r"[*#_|:;]+|(?<=\w)-(?=\w)|\s-\s", " ", s)
    kelimeler = s.split()
    duz = lambda k: re.sub(r"[^a-z0-9-]", "", sade(k))  # noqa: E731
    # Baştaki "SANAL POS", "TAKSİTLİ İŞLEM" ve ödeme aracısı (IYZICO*TRENDYOL -> TRENDYOL)
    aracili = re.search(r"\w\s*[*/]\s*\w", aciklama) is not None
    while len(kelimeler) > 1 and (duz(kelimeler[0]) in _ON_KELIME or aracili and _ARACI.match(sade(kelimeler[0]) + " ")
                                  and len(duz(kelimeler[0])) >= 3):
        kelimeler.pop(0)
    kelimeler = [k for k in kelimeler if not re.fullmatch(r"\d+", duz(k)) and len(re.sub(r"\D", "", k)) < 5
                 and not re.search(r"(?i)taksit|^tks$|^kalan$|^toplam$|^iade|^iptal$", duz(k))]
    # İlk şehir/ilçe ya da ülke kodundan sonrası şube adresidir: 'SHELL ANKARA ESKISEHIR YOLU' -> 'SHELL'
    for i, k in enumerate(kelimeler):
        if i and (duz(k) in ILLER or duz(k) in _ULKE):
            kelimeler = kelimeler[:i]
            break
    while len(kelimeler) > 1 and len(duz(kelimeler[-1])) <= 1:
        kelimeler.pop()
    ad = " ".join(kelimeler).strip(" -.,/")
    if not re.search(r"[A-Za-zÇĞİÖŞÜçğıöşü]{2}", ad):
        return ""
    return tr_buyuk(ad)


def isyeri_anahtari(ad: str | None) -> str:
    """Öğrenilen işyeri eşleşmesinin anahtarı: ilk iki ayırt edici kelime ('MIGROS TICARET A.S.' -> 'migros')."""
    from .kural import unvan_cekirdegi
    kelimeler = (unvan_cekirdegi(ad) or "").split()
    return " ".join(kelimeler[:2])


def tur_tahmin(aciklama: str, tutar: float) -> str:
    s = sade(aciklama)
    if tutar > 0:
        if KART_MASRAFI.search(s) or PUAN.search(s):
            return "diger"  # faiz/ücret iadesi, puan kullanımı -> MUHTELİF BANKA İŞLEMLERİ
        if IADE.search(s):
            return "tahsilat"  # işyerinden iade: işyeri carisine ödediğimiz geri döner
        return "virman"  # kart borcu ödemesi: banka hesabından karta
    if KART_MASRAFI.search(s):
        return "banka_masrafi"
    if NAKIT_AVANS.search(s):
        return "nakit_cekim"
    return "odeme"  # işyerine yapılan harcama


# --- okuma -----------------------------------------------------------------

def _ozet_metinden(metin: str) -> dict:
    """Dönem borcu, önceki borç, asgari ödeme, hesap kesim ve son ödeme tarihi. Etiket ile değer aynı satırda
    ('Dönem Borcu : 12.345,67 TL') ya da etiketler bir satırda değerler alttaki satırda aynı sırayla olabilir."""
    ozet: dict = {}
    satirlar = [x for x in metin.splitlines() if x.strip()]
    for i, satir in enumerate(satirlar):
        s = sade(satir)
        hepsi = [(alan, m.start(), m.end()) for alan, desen in OZET.items() for m in re.finditer(desen, s)]
        # "önceki dönem borcu" içindeki "dönem borcu" ayrı etiket sayılmaz
        bulunan = sorted((b for b in hepsi if not any(d is not b and d[1] <= b[1] and b[2] <= d[2] and d[2] - d[1] > b[2] - b[1]
                                                     for d in hepsi)), key=lambda b: b[1])
        if not bulunan:
            continue
        for j, (alan, bas, son) in enumerate(bulunan):
            if alan in ozet:
                continue
            arada = s[son:bulunan[j + 1][1]] if j + 1 < len(bulunan) else s[son:]
            desen = _TARIH if alan in _TARIH_ALANLARI else _PARA
            m = re.match(rf"[^\d-]{{0,25}}?({desen})", arada)
            if m:
                ozet[alan] = tarih(m.group(1)) if alan in _TARIH_ALANLARI else para_coz(m.group(1))
        # Etiketler üst satırda, değerler alt satırda
        eksik = [b for b in bulunan if b[0] not in ozet]
        if eksik and len(eksik) == len(bulunan) and i + 1 < len(satirlar):
            alt = satirlar[i + 1]
            degerler = [m.group() for m in re.finditer(f"{_TARIH}|{_PARA}", alt)]
            if len(degerler) >= len(bulunan):
                for (alan, _, _), d in zip(bulunan, degerler):
                    ozet[alan] = tarih(d) if alan in _TARIH_ALANLARI else para_coz(d)
    for alan in ("donem_borcu", "onceki_borc", "asgari"):
        if alan in ozet and ozet[alan] is not None:
            ozet[alan] = abs(ozet[alan]) if alan == "asgari" else ozet[alan]
    return {k: v for k, v in ozet.items() if v is not None}


def _satir_tutari(govde: str, tk: tuple[int, int] | None) -> tuple[float, int, int] | None:
    """Satırdaki TL tutarı ve konumu. Döviz tutarı (USD 10,00) atlanır; taksitli satırda 'toplam / taksit tutarı'
    birlikte yazıyorsa taksit tutarı alınır. Puan sütunu tutarın ardından gelir, alınmaz."""
    adaylar = []
    for m in re.finditer(_PARA, govde):
        if _DOVIZ.search(govde[:m.start()]) and len(re.findall(_PARA, govde[m.end():])):
            continue
        adaylar.append((para_coz(m.group()), m.start(), m.end()))
    adaylar = [a for a in adaylar if a[0]]
    if not adaylar:
        return None
    if tk and len(adaylar) >= 2:
        n = tk[1]
        for toplam in adaylar:
            for parca in adaylar:
                if parca is not toplam and abs(abs(toplam[0]) - abs(parca[0]) * n) <= 0.02 * n + 0.05:
                    return parca
    return adaylar[0]


def _pdf_satirlari(metin: str) -> list[dict]:
    sonuc = []
    for satir in metin.splitlines():
        m = re.match(rf"\s*({_TARIH})(?:\s+{_TARIH})?\s+(.*)$", satir)
        if not m:
            continue
        t = tarih(m.group(1))
        govde = m.group(2)
        if not t or not re.search(r"[A-Za-zÇĞİÖŞÜçğıöşü]{2}", govde):
            continue
        tk = taksit(govde)
        bulunan = _satir_tutari(govde, tk)
        if not bulunan:
            continue
        tutar, bas, son = bulunan
        ilk = re.search(_PARA, govde)
        aciklama = " ".join(govde[:ilk.start() if _DOVIZ.search(govde[:ilk.start()]) is None else bas].split()) \
            or " ".join(re.sub(_PARA, " ", govde).split())
        isaret = "-" in govde[bas:son] or bool(re.match(r"\s*(?:\(?\+\)?|A|\(A\)|CR)(?:\s|$)", govde[son:]))
        sonuc.append({"tarih": t, "aciklama": aciklama, "tutar": abs(tutar), "alacak": isaret, "taksit": tk})
    return sonuc


def _sutunlar(baslik: list) -> dict | None:
    adlar = [sade(str(h or "")) for h in baslik]
    sutun: dict = {}
    for i, a in enumerate(adlar):
        if not a:
            continue
        if "tarih" in a:
            if "tarih" not in sutun or "islem" in a:
                sutun["tarih"] = i
        elif PUAN.search(a) or "doviz" in a or re.search(r"\b(usd|eur|kur)\b", a):
            continue
        elif a in ("b/a", "ba", "borc/alacak", "+/-", "yon", "(b/a)"):
            sutun["yon"] = i
        elif "taksit" in a and "tutar" in a:
            sutun["taksit_tutar"] = i
        elif "taksit" in a:
            sutun["taksit"] = i
        elif a.startswith("borc") or a in ("harcama", "harcamalar"):
            sutun.setdefault("borc", i)
        elif a.startswith("alacak") or a in ("odeme", "odemeler"):
            sutun.setdefault("alacak", i)
        elif "tutar" in a or a == "miktar":
            if "tutar" not in sutun or "tl" in a.split():
                sutun["tutar"] = i
        elif any(k in a for k in ("aciklama", "islem", "isyeri", "detay", "uye", "firma")):
            sutun.setdefault("aciklama", i)
    if "tarih" in sutun and ({"tutar", "borc", "alacak", "taksit_tutar"} & set(sutun)):
        return sutun
    return None


def _tablo_satirlari(satirlar: list[list]) -> list[dict]:
    for bas_i, satir in enumerate(satirlar[:60]):
        sutun = _sutunlar(satir)
        if sutun:
            break
    else:
        raise KuralHatasi("Kart ekstresinde 'Tarih' ve 'Tutar' sütunları bulunamadı.")

    def hucre(satir, ad):
        i = sutun.get(ad)
        return satir[i] if i is not None and i < len(satir) else None

    sonuc = []
    for satir in satirlar[bas_i + 1:]:
        t = tarih(hucre(satir, "tarih"))
        if not t:
            continue
        aciklama = str(hucre(satir, "aciklama") or "").strip()
        if not aciklama:
            aciklama = " ".join(str(v) for j, v in enumerate(satir) if isinstance(v, str) and j not in sutun.values()).strip()
        tk_metin = str(hucre(satir, "taksit") or "")
        tk = taksit(f"taksit {tk_metin}") if re.search(r"\d\s*/\s*\d", tk_metin) else taksit(aciklama)
        alacak = False
        tutar = para_coz(hucre(satir, "taksit_tutar")) or para_coz(hucre(satir, "tutar"))
        if not tutar and ("borc" in sutun or "alacak" in sutun):
            b, a = para_coz(hucre(satir, "borc")) or 0, para_coz(hucre(satir, "alacak")) or 0
            tutar, alacak = (abs(a), True) if a and not b else (abs(b), False)
        if not tutar:
            continue
        yon = sade(str(hucre(satir, "yon") or ""))
        if tutar < 0 or (yon and yon[0] in "a+"):
            alacak = True
        if tk and tk_metin and "taksit" not in sade(aciklama):
            aciklama = f"{aciklama} ({tk[0]}/{tk[1]} taksit)"
        sonuc.append({"tarih": t, "aciklama": aciklama, "tutar": abs(tutar), "alacak": alacak, "taksit": tk})
    return sonuc


def _metin(veri: bytes, mime: str) -> tuple[str, bool]:
    """Belgenin metni ve OCR ile mi okunduğu."""
    if mime == "application/pdf":
        metin = pdf_metni(veri)
        if len(metin.strip()) >= 30:
            return metin, False
    elif not mime.startswith("image/"):
        return "", False
    from . import ocr
    if not ocr.var_mi():
        raise KuralHatasi("Bu ekstre taranmış bir görüntü; okumak için yazı tanıma (Tesseract) kurulu olmalı. "
                          "Bankanızın internet şubesinden PDF ya da Excel ekstre indirin.")
    metin, _, _ = ocr.metne_cevir(veri, mime == "application/pdf")
    return metin, True


def tespit_metni(veri: bytes, mime: str) -> str:
    """Belgenin kart ekstresi olup olmadığını anlamak için metni (OCR yapılmaz)."""
    try:
        if mime == "application/pdf":
            return pdf_metni(veri)
        if mime.startswith("image/"):
            return ""
        return "\n".join(" ".join(str(v) for v in r if v not in (None, "")) for r in tablo_satirlari(veri, mime)[:80])
    except KuralHatasi:
        return ""


def ekstre_oku(veri: bytes, mime: str) -> dict:
    """Kart ekstresini okur. Dönüş: satirlar [{tarih, aciklama, tutar (işaretli), taksit, isyeri, onerilen_tur}],
    donem_borcu, onceki_borc, asgari, kesim_tarihi, son_odeme, kart_son4, fark (dönem borcu tutmuyorsa), ocr."""
    metin, ocr_ile = _metin(veri, mime)
    if metin:
        ham = _pdf_satirlari(metin)
    else:
        tablo = tablo_satirlari(veri, mime)
        metin = "\n".join(" ".join(str(v) for v in r if v not in (None, "")) for r in tablo)
        ham = _tablo_satirlari(tablo)
    ozet = _ozet_metinden(metin)
    # Özet bölümündeki tarihli satırlar (ör. "10.11.2026 Son Ödeme Tarihi 12.345,67") hareket sayılmaz.
    ham = [s for s in ham if not re.search("|".join(OZET.values()) + r"|kart\s+limiti|kullanilabilir\s+limit", sade(s["aciklama"]))]
    if not ham:
        raise KuralHatasi("Kart ekstresinde harcama satırı bulunamadı.")
    # Bazı bankalar alacak satırlarını işaretsiz yazar; o zaman açıklamadan anlaşılır.
    isaretli = any(s["alacak"] for s in ham)
    satirlar = []
    for s in ham:
        sa = sade(s["aciklama"])
        alacak = s["alacak"] if isaretli else bool(ODEME.search(sa) or IADE.search(sa) or
                                                   (PUAN.search(sa) and re.search(r"kullan|odeme", sa)))
        tutar = round(s["tutar"] if alacak else -s["tutar"], 2)
        tur = tur_tahmin(s["aciklama"], tutar)
        isyeri = isyeri_temizle(s["aciklama"]) if tur in ("odeme", "tahsilat") else ""
        satirlar.append({"tarih": s["tarih"].isoformat(), "aciklama": s["aciklama"], "tutar": tutar,
                         "taksit": list(s["taksit"]) if s["taksit"] else None, "isyeri": isyeri, "onerilen_tur": tur})
    satirlar.sort(key=lambda s: s["tarih"])  # sıra korunur (sort kararlıdır)
    toplam = round(sum(s["tutar"] for s in satirlar), 2)
    sonuc = {"satirlar": satirlar, **{k: (v.isoformat() if isinstance(v, date) else v) for k, v in ozet.items()},
             "kart_son4": kart_son4(metin), "banka": banka_adi(metin), "toplam": toplam, "ocr": ocr_ile, "fark": None}
    borc, onceki = ozet.get("donem_borcu"), ozet.get("onceki_borc")
    if borc is not None and onceki is not None:
        sonuc["fark"] = round(-borc - (-onceki + toplam), 2) or None
    # Satır bakiyeleri (mutabakat için): dönem borcundan geriye, yoksa önceki borçtan ileriye
    if borc is not None:
        kalan = -borc
        for s in reversed(satirlar):
            s["bakiye"] = round(kalan, 2)
            kalan -= s["tutar"]
    elif onceki is not None:
        b = -onceki
        for s in satirlar:
            b += s["tutar"]
            s["bakiye"] = round(b, 2)
    return sonuc
