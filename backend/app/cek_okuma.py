"""Çek/senet fotoğrafı ve taranmış PDF'ten yapay zekasız okuma (bilgisayarda çalışan Tesseract + karekod).

Bir sayfada birden çok çek olabilir: sayfa boş yatay şeritlerden bloklara bölünür, tarih ve tutar taşıyan her blok bir
çektir. Karekodlu çekte (2017 sonrası) karekoddaki rakamlar (çek no, banka/şube kodu, hesap no, keşideci VKN/TCKN)
yazıyla karşılaştırılır. Tutar rakamla ve yazıyla okunur; ikisi tutmazsa ya da okuma güveni düşükse alan "belirsiz"
işaretlenir (ekranda kırmızı). Tahmin edilen değer uydurulmaz: okunamayan alan boş kalır.
"""
import io
import re
from datetime import date

from . import kural

# Türkiye'deki bankalar: ekranda yazılacak ad ve metinde aranacak (sade) anahtarlar. Kod: EFT/karekod banka kodu.
BANKALAR = [
    ("0010", "Ziraat Bankası", ["ziraat bankasi", "ziraat"]), ("0012", "Halkbank", ["halk bankasi", "halkbank"]),
    ("0015", "VakıfBank", ["vakiflar bankasi", "vakifbank", "vakif bank"]), ("0046", "Akbank", ["akbank"]),
    ("0062", "Garanti BBVA", ["garanti"]), ("0064", "İş Bankası", ["is bankasi", "isbank"]),
    ("0067", "Yapı Kredi", ["yapi ve kredi", "yapi kredi"]), ("0111", "QNB", ["qnb", "finansbank"]),
    ("0032", "TEB", ["turk ekonomi bankasi", "teb "]), ("0134", "DenizBank", ["denizbank", "deniz bank"]),
    ("0099", "ING", ["ing bank"]), ("0123", "HSBC", ["hsbc"]), ("0059", "Şekerbank", ["sekerbank", "seker bank"]),
    ("0205", "Kuveyt Türk", ["kuveyt turk"]), ("0206", "Türkiye Finans", ["turkiye finans"]),
    ("0203", "Albaraka Türk", ["albaraka"]), ("0209", "Ziraat Katılım", ["ziraat katilim"]),
    ("0210", "Vakıf Katılım", ["vakif katilim"]), ("0211", "Emlak Katılım", ["emlak katilim"]),
    ("0146", "Odeabank", ["odeabank", "odea bank"]), ("0103", "Fibabanka", ["fibabanka"]),
    ("0135", "Anadolubank", ["anadolubank"]), ("0124", "Alternatif Bank", ["alternatif bank"]),
    ("0125", "Burgan Bank", ["burgan"]), ("0109", "ICBC Turkey", ["icbc"]), ("0143", "Aktif Bank", ["aktif yatirim", "aktif bank"]),
    ("0092", "Citibank", ["citibank"]),
]
_KODLAR = {kod: ad for kod, ad, _ in BANKALAR}


def banka_bul(metin: str | None) -> str | None:
    """Metindeki banka adının standart yazılışı ("T.C. ZİRAAT BANKASI A.Ş." -> "Ziraat Bankası")."""
    s = f" {kural.sade(metin or '')} "
    # Katılım bankaları ana bankadan önce aranır ("Ziraat Katılım" "Ziraat" değildir)
    for anahtar, ad in sorted(((a, ad) for _, ad, aa in BANKALAR for a in aa), key=lambda x: -len(x[0])):
        if f" {anahtar}" in s:
            return ad
    return None


def banka_anahtari(ad: str | None) -> str:
    """Aynı çek mi karşılaştırmasında banka adı: bilinen bankada standart ad, değilse sade yazılış."""
    return kural.sade(banka_bul(ad) or ad or "")


def cek_no_anahtari(no: str | None) -> str:
    return re.sub(r"[^0-9A-Z]", "", (no or "").upper()).lstrip("0")


# --- Yazıyla tutar ----------------------------------------------------------

_SAYILAR = {"bir": 1, "iki": 2, "uc": 3, "dort": 4, "bes": 5, "alti": 6, "yedi": 7, "sekiz": 8, "dokuz": 9,
            "on": 10, "yirmi": 20, "otuz": 30, "kirk": 40, "elli": 50, "altmis": 60, "yetmis": 70, "seksen": 80,
            "doksan": 90}
_CARPAN = {"yuz": 100, "bin": 1000, "milyon": 1_000_000, "milyar": 1_000_000_000}
_KELIMELER = sorted([*_SAYILAR, *_CARPAN], key=len, reverse=True)


def _yaziyi_coz(s: str) -> int | None:
    toplam = grup = 0
    okunan = False
    while s:
        k = next((k for k in _KELIMELER if s.startswith(k)), None)
        if k is None:
            return None
        s = s[len(k):]
        okunan = True
        if k in _SAYILAR:
            grup += _SAYILAR[k]
        elif k == "yuz":
            grup = (grup or 1) * 100
        else:
            toplam += (grup or 1) * _CARPAN[k]
            grup = 0
    return toplam + grup if okunan else None


def _en_uzun_sayi(harfler: str) -> int | None:
    """Harf dizisinin sonundaki en uzun yazıyla sayı ("yalnizonikibinbesyuz" -> 12500)."""
    for i in range(len(harfler)):
        if (n := _yaziyi_coz(harfler[i:])) is not None:
            return n
    return None


def yaziyla_tutar(metin: str) -> float | None:
    """"#ONİKİBİNBEŞYÜZ TÜRK LİRASI ELLİ KURUŞ#" -> 12500.5. Yazıyla tutar yoksa ya da çözülemezse None."""
    s = kural.sade(metin)
    s = re.sub(r"\btl\b", "lira", s)
    harfler = re.sub(r"[^a-z]", "", s)
    i = harfler.find("lira")
    if i <= 0:
        return None
    onu = harfler[max(i - 80, 0):i].removesuffix("turk")
    lira = _en_uzun_sayi(onu)
    if lira is None:
        return None
    sonra = harfler[i + 4:i + 40].removeprefix("si").removeprefix("ve")
    kurus = 0
    if (j := sonra.find("kurus")) > 0:
        kurus = _yaziyi_coz(sonra[:j]) or 0
    return round(lira + kurus / 100, 2)


# --- Metinden çek bilgileri -----------------------------------------------------

_TARIH = re.compile(r"(?<!\d)(\d{1,2})\s?[./-]\s?(\d{1,2})\s?[./-]\s?(\d{4})(?!\d)")
_TUTAR = re.compile(r"(?<![\d.,])(\d{1,3}(?:[.\s]\d{3})+|\d+),(\d{2})(?!\d)")
_VKN = re.compile(r"(?:V\.?\s?K\.?\s?N\.?|T\.?\s?C\.?\s?K\.?\s?N\.?|VERG[İI]\s*(?:K[İI]ML[İI]K\s*)?NO|T\.?C\.?\s*K[İI]ML[İI]K\s*NO)\D{0,6}(\d{10,11})",
                  re.IGNORECASE)
_CEK_NO = re.compile(r"(?:SER[İIı!1l|]\s*N[O0]|ÇEK\s*NO|CEK\s*NO|SENET\s*NO|ÇEK\s*SER[İIı!1l|]\s*N[O0])\s*[:.,]?\s*([A-Z]{0,2}\s?\d{4,10})", re.IGNORECASE)
_HESAP = re.compile(r"(?:HESAP\s*NO|HES\.?\s*NO|H\.\s*NO|HESAP\s*NUMARASI)\s*[:.]?\s*([\d\s-]{5,20}\d)", re.IGNORECASE)
_IBAN = re.compile(r"\bTR\s?\d{2}(?:\s?\d{4}){5}\s?\d{2}\b")
_SUBE = re.compile(r"([A-ZÇĞİÖŞÜ][A-ZÇĞİÖŞÜa-zçğıöşü./ -]{2,40}?)\s*(?:ŞUBES[İI]|SUBES[İI]|ŞB\.|ŞUBE\b|SUBE\b)", re.IGNORECASE)
_KESIDECI = re.compile(r"(?:KEŞ[İI]DEC[İI]|KESIDECI|HESAP\s*SAH[İI]B[İI]|DÜZENLEYEN|BORÇLU)\s*[:.]?\s*(.{3,80})", re.IGNORECASE)


def _tarih(g, a, y) -> date | None:
    try:
        return date(int(y), int(a), int(g))
    except ValueError:
        return None


_FIRMA_EKI = re.compile(r"(?i)\b(?:L[İI]M[İI]TED|Ş[İI]RKET[İI]|SIRKETI|LTD|A\.?\s?Ş\.?|ANON[İI]M|T[İI]CARET)\b")


def _basili_firma(satirlar: list[str]) -> str | None:
    """Çekin üstüne basılı keşideci firma adı (etiketsiz): şirket eki taşıyan, "EMRİNE" (lehtar) ve banka satırı olmayan satır."""
    for i, s in enumerate(satirlar):
        if not _FIRMA_EKI.search(s) or re.search(r"(?i)emr[İi]ne|bu\s*[çc]ek|bankas|ödeyin|t\.?c\.?k\.?n", s):
            continue
        ad = re.sub(r"(?i)^.*?\b(?:SER[İI]\s*NO|MERS[İI]S\s*NO|BAS\.?\s*TRH)[\s.,:]*\d*\s*", "", s)
        # Aynı satıra okunan basım tarihi ("17 OCAK 2025") ve numara kırıntısı ("NO: 0658...", "]") ad değildir
        ad = re.sub(r"(?i)^[\W\d_]*(?:\d{1,2}\s+)?(?:OCAK|[ŞS]UBAT|MART|N[İI]SAN|MAYIS|HAZ[İI]RAN|TEMMUZ|A[ĞG]USTOS|EYL[ÜU]L|EK[İI]M|"
                    r"KASIM|ARALIK)\s+\d{4}\b", "", ad)
        ad = re.sub(r"(?i)^\s*(?:NO\b)?[\W\d_]*", "", ad).strip(" .,:|>-")
        if i + 1 < len(satirlar) and re.match(r"(?i)\s*Ş[İI]RKET[İI]", satirlar[i + 1]) and not re.search(r"(?i)Ş[İI]RKET[İI]", ad):
            ad += " ŞİRKETİ"
        ad = re.sub(r"[^\w\s.&-]+$", "", ad).strip(" .")
        if anlamli_mi(ad) and not banka_bul(ad) and not re.search(r"(?i)\bkredi\b", ad):  # "Yapı ve Kredi A.Ş." bankadır
            return ad
    return None


def anlamli_mi(s: str | None) -> bool:
    """Ad/şube gibi yazı alanı anlamlı mı: en az bir 3 harfli kelime ve çoğu harf ("in dı", "i: ,|" gibi okuma
    kırıntısı değil)."""
    if not s:
        return False
    dolu = re.sub(r"\s", "", s)
    harf = len(re.findall(r"[^\W\d_]", s))
    return bool(re.search(r"[^\W\d_]{3,}", s)) and harf >= 4 and harf >= 0.6 * len(dolu)


def cek_metni_coz(metin: str, karekod: str | None = None, belirsiz_tutarlar: list[str] | None = None) -> dict:
    """Tek bir çekin metninden alanlar. Dönen sözlükte 'belirsiz' emin olunamayan alanların adlarıdır."""
    satirlar = [s.strip() for s in metin.splitlines() if s.strip()]
    sonuc: dict = {"tur": "senet" if re.search(r"\bSENED[İI]\b|\bSENET\b|EMRE\s*MUHARRER", metin, re.I) else "cek"}
    belirsiz: list[str] = []

    # Vade: "keşide tarihi"/"vade" yanındaki tarih; yoksa çekteki en geç tarih (ileri tarihli çek)
    tarihler = []
    for s in satirlar:
        for m in _TARIH.finditer(s):
            t = _tarih(*m.groups())
            if t and 2000 <= t.year <= 2100:
                tarihler.append((t, bool(re.search(r"ke[sş][iİ]de|vade|[oö]deme\s*tarih", s, re.I))))
    isaretli = [t for t, i in tarihler if i]
    sonuc["vade"] = (max(isaretli) if isaretli else max(t for t, _ in tarihler)).isoformat() if tarihler else None
    if not isaretli and len({t for t, _ in tarihler}) > 1:
        belirsiz.append("vade")

    # Tutar: rakamla yazılan (#12.500,00# gibi) ve yazıyla yazılan karşılaştırılır
    adaylar = []
    for s in satirlar:
        for m in _TUTAR.finditer(s):
            deger = float(re.sub(r"[.\s]", "", m.group(1)) + "." + m.group(2))
            yildiz = bool(re.search(r"[#*=]", s[max(m.start() - 3, 0):m.end() + 3])) or "TL" in s.upper()
            adaylar.append((deger, yildiz, m.group(0)))
    for s in satirlar:
        for m in re.finditer(r"#\s*(\d{1,3}(?:\.\d{3})+)(?![\d,])", s):  # el yazısı "#350.000#" (kuruşsuz)
            adaylar.append((float(m.group(1).replace(".", "")), True, m.group(0)))
    yazi = yaziyla_tutar(metin)
    rakam = next((d for d, y, _ in adaylar if y), None) or (max(d for d, _, _ in adaylar) if adaylar else None)
    if yazi and rakam and abs(yazi - rakam) < 0.01:
        sonuc["tutar"] = rakam
    elif rakam and not yazi and not any(y for _, y, _ in adaylar) and len({d for d, _, _ in adaylar}) > 1:
        # Ne "#...#"/TL işareti ne yazıyla tutar var, metinde birden çok sayı: hangisinin tutar olduğu bilinmez, boş kalır
        sonuc["tutar"] = None
        belirsiz.append("tutar")
    elif rakam:
        sonuc["tutar"] = rakam
        belirsiz.append("tutar")  # yazıyla tutar okunamadı ya da rakamla tutmuyor
        if yazi and any(abs(d - yazi) < 0.01 for d, _, _ in adaylar):
            sonuc["tutar"] = yazi
    elif yazi:
        sonuc["tutar"] = yazi
        belirsiz.append("tutar")
    else:
        sonuc["tutar"] = None
        belirsiz.append("tutar")
    if sonuc.get("tutar") and belirsiz_tutarlar and any(
            abs(kural.para_coz(x) or 0) == sonuc["tutar"] for x in belirsiz_tutarlar) and "tutar" not in belirsiz:
        belirsiz.append("tutar")

    sonuc["banka"] = banka_bul(metin)
    if not sonuc["banka"] and (m := re.search(r"TR\s*\d{2}\s*0\s*(\d)\s*(\d)\s*(\d)\s*(\d)", metin.upper())):
        sonuc["banka"] = _KODLAR.get("".join(m.groups()))  # IBAN'daki banka kodu (TRkk 0 BBBB ...)
    m = _SUBE.search(metin)
    sube = m.group(1).strip(" -/.") if m else None
    if sube and sonuc["banka"] and banka_bul(sube):
        sube = re.sub(r"(?i).*\b(?:bankas[ıi]|bank|a\.?ş\.?)\b", "", sube).strip(" -/.") or None
    sonuc["sube"] = sube
    m = _CEK_NO.search(metin)
    sonuc["cek_no"] = re.sub(r"\s", "", m.group(1)) if m else None
    m = _HESAP.search(metin)
    sonuc["hesap_no"] = re.sub(r"[\s-]", "", m.group(1)) if m else None
    if not sonuc["hesap_no"] and (m := _IBAN.search(metin.upper())):
        sonuc["hesap_no"] = re.sub(r"\s", "", m.group(0))
    m = _VKN.search(metin)
    sonuc["vkn"] = m.group(1) if m else None
    m = _KESIDECI.search(metin)
    kesideci = m.group(1).strip(" :.") if m else None
    if kesideci:
        kesideci = re.sub(r"\bL[I1İ]D\b", "LTD", kesideci)  # sık okuma hatası
        kesideci = re.split(r"\s{2,}|(?i:V\.?K\.?N|T\.?C\.?K\.?N|VERG[İI]|ADRES)", kesideci)[0].strip(" :.,") or None
    if kesideci and re.search(r"(?i)\bad[ıi]\b|soyad|imza", kesideci):
        kesideci = None  # "Keşidecinin Adı, Soyadı ve İmzası" etiketi
    if not kesideci:
        kesideci = _basili_firma(satirlar)
    sonuc["kesideci"] = kesideci
    # Lehtar: "Bu çek karşılığında ... emrine" (çekin kime yazıldığı)
    m = re.search(r"(?i)kar[şs][ıi]l[ıi][ğg][ıi]nda[\s:.]*(.+?)\s*(?:emr[İIi]ne|$)", metin, re.M)
    lehtar = m.group(1).strip(" .,:") if m else None
    # El yazısı lehtar sık bozuk okunur ("NES SA Ae 2. Mid. Ihe. LTO."): şirket ekleri dışında 4+ harfli bir kelime
    # yoksa uydurma yazı gösterilmez, alan boş ve kırmızı kalır
    kelimeler = [k for k in re.findall(r"[^\W\d_]{4,}", lehtar or "")
                 if not re.fullmatch(r"(?i)l[İIi]m[İIi]ted|[şs][İIi]rket[İIi]?|ticaret|sanayi|anon[İIi]m", k)]
    sonuc["lehtar"] = lehtar if lehtar and anlamli_mi(lehtar) and kelimeler else None

    # Anlamsız okunan yazı alanı doldurulmaz: boş kalır, ekranda kırmızı
    for alan in ("kesideci", "sube"):
        if sonuc.get(alan) and not anlamli_mi(sonuc[alan]):
            sonuc[alan] = None
            belirsiz.append(alan)
    if karekod:
        _karekodla_tamamla(sonuc, karekod, belirsiz)
    for alan in ("cek_no", "banka", "kesideci"):
        if not sonuc.get(alan):
            belirsiz.append(alan)
    sonuc["belirsiz"] = list(dict.fromkeys(belirsiz))
    return sonuc


# Çek karekodunun KKB biçimi: "KKB 00 <seri no 10> <banka kodu 4> <şube kodu 5> <hesap no 16> <VKN/TCKN 11> <MERSİS 16> ..."
_KKB = re.compile(r"KKB\s*\d{2}\s+(\d{10})\s+(\d{4})\s+(\d{5})\s+(\d{16})\s+(\d{11})")


def kkb_karekodu(karekod: str | None) -> dict | None:
    """Karekoddaki basılı bilgiler (bankanın bastığı, kesin): çek no, banka, şube kodu, hesap no, keşideci VKN/TCKN."""
    m = _KKB.search(karekod or "")
    if not m:
        return None
    seri, banka, sube, hesap, kimlik = m.groups()
    # 11 hane: TCKN; başında 0 olan 11 hane 10 haneli VKN'dir (TCKN 0 ile başlamaz)
    return {"cek_no": seri.lstrip("0") or "0", "banka_kodu": banka, "banka": _KODLAR.get(banka), "sube_kodu": sube.lstrip("0"),
            "hesap_no": hesap.lstrip("0") or "0", "vkn": kimlik[1:] if kimlik.startswith("0") else kimlik}


def _karekodla_tamamla(sonuc: dict, karekod: str, belirsiz: list[str]) -> None:
    """Çek karekodundaki rakamlar: 4 haneli banka kodu, 10/11 haneli VKN/TCKN, 16 haneli MERSİS; çek no ve hesap no
    yazıdan okunanla karşılaştırılır. Karekod biçimi bankadan bankaya ayraç farkı gösterebildiği için yalnız
    tanınan parçalar kullanılır."""
    if kkb := kkb_karekodu(karekod):
        # Karekod bankanın bastığı bilgidir: yazıdan okunanın yerine geçer
        for a in ("cek_no", "hesap_no", "vkn"):
            sonuc[a] = kkb[a]
            while a in belirsiz:
                belirsiz.remove(a)
        if kkb["banka"]:
            sonuc["banka"] = kkb["banka"]
        if not sonuc.get("sube"):
            sonuc["sube"] = kkb["sube_kodu"]
        return
    parcalar = re.findall(r"[0-9A-Z]+", karekod.upper())
    rakamlar = [p for p in parcalar if p.isdigit()]
    if (kod := next((p for p in rakamlar if len(p) == 4 and p in _KODLAR), None)) and not sonuc.get("banka"):
        sonuc["banka"] = _KODLAR[kod]
    vkn = next((p for p in rakamlar if len(p) in (10, 11)), None)
    if vkn:
        if sonuc.get("vkn") and sonuc["vkn"] != vkn:
            belirsiz.append("vkn")
        sonuc["vkn"] = vkn
    if sonuc.get("cek_no") and cek_no_anahtari(sonuc["cek_no"]) not in {cek_no_anahtari(p) for p in parcalar}:
        belirsiz.append("cek_no")
    if sonuc.get("hesap_no") and not any(p.endswith(sonuc["hesap_no"].lstrip("0")) for p in rakamlar):
        belirsiz.append("hesap_no")


# --- Görüntüden ----------------------------------------------------------------

def _bloklar(satirlar: list[tuple[int, str]]) -> list[list[str]]:
    """Okunan satırları (üst konum, metin) alt alta taranmış çeklere böler. Çekler arası boşluk, çekin kendi satır
    aralıklarından belirgin büyüktür: aralıklar sıralanıp en büyük sıçramanın üstündekiler ayraç sayılır."""
    if len(satirlar) < 2:
        return [[m for _, m in satirlar]]
    araliklar = [b[0] - a[0] for a, b in zip(satirlar, satirlar[1:])]
    sirali = sorted(set(araliklar))
    yukseklik = satirlar[-1][0] - satirlar[0][0] or 1
    esik = None
    for kucuk, buyuk in zip(sirali, sirali[1:]):
        if buyuk >= 2 * max(kucuk, 1) and buyuk >= yukseklik * 0.08:
            esik = buyuk
    bloklar = [[satirlar[0][1]]]
    for aralik, (_, m) in zip(araliklar, satirlar[1:]):
        if esik is not None and aralik >= esik:
            bloklar.append([])
        bloklar[-1].append(m)
    return bloklar


# Çek formundaki "ÇEK SERİ NO" (tarayıcı İ harfini !, 1, l okuyabilir)
_SERI_NO = re.compile(r"(?i)SER[İIı!1l|]\s*N[O0]|[ÇC]EK\s*SER")
_MIKR = re.compile(r"[0O]{6,}")  # çekin altındaki manyetik (MICR) satır: "1000009"012"1546:00000000 11 2233 44"


def _karekoda_gore_bol(satirlar: list[tuple[int, str]], kodlar: list[tuple[str, int]], img
                      ) -> list[tuple[str | None, list[str], tuple[int, int]]] | None:
    """Okunan satırları (resim okunurken büyütülmüş konumlarıyla) çeklere ayırır, her çeke kendi karekodunu ve resimdeki
    dikey aralığını verir. Her çek altındaki MICR satırıyla biter; karekodu okunamayan çek de böylece kaybolmaz.
    MICR satırları okunamadıysa sınır, sonraki karekodun biraz üstüdür. Karekod hiç yoksa yalnız MICR satırıyla biten
    ve "SERİ NO" taşıyan bloklar çektir. Sayfa döndürülerek okunduysa konumlar tutmaz: None."""
    w, h = img.size
    oran = 2400 / w if w < 2000 else min(4000 / w, 4000 / h, 1.0)
    if not satirlar or max(y for y, _ in satirlar) > h * oran * 1.1:
        return None
    aralik = lambda b: (int(b[0][0] / oran), int(b[-1][0] / oran) + int(60 / oran))  # noqa: E731
    kod_y = [y * oran for _, y in kodlar]
    bloklar: list[list[tuple[int, str]]] = [[]]
    mikr = 0
    for y, m in satirlar:
        bloklar[-1].append((y, m))
        if _MIKR.search(m) and len(re.findall(r"\d", m)) >= 10:
            bloklar.append([])
            mikr += 1
    # MICR'den sonra kalan ve çek bilgisi taşımayan satırlar bir önceki çeke katılır
    if not bloklar[-1] or (len(bloklar) > 1 and not _SERI_NO.search(" ".join(m for _, m in bloklar[-1]))):
        son = bloklar.pop()
        if bloklar:
            bloklar[-1] += son
        else:
            bloklar = [son]
    if not kodlar:
        seri = [b for b in bloklar if _SERI_NO.search(" ".join(m for _, m in b))]
        return [(None, [m for _, m in b], aralik(b)) for b in seri] if mikr and seri else None
    if len(bloklar) >= len(kodlar):
        sonuc = []
        kalan = list(zip(kodlar, kod_y))
        for i, b in enumerate(bloklar):
            ust = b[0][0] if i else -1e9
            alt = bloklar[i + 1][0][0] if i + 1 < len(bloklar) else 1e9
            kod = next((x for x in kalan if ust <= x[1] < alt), None)
            if kod:
                kalan.remove(kod)
            sonuc.append((kod[0][0] if kod else None, [m for _, m in b], aralik(b)))
        if not kalan:
            return sonuc
    sinirlar = [b - 0.15 * (b - a) for a, b in zip(kod_y, kod_y[1:])]
    gruplar: list[list[tuple[int, str]]] = [[] for _ in kod_y]
    for y, m in satirlar:
        gruplar[sum(1 for s in sinirlar if y >= s)].append((y, m))
    return [(k, [m for _, m in g], aralik(g)) for (k, _), g in zip(kodlar, gruplar) if g]


def _capraz_dogrula(c: dict, ikinci: list[str], karekodlu: bool) -> None:
    """Basılı alanlar (çek no, VKN, çeki yazan firma) iki ayrı okuma motoruyla karşılaştırılır: birinci okuma
    (Tesseract) ile çek bandının el yazısı modeliyle okunuşu tutmazsa alan kırmızı olur. Karekod okunduysa çek no ve
    VKN bankanın bastığı karekoddan gelir, karşılaştırılmaz. Çek no için hangisinin doğru olduğu, okunan bütün yazılarda
    (MICR satırı dahil) daha çok geçen rakamlardan seçilir."""
    if not ikinci:
        return
    r = cek_metni_coz(ikinci_metin := "\n".join(ikinci).translate(str.maketrans("ÍíÌì", "İiİi")))
    tum_rakam = re.sub(r"\D", "", ikinci_metin + "\n".join(c.get("_metinler") or []))
    ad = lambda x: re.sub(r"[^a-z]", "", kural.sade(x or "").split()[0] if (x or "").split() else "")  # noqa: E731
    for alan in ("cek_no", "vkn", "kesideci"):
        if karekodlu and alan in ("cek_no", "vkn"):
            continue
        a, b = c.get(alan), r.get(alan)
        if not a or not b:
            if not a and b and alan != "kesideci":  # birinci okuma bulamadı: ikinci okunuş önerilir, kırmızı
                c[alan] = b
                c["belirsiz"].append(alan)
            continue
        ayni = ad(a) == ad(b) if alan == "kesideci" else re.sub(r"\D", "", a) == re.sub(r"\D", "", b)
        if ayni:
            continue
        if alan == "cek_no" and tum_rakam.count(re.sub(r"\D", "", b)) > tum_rakam.count(re.sub(r"\D", "", a)):
            c[alan] = b
        if alan not in c["belirsiz"]:
            c["belirsiz"].append(alan)
        c.setdefault("nedenler", {})[alan] = "İki ayrı okuma farklı çıktı; çekteki ile karşılaştırın."


def _el_yazisi(img, ust: int, alt: int) -> dict:
    """Çek bandındaki el yazısı vade ve tutar: {alan: (değer, emin mi)}. Paket kurulu değilse boş."""
    from . import el_yazisi
    if not el_yazisi.var_mi():
        return {}
    try:
        # Model büyük resmi küçültür; el yazısı küçülmesin diye bant iki örtüşen yarıda okunur (yazıyla tutar solda,
        # tarih ve rakamla tutar sağda)
        ust = max(ust, 0)
        bant = img.crop((0, ust, img.width, min(alt + 20, img.height)))
        w = bant.width
        ayrinti = []
        for x0 in (0, int(w * 0.4)):
            for k in el_yazisi.ayrintili(bant.crop((x0, 0, x0 + int(w * 0.6), bant.height))):
                a, b, c, d = k["kutu"]
                ayrinti.append({**k, "kutu": [a + x0, b + ust, c + x0, d + ust]})  # sayfadaki konum
        # Çekin altındaki el yazısı notlar ("08.10.2026 teslim alındı", kaşe) vade sanılmasın: çekin en alt basılı
        # satırından (MICR ya da IBAN) aşağıdaki yazılar alınmaz
        alt_satir = [k["kutu"][3] for k in ayrinti if re.search(r"(?i)IBAN|0{6,}", k["m"])]
        if alt_satir:
            ayrinti = [k for k in ayrinti if k["kutu"][1] <= max(alt_satir) + 15]
        kutular = [k["m"] for k in ayrinti]
    except Exception as e:  # noqa: BLE001  # model çalışmazsa alanlar elle girilir
        return {"hata": f"El yazısı okunamadı: {e}"}
    vade = el_yazisi.vade_bul_nedenli(kutular, basim=basim_tarihi(kutular))
    tutar = el_yazisi.tutar_bul_nedenli(kutular)
    return {"vade": vade[:2], "tutar": tutar[:2], "nedenler": {"vade": vade[2], "tutar": tutar[2]}, "metinler": kutular,
            "ayrinti": ayrinti}


_AYLAR = ["ocak", "subat", "mart", "nisan", "mayis", "haziran", "temmuz", "agustos", "eylul", "ekim", "kasim", "aralik"]


def basim_tarihi(metinler: list[str]) -> date | None:
    """Çeke basılı "BAS.TRH. 17 OCAK 2025" / "BASIM TARİHİ 17OCAK2025": vade bundan önce olamaz."""
    for m in metinler:
        sade = re.sub(r"[^a-z0-9]", "", kural.sade(m))
        if (b := re.search(r"bas(?:im)?t(?:arih[i1]?|rh)(\d{1,2})([a-z0]+?)(20\d{2})", sade)):
            ay = next((i for i, a in enumerate(_AYLAR, 1) if b.group(2).replace("0", "o").startswith(a[:3])), None)
            try:
                return date(int(b.group(3)), ay, int(b.group(1))) if ay else None
            except ValueError:
                return None
    return None


def _karekodlar(img) -> list[tuple[str, int]]:
    """Sayfadaki karekodlar: (içerik, dikey orta nokta)."""
    try:
        import zxingcpp
    except ImportError:
        return []
    from PIL import ImageOps
    # Soluk ya da gri taranmış çekte karekod her ayarda okunmaz: ham resim, kontrastı açılmış hali ve birkaç eşikte
    # siyah-beyaz hali ayrı ayrı denenir, bulunanlar birleştirilir (ölçümde iki çekli gri sayfanın ikinci karekodu
    # yalnız eşiklenince çıktı)
    gri = img.convert("L")
    acik = ImageOps.autocontrast(gri, cutoff=2)
    sonuc: dict[str, int] = {}
    for v in [gri, acik] + [acik.point(lambda p, e=e: 255 if p > e else 0) for e in (90, 110, 130, 150)]:
        for kod in zxingcpp.read_barcodes(v):
            p = kod.position
            sonuc.setdefault(kod.text, (p.top_left.y + p.bottom_left.y) // 2)
    return list(sonuc.items())


def _cek_mi(metin: str) -> bool:
    return bool(_TARIH.search(metin) and (_TUTAR.search(metin) or yaziyla_tutar(metin)))


def cekleri_oku(veri: bytes, pdf: bool, tani: bool = False) -> list[dict]:
    """Dosyadaki her çek için okunan alanlar (sayfa sırasıyla). tani: her çeke okuma ayrıntısı (_tani) eklenir."""
    from . import el_yazisi, ocr
    el_motor = el_yazisi.motor_adi() if tani and el_yazisi.var_mi() else None
    cekler = []
    for sayfa_no, img in enumerate(ocr._goruntuler(veri, pdf), 1):
        w, h = img.size
        oran = 2400 / w if w < 2000 else min(4000 / w, 4000 / h, 1.0)  # okuma için büyütme (konumlar bu ölçekte)
        kodlar = sorted(_karekodlar(img), key=lambda k: k[1])
        kelimeler = ocr.sayfa_oku(img)
        satir: dict[tuple, list] = {}
        for k in kelimeler:
            if not ocr._gurultu_mu(k):
                satir.setdefault(k["s"], []).append(k)
        satirlar = sorted((min(k["y"] for k in s), " ".join(k["m"] for k in sorted(s, key=lambda k: k["x"])))
                          for s in satir.values())
        kkb = [(k, y) for k, y in kodlar if kkb_karekodu(k)]
        if gruplar := _karekoda_gore_bol(satirlar, kkb, img):
            # Banka çek formu (karekodlu ya da MICR satırlı): sayfa çeklere bölünür; blok yazısı az okunsa da çektir.
            # Tarih ve tutar elle yazılır: el yazısı modeli (isteğe bağlı) okur; emin değilse kırmızı, okunamazsa boş
            # Çek bandı: önceki çekin altından (MICR satırı) bu çekin altına; tarih çekin en üstündedir
            altlar = [a for _, _, (_, a) in gruplar]
            for i, (karekod, grup, (_, alt)) in enumerate(gruplar):
                ust = altlar[i - 1] if i else 0
                metin = ocr.duzelt("\n".join(grup))
                if not karekod and not _SERI_NO.search(metin):
                    continue
                c = cek_metni_coz(metin, karekod)
                el = _el_yazisi(img, ust, alt)
                c["_metinler"] = grup + el.get("metinler", [])  # lehtar (çekin yazıldığı firma) aranırken kullanılır
                _capraz_dogrula(c, el.get("metinler", []), bool(karekod and kkb_karekodu(karekod)))
                if tani:
                    c["_tani"] = {
                        "sayfa": sayfa_no, "bolme": "karekod" if kkb else "MICR satırı", "karekod_bulundu": bool(karekod),
                        "bant": {"ust": ust, "alt": alt}, "sayfa_boyu": list(img.size),
                        "basili_motor": "tesseract", "el_yazisi_motor": el_motor,
                        "basili": [{"m": k["m"], "g": k["g"], "x": k["x"], "y": k["y"]} for k in kelimeler
                                   if ust <= k["y"] / oran <= alt + 20],
                        "el_yazisi": el.get("ayrinti", []), "el_yazisi_hata": el.get("hata"),
                        "kural_okumasi": {a: c.get(a) for a in ("cek_no", "tutar", "vade", "kesideci", "lehtar")},
                        "el_yazisi_okumasi": {a: (str(el[a][0]) if el[a][0] is not None else None, el[a][1])
                                              for a in ("vade", "tutar") if a in el}}
                if not c.get("hesap_no"):
                    c["belirsiz"].append("hesap_no")
                for alan in ("vade", "tutar"):
                    if alan in c["belirsiz"] or (alan == "vade" and c.get("vade")):
                        c[alan] = None
                    deger, emin = el.get(alan, (None, False))
                    if deger is not None:
                        c[alan] = deger.isoformat() if alan == "vade" else deger
                    if emin:
                        while alan in c["belirsiz"]:
                            c["belirsiz"].remove(alan)
                    else:
                        if alan not in c["belirsiz"]:
                            c["belirsiz"].append(alan)
                        # Kırmızı alanın nedeni ekranda gösterilir (üstüne gelince)
                        c.setdefault("nedenler", {})[alan] = (el.get("nedenler") or {}).get(alan) or el.get("hata") or (
                            "El yazısı okuma paketi kurulu değil." if not el else None)
                c["sayfa"] = sayfa_no
                c["_bant"] = (sayfa_no, ust, alt)  # isteğe bağlı yapay zekaya yalnız bu çekin görüntüsü gönderilir
                cekler.append(c)
            continue
        parcalar = [ocr.duzelt("\n".join(b)) for b in _bloklar(satirlar)]
        # Tarih ve tutar taşımayan parça (çekin başlığı ya da keşideci/imza kısmı) komşusuna katılır
        while len(parcalar) > 1 and (i := next((i for i, p in enumerate(parcalar) if not _cek_mi(p)), None)) is not None:
            j = i - 1 if i > 0 else 1
            a, b = sorted((i, j))
            parcalar[a:b + 1] = [parcalar[a] + "\n" + parcalar[b]]
        parcalar = [p for p in parcalar if _cek_mi(p)]
        belirsiz_tutarlar = [k["m"] for k in kelimeler if k["g"] < ocr.DUSUK_GUVEN and re.search(r"\d[.,]\d{2}\b", k["m"])]
        for i, metin in enumerate(parcalar):
            # Karekodlar yukarıdan aşağı sırayla çeklere denk gelir (sayılar eşitse)
            karekod = kodlar[i][0] if len(kodlar) == len(parcalar) else None
            c = cek_metni_coz(metin, karekod, belirsiz_tutarlar)
            c["sayfa"] = sayfa_no
            cekler.append(c)
    return cekler


def lehtari_belirle(o: dict, sirket_unvan: str | None) -> None:
    """Çek bize mi yazılmış: okunan yazılardan biri firma adımıza benziyorsa lehtar firmamızdır (yeşil). Değilse okunan
    lehtar kırmızı kalır (el yazısı ad sık bozuk okunur). o["_metinler"] (çekteki okunan yazılar) burada kaldırılır."""
    cekten_okundu = "_metinler" in o
    metinler = (o.pop("_metinler", None) or []) + ([o["lehtar"]] if o.get("lehtar") else [])
    ilk = (kural.kendi_kelimeleri(sirket_unvan) or [""])[0]
    ilk_kelime = lambda m: (re.sub(r"[^a-z0-9 ]", " ", kural.sade(m or "")).split() or [""])[0]  # noqa: E731
    # Çeki biz yazdıysak (keşideci biziz) basılı firma adımız lehtar sayılmaz
    bizim_cek = bool(sirket_unvan and o.get("kesideci")
                     and (kural.firma_adi_benzer_mi(o["kesideci"], sirket_unvan) or (len(ilk) >= 4 and ilk_kelime(o["kesideci"]) == ilk)))
    # Ünvanın ayırt edici ilk kelimesiyle ("ARMA CRUP ENEPG MUH.") başlayan okunan satır da firmamızdır
    if sirket_unvan and not bizim_cek and (any(kural.firma_adi_benzer_mi(m, sirket_unvan) for m in metinler)
                                           or (len(ilk) >= 4 and any(ilk_kelime(m) == ilk for m in metinler))):
        o["lehtar"] = sirket_unvan
        o["belirsiz"] = [b for b in (o.get("belirsiz") or []) if b != "lehtar"]
    elif o.get("lehtar") or cekten_okundu:
        o["belirsiz"] = list(dict.fromkeys([*(o.get("belirsiz") or []), "lehtar"]))


def _ayni_kesideciyi_esitle(cekler: list[dict]) -> list[dict]:
    """Aynı dosyada aynı VKN'li (aynı keşidecinin) çeklerde keşideci adı ve şube, en çok okunan değerle yazılır:
    tek çekte yanlış okunan satır ("ŞİRKETİ", lehtar satırı) diğerlerinden düzelir."""
    from collections import Counter
    # Aynı keşideci: aynı VKN ya da (VKN okunamadıysa) aynı hesap no
    # Hesap no IBAN olarak da okunabilir: karşılaştırmada son 8 hane
    hesap = lambda c: re.sub(r"\D", "", c.get("hesap_no") or "")[-8:] or None  # noqa: E731
    hesap_vkn = {hesap(c): c["vkn"] for c in cekler if c.get("vkn") and hesap(c)}
    for c in cekler:
        if not c.get("vkn") and hesap(c) in hesap_vkn:
            c["_grup"] = hesap_vkn[hesap(c)]
    # Keşideci aynı kişi (VKN) ama bankası/şubesi hesaba göre değişir (aynı firmanın iki bankada hesabı olabilir)
    for alan, gecerli, anahtar_bul in (
            ("kesideci", anlamli_mi, lambda c: c.get("vkn") or c.get("_grup") or hesap(c)),
            ("sube", lambda x: bool(x) and not x.isdigit() and anlamli_mi(x), lambda c: hesap(c) or c.get("vkn")),
            ("banka", bool, hesap)):
        gruplar: dict[str, list[dict]] = {}
        for c in cekler:
            if anahtar := anahtar_bul(c):
                gruplar.setdefault(anahtar, []).append(c)
        for grup in gruplar.values():
            # "ONEM"/"ÖNEM" gibi harf farkları aynı ad sayılır; yazılış olarak Türkçe harfi doğru olan seçilir
            sayim = Counter(kural.sade(c[alan]) for c in grup if gecerli(c.get(alan)))
            if not sayim:
                continue
            anahtar, adet = max(sayim.items(), key=lambda x: (x[1], len(x[0])))
            en = max((c[alan] for c in grup if gecerli(c.get(alan)) and kural.sade(c[alan]) == anahtar),
                     key=lambda x: (sum(ch in "ÇĞİÖŞÜçğıöşü" for ch in x), x.isupper()))
            if adet < 2 and len(sayim) > 1:  # tek okunuşlar birbirini tutmuyor
                continue
            for c in grup:
                c[alan] = en
                if alan in c.get("belirsiz", []):
                    c["belirsiz"].remove(alan)
    for c in cekler:
        c.pop("_grup", None)
    return cekler


def dosyadan_oku(veri: bytes, ad: str, mime: str, tani: bool = False) -> list[dict]:
    """Yazılı PDF'te metin doğrudan, taranmış PDF ve fotoğrafta resimden okuma ile."""
    from . import ocr
    pdf = veri[:5] == b"%PDF-" or ad.lower().endswith(".pdf")
    if not pdf and not ocr.resim_mi(ad, mime):
        raise kural.KuralHatasi("Desteklenmeyen dosya türü (PDF ya da fotoğraf yükleyin).")
    metinden = []
    if pdf:
        metin = kural.pdf_metni(veri)
        if _cek_mi(metin):
            metinden = [{**cek_metni_coz(metin), "sayfa": 1}]
            if not taranmis_pdf_mi(veri):
                return metinden
    # Taranmış PDF (Adobe Scan, CamScanner...): içine gömülü tarayıcı yazısı çoğu zaman bozuktur. Resim ayrıca okunur,
    # hangisi daha çok alanı emin okuduysa o alınır
    if not ocr.var_mi():
        if metinden:
            return metinden
        raise kural.KuralHatasi(ocr.KURULU_DEGIL)
    resimden = _ayni_kesideciyi_esitle(cekleri_oku(veri, pdf, tani))
    if metinden and (not resimden or _puan(metinden) > _puan(resimden)):
        return metinden
    return resimden


_ALANLAR = ("vade", "tutar", "cek_no", "banka", "kesideci", "hesap_no", "sube")


def _puan(cekler: list[dict]) -> float:
    """Okumanın iyiliği: çek başına emin okunan alan sayısı."""
    return sum(sum(1 for a in _ALANLAR if c.get(a) and a not in c.get("belirsiz", [])) for c in cekler) / len(cekler)


def taranmis_pdf_mi(veri: bytes) -> bool:
    """Sayfanın çoğunu bir resim kaplıyorsa PDF taranmıştır (yazı, tarayıcının üstüne gömdüğü görünmez katmandır)."""
    try:
        import io
        import pdfplumber
        with pdfplumber.open(io.BytesIO(veri)) as belge:
            for sayfa in belge.pages[:3]:
                alan = float(sayfa.width * sayfa.height) or 1
                if any(abs((r["x1"] - r["x0"]) * (r["bottom"] - r["top"])) >= 0.4 * alan for r in sayfa.images):
                    return True
    except Exception:  # noqa: BLE001
        return False
    return False


# --- İsteğe bağlı yapay zeka desteği ----------------------------------------------------------------------------

def _yz_cekini_cevir(y: dict) -> dict:
    """Yapay zekanın okuduğu çek, programın çek alanlarına: tutar yalnız rakamla ve yazıyla aynıysa emin."""
    def tarih(s):
        try:
            return date.fromisoformat(s).isoformat() if s else None
        except ValueError:
            return None
    rakam, yazi = y.get("tutar_rakamla"), y.get("tutar_yaziyla_sayi")
    tutar_emin = rakam is not None and yazi is not None and abs(rakam - yazi) < 0.005
    vkn = re.sub(r"\D", "", y.get("cekin_yazani_vkn") or "")
    return {"tur": "cek", "cek_no": re.sub(r"\D", "", y.get("cek_no") or "") or None,
            "banka": banka_bul(y.get("banka")) or y.get("banka"), "sube": y.get("sube"),
            "hesap_no": re.sub(r"\s", "", y.get("hesap_no") or "") or None, "kesideci": y.get("cekin_yazani"),
            "vkn": vkn if len(vkn) in (10, 11) else None, "lehtar": y.get("lehtar"), "vade": tarih(y.get("vade")),
            # Çek Kanunu: yazı ile rakam farklıysa yazıyla yazılan geçerli
            "tutar": yazi if yazi is not None else rakam, "_tutar_emin": tutar_emin,
            "para_birimi": (y.get("para_birimi") or "TRY").upper().replace("TL", "TRY")[:3]}


def yapay_zekayla_tamamla(cekler: list[dict], yz_cekleri: list[dict]) -> list[dict]:
    """Kural tabanlı okumanın boş ya da kırmızı bıraktığı alanlar yapay zekanın okuduğuyla doldurulur.
    Emin okunmuş alana dokunulmaz. Yapay zekanın değeri de emin sayılmaz (kırmızı kalır); yalnız tutar rakamla ve
    yazıyla aynı okunduysa, vade de kural okumasıyla aynıysa yeşil olur. Eşleştirme çek no ile, olmazsa sırayla."""
    yz = [_yz_cekini_cevir(y) for y in yz_cekleri]
    no = lambda c: cek_no_anahtari(c.get("cek_no"))  # noqa: E731
    kalan = list(yz)
    for i, c in enumerate(cekler):
        e = next((y for y in kalan if no(y) and no(y) == no(c)), None)
        if e is None and len(yz) == len(cekler) and yz[i] in kalan:
            e = yz[i]
        if e is None:
            continue
        kalan.remove(e)
        belirsiz = c.setdefault("belirsiz", [])
        doldurulan = []
        for alan in ("cek_no", "banka", "sube", "hesap_no", "kesideci", "vkn", "lehtar"):
            if e.get(alan) and (not c.get(alan) or alan in belirsiz):
                c[alan] = e[alan]
                doldurulan.append(alan)
                if alan not in belirsiz and alan not in ("vkn", "lehtar"):  # lehtar sonra firmamızla karşılaştırılır
                    belirsiz.append(alan)
        if "tutar" in belirsiz or not c.get("tutar"):
            if e.get("tutar") is not None:
                c["tutar"] = e["tutar"]
                doldurulan.append("tutar")
                if e["_tutar_emin"]:
                    belirsiz[:] = [b for b in belirsiz if b != "tutar"]
                elif "tutar" not in belirsiz:
                    belirsiz.append("tutar")
        if "vade" in belirsiz or not c.get("vade"):
            if e.get("vade"):
                ayni = c.get("vade") == e["vade"]
                c["vade"] = e["vade"]
                doldurulan.append("vade")
                if ayni:
                    belirsiz[:] = [b for b in belirsiz if b != "vade"]
                elif "vade" not in belirsiz:
                    belirsiz.append("vade")
        if doldurulan:
            c["yz_alanlar"] = doldurulan
    # Kural okumasının hiç bulamadığı çekler: bütün alanlar yapay zekadan, tutar dışında hepsi kırmızı
    for e in kalan:
        c = {k: v for k, v in e.items() if not k.startswith("_")}
        c["belirsiz"] = ["cek_no", "banka", "sube", "hesap_no", "kesideci", "vade"] + ([] if e["_tutar_emin"] else ["tutar"])
        c["yz_alanlar"] = [a for a in ("cek_no", "banka", "sube", "hesap_no", "kesideci", "lehtar", "vade", "tutar") if c.get(a)]
        cekler.append(c)
    return cekler


def okuma_raporu(dosyalar: list[tuple[str, bytes, str]]) -> bytes:
    """İsteğe bağlı okuma raporu (ZIP): her çek için hangi yolla bulunduğu (karekod / MICR satırı), çek bandının
    sınırları, çalışan okuma motorları, alan alan okunan ham yazılar, güven puanları ve konumları, kırmızı alanların
    nedeni ve çek bandının resmi. Yalnız kullanıcı isteyince üretilir; API anahtarı ve karekodun ham içeriği yazılmaz."""
    import json
    import zipfile
    from . import ocr
    tampon = io.BytesIO()
    with zipfile.ZipFile(tampon, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("BENI-OKU.txt", "Çek okuma raporu\n\nHer dosya için bir klasör vardır. rapor.json: okunan alanlar, "
                   "kırmızı alanlar ve nedenleri, okuma ayrıntısı (motor, ham yazı, güven puanı 0-1 ya da 0-100, "
                   "konum). cek-N.jpg: okunan çek bandı.\nÇek bilgisi içerir: yalnız güvendiğiniz kişiyle paylaşın.\n")
        for n, (ad, veri, mime) in enumerate(dosyalar, 1):
            klasor = f"{n:03d}_{re.sub(r'[^0-9A-Za-z._-]+', '_', ad)[:60]}/"
            try:
                cekler = dosyadan_oku(veri, ad, mime, tani=True)
            except kural.KuralHatasi as e:
                z.writestr(klasor + "rapor.json", json.dumps({"hata": str(e)}, ensure_ascii=False, indent=1))
                continue
            pdf = veri[:5] == b"%PDF-" or ad.lower().endswith(".pdf")
            sayfalar = list(ocr._goruntuler(veri, pdf)) if any(c.get("_bant") for c in cekler) else []
            rapor = []
            for i, c in enumerate(cekler, 1):
                if c.get("_bant") and sayfalar:
                    sayfa, ust, alt = c["_bant"]
                    img = sayfalar[sayfa - 1]
                    z.writestr(f"{klasor}cek-{i}.jpg", _jpeg(img.crop((0, max(ust, 0), img.width, min(alt + 20, img.height)))))
                rapor.append({"cek": i, **{k: v for k, v in c.items() if not k.startswith("_")},
                              "okuma": c.get("_tani") or {"not": "Yazılı PDF: çek metni doğrudan okundu."}})
            z.writestr(klasor + "rapor.json", json.dumps(rapor, ensure_ascii=False, indent=1, default=str))
    return tampon.getvalue()


YZ_ALANLARI = ("cek_no", "banka", "kesideci", "tutar", "vade")


def _jpeg(img) -> bytes:
    img = img.convert("RGB")
    img.thumbnail((2400, 2400))
    tampon = io.BytesIO()
    img.save(tampon, "JPEG", quality=88)
    return tampon.getvalue()


def yapay_zekayla_eksikleri_oku(veri: bytes, ad: str, cekler: list[dict]) -> list[dict]:
    """İsteğe bağlı yapay zeka desteği, en az veriyle: kural okuması çekleri bulduysa yalnız boş ya da kırmızı alanı
    olan çeklerin görüntüsü (çek bandı) gönderilir, sorunsuz okunan çekler ve sayfanın geri kalanı gönderilmez.
    Kural okuması hiç çek bulamadıysa sayfalar gönderilir. Sonuç taslaktır: kaydedilmez, kullanıcı kontrol eder."""
    from . import ai, ocr
    if not cekler or not all(c.get("_bant") for c in cekler):
        return yapay_zekayla_tamamla(cekler, yapay_zekayla_oku(veri, ad))
    pdf = veri[:5] == b"%PDF-" or ad.lower().endswith(".pdf")
    sayfalar = None
    for c in cekler:
        if not any(not c.get(a) or a in c.get("belirsiz", []) for a in YZ_ALANLARI):
            continue
        if sayfalar is None:
            sayfalar = list(ocr._goruntuler(veri, pdf))
        sayfa, ust, alt = c["_bant"]
        img = sayfalar[sayfa - 1]
        bant = img.crop((0, max(ust, 0), img.width, min(alt + 20, img.height)))
        if yz := ai.cek_sayfasi_oku(_jpeg(bant))[:1]:
            yapay_zekayla_tamamla([c], yz)
    return cekler


def yapay_zekayla_oku(veri: bytes, ad: str) -> list[dict]:
    """Dosyanın sayfaları resim olarak yapay zekaya gönderilir (taranmış PDF'in bozuk yazı katmanı kullanılmaz)."""
    from . import ai, ocr
    pdf = veri[:5] == b"%PDF-" or ad.lower().endswith(".pdf")
    sonuc = []
    for img in ocr._goruntuler(veri, pdf):
        sonuc += ai.cek_sayfasi_oku(_jpeg(img))
    return sonuc
