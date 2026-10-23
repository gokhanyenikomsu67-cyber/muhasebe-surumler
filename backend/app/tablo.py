"""PDF faturadaki kalem tablosunu firmaya özel düzen aramadan, sütun başlıklarına göre okur.

Her firmanın tablosu farklıdır; ama hepsinde mal/hizmet adı, miktar, birim fiyat, (varsa) iskonto, KDV ve tutar
sütunları vardır. Tablo PDF'teki çizgilerden bulunur (pdfplumber), başlık hücreleri eş anlamlılarla eşlenir,
hücre içinde alt satıra bölünmüş adlar birleştirilir. Her satır kendi içinde denetlenir (miktar x fiyat, KDV),
toplam faturanın alt toplamını tutmazsa sonuç kullanılmaz ve eski okuma yöntemleri denenir.
"""
import io
import re

from .kural import BIRIMLER, _miktar, _tevkifat_bilgisi, para_coz, sade

# Başlık -> alan. Sıra önemli: önce daha özel adlar ("net birim fiyat" "birim fiyat"tan önce).
_ALANLAR = [
    ("sira", r"^(s[ıi]ra( no)?|s\.? ?n\.?|#|no)$"),
    ("kdvli", r"kdv.?l[ıi]|kdv dahil|vergiler dahil"),
    ("kdvt", r"kdv tutar|kdv tutari|hesaplanan kdv"),
    ("kdv", r"kdv( oran[ıi]?| ?%| o\.?)?$|kdv oran"),
    ("iskt", r"(iskonto|isk\.?|indirim)( ?/ ?arttirim)? tutar"),
    ("isko", r"(iskonto|isk\.?|indirim)( ?/ ?arttirim)?( oran[ıi]?| ?%|\d)?$"),
    ("netfiy", r"net birim fiyat"),
    ("fiy", r"birim fiyat|^fiyat"),
    ("mik", r"miktar|^adet$"),  # nakliye faturası: "Adet" sütunu miktardır
    ("birim", r"^birim$|^birimi$"),
    ("diger", r"diger vergi|vergi muafiyet|otv|not$|^k\.? ?v$|konaklama ver"),
    ("not", r"satir aciklama"),  # "Birim:ADET" gibi notlar; ada katılmaz
    ("kod", r"kod"),
    ("tut", r"tutar|^toplam$"),
    # nakliye faturasında taşınan iş "Gönderen / Alıcı" sütununa yazılır, "Mamül Cinsi" çoğu zaman boştur
    ("ad", r"mal|hizmet|urun|malzeme|cinsi|aciklama|stok adi|gonderen"),
]


def _temiz(satirlar: list) -> list:
    """Bağlı harf ("ti") bazı PDF'lerde boş karakter çıkar: "Özelleş\\x00rme" (pdf_metni ile aynı düzeltme)."""
    return [[h.replace("\x00", "ti") if h else h for h in s] for s in satirlar]


def _alan(baslik: str) -> str | None:
    b = re.sub(r"\s+", " ", sade(baslik or ""))
    b = re.sub(r"\bk\. ?d\. ?v\.?", "kdv", b).strip(" .:")  # "K.D.V. Oranı"
    if not b:
        return None
    for alan, desen in _ALANLAR:
        if re.search(desen, b):
            if alan == "tut" and re.search(r"iskonto|kdv", b):
                continue
            return alan
    return None


def _sayi(hucre: str | None) -> float | None:
    if not hucre:
        return None
    m = re.search(r"-?\d[\d.,]*", hucre.replace(" ", ""))
    return para_coz(m.group(0)) if m else None


def _miktar_birim(hucre: str) -> tuple[float | None, str | None]:
    m = re.match(r"\s*(\d[\d.,]*)\s*([A-Za-zÇĞİÖŞÜçğıöşü²³0-9]*\.?)", (hucre or "").replace("\n", " "))
    if not m:
        return None, None
    birim = m.group(2) or None
    if birim:
        birim = re.sub(r"\((?:NIU|C62|[A-Z]{3})\)$", "", birim) or None
    return _miktar(m.group(1)), BIRIMLER.get(birim or "", birim)


def _metin(hucre: str | None, kod: bool = False) -> str:
    """Hücrenin satırlarını birleştirir. Satır sonu '-' ise ("SARI-⏎YEŞİL") ve kodlarda ("ZEY.FK.50-⏎08-40",
    "M.U.AL⏎G.00006") boşluk konmaz."""
    satirlar = [" ".join(x.split()) for x in (hucre or "").splitlines() if x.strip()]
    sonuc = ""
    for x in satirlar:
        bitisik = sonuc and (sonuc.endswith(("-", "/")) or kod and (sonuc.endswith(".") or x.startswith(("-", ".", "/"))
                                                                    or (" " not in sonuc and " " not in x and re.search(r"[.\-]", sonuc))))
        sonuc = f"{sonuc}{x}" if bitisik else f"{sonuc} {x}".strip()
    return sonuc


def _sutunlar(baslik: list) -> list[str | None] | None:
    """Başlık hücrelerini alanlara eşler. Başlığı boş sütun (birleşik hücre) soldakine aittir."""
    alanlar, son = [], None
    for h in baslik:
        a = _alan(h)
        if a is None and not (h or "").strip():
            a = son and f"+{son.lstrip('+')}"
        alanlar.append(a)
        son = a or son
    adlar = {a for a in alanlar if a}
    # Miktar sütunu olmayabilir (restoran, otel: "Açıklama | Vergiler Dahil | KDV | Net Tutar"): miktar 1 sayılır
    if "ad" not in adlar or not ({"tut", "fiy", "netfiy"} & adlar):
        return None
    return alanlar


def _satir_alanlari(alanlar: list, satir: list) -> dict[str, list[str]]:
    d: dict[str, list[str]] = {}
    for a, h in zip(alanlar, satir):
        if a and h and h.strip():
            d.setdefault(a.lstrip("+"), []).append(h)
    return d


def _kalem(d: dict[str, list[str]], oran: float | None = None) -> dict | None:
    """Bir tablo satırından kalem. Tutar, fiyat ya da ad yoksa None."""
    ilk = lambda a: d.get(a, [None])[0]  # noqa: E731
    adlar = [_metin(x) for x in d.get("ad", []) if _metin(x)]
    ad = ""
    for x in adlar:  # ürün adı ve açıklaması aynıysa ya da biri ötekini içeriyorsa bir kez
        if sade(x) in sade(ad):
            continue
        ad = x if sade(ad) in sade(x) else f"{ad} - {x}" if ad else x
    kodlar = [_metin(x, kod=True) for x in d.get("kod", []) if _metin(x)]
    if not ad and kodlar and re.search(r"[A-Za-zÇĞİÖŞÜçğıöşü]{3,}.*\s", _metin(d["kod"][0])):
        ad, kodlar = _metin(d["kod"][0]), []  # ad "Malzeme / Hizmet Kodu" sütununa yazılmış, açıklama boş
    if not ad:
        return None
    miktar, birim = _miktar_birim(ilk("mik") or "")
    if ilk("birim"):
        b = _metin(ilk("birim"))
        birim = BIRIMLER.get(b, b)
    fiyat = _miktar(re.sub(r"[^\d.,]", "", ilk("fiy") or "")) if ilk("fiy") else None
    netfiy = _miktar(re.sub(r"[^\d.,]", "", ilk("netfiy") or "")) if ilk("netfiy") else None
    # Birden çok tutar sütunu ("Brüt Tutar", "İsk. Sonrası Brüt Tutar"): en sağdaki son tutardır
    tutar = next((x for x in (_sayi(h) for h in reversed(d.get("tut", []))) if x is not None), None)
    kdvt, kdvli = _sayi(ilk("kdvt")), _sayi(ilk("kdvli"))
    isko = [x for x in (_sayi(h) for h in d.get("isko", [])) if x]
    iskt = _sayi(ilk("iskt"))
    kdv = _sayi(ilk("kdv"))
    # "1.290,91 TL(%10)": KDV sütununda tutar ve oran birlikte
    m = re.search(r"(\d[\d.,]*)\s*(?:TL|TRY|USD|EUR)?\s*\(\s*%\s*(\d+(?:[.,]\d+)?)\s*\)", ilk("kdv") or "")
    if m:
        kdvt, kdv = kdvt if kdvt is not None else para_coz(m.group(1)), para_coz(m.group(2))
    # Diğer vergiler: "KONAKLAMA VER. (%2,00)=58,04TL", "KV (%2,00) = 50,00 TL", "80,36 TL (%2)"
    # Stopaj ("GELİR VERGİSİ STOPAJI (%5,00)=96.790,96 TL") diğer vergi değildir: ödenecekten düşülür, oranı kaleme yazılır.
    # Aynı hücredeki KDV tevkifatı ayrıca okunur, diğer vergiye katılmaz.
    diger = 0.0
    stopaj_orani = None
    for h in d.get("diger", []):
        h = " ".join(h.split())
        parcalar = list(re.finditer(r"([^=()]*?)\(?\s*%\s*([\d.,]+)\s*\)?\s*=\s*(\d[\d.,]*)", h))
        if parcalar:
            for m in parcalar:
                etiket = sade(m.group(1))
                if re.search(r"stopaj|stpj", etiket):
                    stopaj_orani = para_coz(m.group(2))
                elif not re.search(r"tevk", etiket) and para_coz(m.group(3)):
                    diger += para_coz(m.group(3))
            continue
        m = re.search(r"=\s*(\d[\d.,]*)", h) or re.match(r"(\d[\d.,]*)\s*(?:TL|TRY)?\s*\(\s*%", h)
        if m and para_coz(m.group(1)) and not re.search(r"stopaj|stpj|tevk", sade(h)):
            diger += para_coz(m.group(1))
    miktar = miktar or 1
    if tutar is None and kdvli is not None and kdvt is not None:
        tutar = round(kdvli - kdvt, 2)
    if tutar is None and (netfiy or fiyat) is not None:
        tutar = round(miktar * (netfiy or fiyat), 2)
    if tutar is None:
        return None
    # Tutar sütunu iskonto öncesi yazılmış olabilir: KDV iskonto sonrası tutar üzerindendir.
    if iskt and kdvt is not None and kdv and abs((tutar - iskt) * kdv / 100 - kdvt) <= 0.05 + 0.001 * kdvt \
            and abs(tutar * kdv / 100 - kdvt) > 0.05:
        tutar = round(tutar - iskt, 2)
    if kdv is None and kdvt is not None and tutar:
        kdv = min((0, 1, 8, 10, 18, 20), key=lambda o: abs(tutar * o / 100 - kdvt))
        if abs(tutar * kdv / 100 - kdvt) > 0.05 + 0.001 * kdvt:
            kdv = round(kdvt / tutar * 100, 2)
    if kdv is None and kdvt is None:
        kdv = oran  # KDV sütunu yok: faturanın toplam KDV oranı
    liste = fiyat if fiyat is not None else netfiy
    if liste is None:
        liste = round(tutar / miktar, 6)
    if kodlar and kodlar[0].replace(" ", "") not in ad.replace(" ", ""):
        # Kod sütununa ad yazılmış olabilir ("MESLEKİ EĞİTİM VE BELGELENDİRME"): rakamsız ve boşluklu ise ada katılır
        ad = f"{kodlar[0]} {ad}" if " " in kodlar[0] and not re.search(r"\d", kodlar[0]) else f"{ad} ({kodlar[0]})"
    kalem = {"aciklama": ad, "miktar": miktar, "birim": birim, "birim_fiyat": liste, "kdv_orani": kdv or 0, "tutar": tutar}
    if kdvt is not None and kdv and abs(tutar * kdv / 100 - kdvt) > 0.05 + 0.001 * kdvt:
        kalem["kdv_tutari"] = kdvt
    # tutar 0 olabilir: %100 iskontolu bedelsiz kalem (Nova "120 CM L AYAK" 6 x 566,99, İskonto %100)
    if abs(miktar * liste - tutar) > max(0.05, 0.002 * abs(tutar)) and tutar >= 0 and liste and miktar * liste > tutar:
        isk = round(miktar * liste - tutar, 2)
        yuzde = isko[0] if len(isko) == 1 and abs(miktar * liste * isko[0] / 100 - isk) <= max(0.05, 0.002 * tutar) \
            else round(isk / (miktar * liste) * 100, 2)
        kalem["iskonto_orani"], kalem["iskonto_tutari"] = yuzde, isk
    pay, kod = _tevkifat_bilgisi(" ".join(_metin(h) for v in d.values() for h in v))
    if pay and kalem["kdv_orani"]:
        kalem["tevkifat_orani"], kalem["tevkifat_kodu"] = pay, kod
    # Satırda yazan KDV ve diğer vergi tutarı: tutar sütunu vergiler dahil yazılmışsa net tutarı bulmak için
    # (kural.kalemleri_uzlastir kullanır, sonra silinir)
    if kdvt is not None:
        kalem["_kdvt"] = kdvt
    if diger:
        kalem["_diger"] = round(diger, 2)
    if stopaj_orani:
        kalem["stopaj_orani"] = stopaj_orani
    return kalem


def _sira_mi(d: dict) -> bool:
    """Yeni kalemin satırı mı, yoksa üstteki kalemin alt satıra bölünmüş devamı mı?"""
    return any(k in d for k in ("mik", "tut", "fiy", "netfiy", "kdvt", "kdvli"))


def _sutun_sec(sutunlar: list[tuple[str | None, float, float]], x0: float, x1: float) -> str | None:
    """Konumu verilen hücre/kelime hangi başlık sütununun altında? Önce en çok örtüşen, yoksa ortası en yakın."""
    adaylar = [s for s in sutunlar if s[0]]
    if not adaylar:
        return None
    ortusen = max(adaylar, key=lambda s: min(x1, s[2]) - max(x0, s[1]))
    if min(x1, ortusen[2]) - max(x0, ortusen[1]) > 0:
        return ortusen[0]
    orta = (x0 + x1) / 2
    return min(adaylar, key=lambda s: abs(orta - (s[1] + s[2]) / 2))[0]


def _satirlar(kelimeler: list[dict]) -> list[list[dict]]:
    """Kelimeleri satırlara toplar (aynı satırdaki yazılar birkaç birim yukarı-aşağı kayabilir)."""
    satirlar: list[list[dict]] = []
    for w in sorted(kelimeler, key=lambda w: (w["top"], w["x0"])):
        if satirlar and abs(w["top"] - satirlar[-1][0]["top"]) <= 3:
            satirlar[-1].append(w)
        else:
            satirlar.append([w])
    return [sorted(x, key=lambda w: w["x0"]) for x in satirlar]


_SON = re.compile(r"^(mal|malzeme|urun)?\s*/?\s*(hizmet)?\s*toplam|^toplam|^yalniz|^ara toplam|^genel toplam|^kdv matrah|^not\s*:")


def _kelimelerle_satirlar(satirlar: list[list[dict]], sutunlar: list[tuple[str | None, float, float]]) -> list[dict]:
    """Çizgisiz tablo: başlığın altındaki her kelime, konumuna göre başlık sütununa yazılır. Tutar ya da miktar
    taşıyan satır yeni kalemdir; hemen altındaki yalnız ad taşıyan satır adın devamıdır."""
    sonuc, onceki, son_alt = [], None, None
    for satir in satirlar:
        metin = sade(" ".join(w["text"] for w in satir)).strip()
        if _SON.search(metin):
            break
        if son_alt is not None and satir[0]["top"] - son_alt > (40 if not sonuc else 18):
            break
        d: dict[str, list[str]] = {}
        for w in satir:
            alan = _sutun_sec(sutunlar, w["x0"], w["x1"])
            if alan:
                d.setdefault(alan, []).append(w["text"])
        d = {a: [" ".join(v)] for a, v in d.items()}
        son_alt = max(w["bottom"] for w in satir)
        if _sira_mi(d) and ("ad" in d or "kod" in d or onceki is None or "sira" in d):
            onceki = d
            sonuc.append(d)
        elif onceki is not None and "ad" in d and set(d) <= {"ad", "kod", "not"}:
            onceki["ad"] = [f"{onceki.get('ad', [''])[0]}\n{d['ad'][0]}".strip()]
        elif not d:
            continue
        elif sonuc:
            break
    return sonuc


def _baslik_sutunlari(satir: list[dict]) -> list[tuple[str | None, float, float]] | None:
    """Çizgisiz tablonun başlık satırı: aralarında boşluk az olan kelimeler bir başlıktır ("Birim Fiyat")."""
    obekler: list[list[dict]] = []
    for w in satir:
        if obekler and w["x0"] - obekler[-1][-1]["x1"] < 5.5:
            obekler[-1].append(w)
        else:
            obekler.append([w])
    sutunlar = []
    for o in obekler:
        alan = _alan(" ".join(w["text"] for w in o))
        if alan:
            sutunlar.append((alan, o[0]["x0"], o[-1]["x1"]))
        else:  # öbek eşlenmediyse kelimeleri tek tek dene
            sutunlar += [(a, w["x0"], w["x1"]) for w in o if (a := _alan(w["text"]))]
    alanlar = {a for a, *_ in sutunlar}
    if len(sutunlar) < 3 or "ad" not in alanlar or not ({"tut", "fiy", "netfiy"} & alanlar):
        return None
    return sutunlar


def _sayfa_sonu_satiri(kelimeler: list[dict], alt: float, konum) -> dict | None:
    """Sayfa sonunda alt çizgisi çizilmemiş kalem satırı (sıra no, kod, ad bu sayfada; miktar ve tutarlar sonraki
    sayfadaki tablonun ilk satırında). Tablonun hemen altında sıra numarasıyla başlayan satır aranır."""
    satirlar = _satirlar([w for w in kelimeler if w["top"] >= alt - 1])
    if not satirlar or satirlar[0][0]["top"] - alt > 12:
        return None
    d: dict[str, list[str]] = {}
    for i, satir in enumerate(satirlar[:4]):
        parca: dict[str, list[str]] = {}
        for w in satir:
            parca.setdefault(_sutun_sec(konum, w["x0"], w["x1"]) or "", []).append(w["text"])
        if i == 0 and not re.fullmatch(r"\d{1,4}", " ".join(parca.get("sira", []))):
            return None
        if i and (set(parca) - {"ad", "kod"} or satir[0]["top"] - satirlar[i - 1][0]["top"] > 16):
            break
        for a, v in parca.items():
            if a:
                d[a] = [f"{d[a][0]}\n{' '.join(v)}" if a in d else " ".join(v)]
    return d if "ad" in d or "kod" in d else None


def _tablo_satirlari(veri: bytes, yazidan: bool = False) -> list[dict] | None:
    """Kalem tablosunun satırları (alan -> hücreler). Önce çizgili tablo; başlığı olmayan devam tablosu (sonraki
    sayfa) sütun konumlarıyla, satır çizgisi olmayan tablo kelime konumlarıyla okunur. Çizgili tablo yoksa
    başlık satırı yazıdan aranır."""
    try:
        import pdfplumber
    except ImportError:
        return None
    try:
        pdf = pdfplumber.open(io.BytesIO(veri))
    except Exception:  # noqa: BLE001
        return None
    kalemler, alanlar, konum, baslik_sayfasi, bekleyen = [], None, None, None, None
    try:
        for no, sayfa in enumerate(pdf.pages):
            kelimeler = None
            for sira, tablo in enumerate(sayfa.find_tables()):
                satirlar = _temiz(tablo.extract())
                hucreler = [[(c[0], c[2]) if c else None for c in r.cells] for r in tablo.rows]
                basla, sutun_konumu = 0, None
                yeni = next(((i, a) for i, x in enumerate(satirlar[:3]) if (a := _sutunlar(x))), None)
                if yeni:
                    basla, alanlar, baslik_sayfasi = yeni[0] + 1, yeni[1], no
                    konum = [(a.lstrip("+") if a else None, *(h or (0, 0))) for a, h in zip(alanlar, hucreler[yeni[0]])]
                elif alanlar is None or no == baslik_sayfasi or sira > 0:
                    continue  # başlıksız tablo ancak sonraki sayfanın başındaysa kalem tablosunun devamıdır
                elif len(satirlar[0]) != len(alanlar):  # devam tablosu, sütun sayısı farklı: konumla eşle
                    sutun_konumu = [_sutun_sec(konum, *h) if h else None for h in hucreler[0]]
                onceki, eklenen = None, 0
                for s in satirlar[basla:]:
                    d = _satir_alanlari(sutun_konumu or alanlar, s)
                    if not d:
                        continue
                    if bekleyen and not yeni and "ad" not in d and "sira" not in d and _sira_mi(d):
                        d, bekleyen = {**bekleyen, **d}, None  # sayfa sonunda bölünen satırın tutarları bu sayfada
                    if "ad" not in d and "sira" not in d:  # alt toplam satırları ("Mal Hizmet Toplam Tutarı")
                        if _sira_mi(d) or re.search(r"toplam|matrah|iskonto|kdv", sade(" ".join(c or "" for c in s))):
                            onceki = None
                        continue
                    if re.search(r"toplam tutar", sade(" ".join(c or "" for c in s))):  # tabloya karışmış alt toplam
                        continue
                    if re.match(r"(hesaplanan|odenecek|toplam|ara toplam|genel toplam|kdv matrah|vergiler dahil|"
                                r"(mal|malzeme|urun) ?/? ?hizmet toplam)", sade(_metin((d.get("ad") or [""])[0]))):
                        break  # tablonun altındaki toplamlar ("Hesaplanan KDV(%10)", "Ödenecek Tutar")
                    if re.fullmatch(r"(kdv|otv|oiv)( tutari| toplami)?", sade(_metin((d.get("ad") or [""])[0]))):
                        continue  # kalemin altına ayrı satırda yazılmış KDV tutarı (araç muayene faturası)
                    if not yeni and not (re.fullmatch(r"\d{1,4}", _metin((d.get("sira") or [""])[0]))
                                         or _sayi((d.get("tut") or [""])[-1]) is not None):
                        continue  # devam tablosunda sıra numarası ya da tutarı olmayan satır (banka bilgileri) kalem değil
                    if not _sira_mi(d):
                        if onceki is not None and "ad" in d:
                            onceki.setdefault("ad", []).extend(d["ad"])
                        continue
                    onceki = d
                    kalemler.append(d)
                    eklenen += 1
                kelimeler = kelimeler or sayfa.extract_words()
                bekleyen = _sayfa_sonu_satiri(kelimeler, tablo.bbox[3], konum) if eklenen else None
                if bekleyen and _sira_mi(bekleyen):  # satırın tamamı tablonun altında kalmış
                    kalemler.append(bekleyen)
                    bekleyen = None
                if yeni and not eklenen:  # satır çizgisi yok: başlığın altındaki yazı kelime konumlarıyla okunur
                    alt = tablo.rows[yeni[0]].bbox[3]
                    ic = [w for w in kelimeler if alt - 1 <= w["top"] and w["bottom"] <= tablo.bbox[3] + 1]
                    kalemler += _kelimelerle_satirlar(_satirlar(ic), konum)
        if not kalemler and alanlar is None and yazidan:  # hiç çizgili kalem tablosu yok: başlık satırını yazıda ara
            for sayfa in pdf.pages:
                satirlar = _satirlar(sayfa.extract_words())
                for i, satir in enumerate(satirlar):
                    sutunlar = _baslik_sutunlari(satir)
                    if sutunlar:
                        kalemler += _kelimelerle_satirlar(satirlar[i + 1:], sutunlar)
                        break
    finally:
        pdf.close()
    return kalemler or None


_ALT_BILGI = re.compile(r"^yalniz\b|\b(?:ara toplam|genel toplam|kdv matrahi|odenecek tutar|vergiler dahil|toplam tutar)\b")


def tablodan_kalemler(veri: bytes, hedefler: list[float | None], oran: float | None = None,
                      genel: float | None = None, kdv: float | None = None, yazidan: bool = False) -> list[dict] | None:
    """yazidan=True: çizgili tablo yoksa başlık satırı yazıda aranır (öteki okuma yöntemleri sonuç vermediğinde)."""
    from .kural import kalemleri_uzlastir
    satirlar = _tablo_satirlari(veri, yazidan)
    if not satirlar:
        return None
    # Tablonun içine düşmüş alt bilgi satırı ("Yalnız : #sekizbin...", "Ara Toplam / KDV Matrahı") kalem değildir
    satirlar = [d for d in satirlar if _kalem(d, oran) or not _ALT_BILGI.search(sade(" ".join(
        str(x) for v in d.values() for x in (v if isinstance(v, list) else [v]) if x)))]
    sonuc = [k for k in (_kalem(d, oran) for d in satirlar) if k]
    if not sonuc or len(sonuc) != len(satirlar):
        return None
    return kalemleri_uzlastir(sonuc, hedefler, genel, kdv)


def tablo_dokumu(veri: bytes) -> list[dict]:
    """Hata raporu için: PDF'te bulunan tablolar, başlık satırının hangi alanlara eşlendiği ve hücreler."""
    try:
        import pdfplumber
        pdf = pdfplumber.open(io.BytesIO(veri))
    except Exception:  # noqa: BLE001
        return []
    sonuc = []
    try:
        for no, sayfa in enumerate(pdf.pages[:10], 1):
            for tablo in sayfa.find_tables():
                satirlar = _temiz(tablo.extract())
                eslesme = next(((i, a) for i, s in enumerate(satirlar[:3]) if (a := _sutunlar(s))), None)
                sonuc.append({"sayfa": no, "konum": [round(x) for x in tablo.bbox],
                              "baslik_satiri": eslesme[0] if eslesme else None,
                              "basliklar": satirlar[eslesme[0]] if eslesme else (satirlar[0] if satirlar else []),
                              "alanlar": eslesme[1] if eslesme else [_alan(h) for h in (satirlar[0] if satirlar else [])],
                              "kalem_tablosu": bool(eslesme), "satirlar": satirlar})
    finally:
        pdf.close()
    return sonuc


def kelimeler(veri: bytes) -> list[dict]:
    """Hata raporu için: her kelime ve sayfadaki konumu (sütun düzenini görmek için)."""
    try:
        import pdfplumber
        pdf = pdfplumber.open(io.BytesIO(veri))
    except Exception:  # noqa: BLE001
        return []
    try:
        return [{"s": no, "x": round(w["x0"], 1), "y": round(w["top"], 1), "x1": round(w["x1"], 1), "m": w["text"]}
                for no, sayfa in enumerate(pdf.pages[:10], 1) for w in sayfa.extract_words()]
    finally:
        pdf.close()
