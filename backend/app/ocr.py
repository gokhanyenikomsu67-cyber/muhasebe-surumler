"""Resimden fatura okuma: taranmış PDF ve fotoğraflar yapay zekasız, bilgisayarda çalışan Tesseract ile metne çevrilir.

Görüntü önce iyileştirilir (EXIF yönü, gri ton, kontrast, büyütme, eğiklik düzeltme), yan ya da ters çekilmişse
dört yönden en güvenilir okunan seçilir. Çıkan metin PDF metniyle aynı kurallarla çözülür (kural.pdf_fatura_oku) ve
aynı öz-denetimden geçer. Tesseract'ın kelime güveni düşük olan tutarlar "belirsiz" olarak işaretlenir.
Tesseract programı Windows'ta baslat.bat ile kurulur; Türkçe dil verisi programla gelir (ocr_veri/).
"""
import io
import os
import re
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

from . import kural

DIL_KLASORU = Path(__file__).with_name("ocr_veri")
RESIM_UZANTILARI = (".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".tif", ".tiff", ".bmp")
EN_FAZLA_SAYFA = 5
DUSUK_GUVEN = 70  # bu güvenin altındaki tutarlar belirsiz sayılır


KURULU_DEGIL = ("Resimden okuma programı (Tesseract) bu bilgisayarda kurulu değil. Programı baslat.bat ile yeniden açın; "
                "ilk açılışta kurulur. Ya da faturanın XML/PDF dosyasını yükleyin.")


def tesseract() -> str | None:
    aday = os.environ.get("MUHASEBE_TESSERACT") or shutil.which("tesseract")
    if aday:
        return aday
    for kok in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"), os.environ.get("LOCALAPPDATA")):
        if kok:
            for alt in ("Tesseract-OCR", r"Programs\Tesseract-OCR"):
                yol = Path(kok) / alt / "tesseract.exe"
                if yol.exists():
                    return str(yol)
    return None


def var_mi() -> bool:
    return tesseract() is not None


def resim_mi(ad: str, mime: str) -> bool:
    return ad.lower().endswith(RESIM_UZANTILARI) or mime.startswith("image/")


# PDFium aynı anda birden çok iş parçacığından kullanılamaz: toplu yüklemede eşzamanlı okumalar programı
# çökertiyordu (segmentation fault). PDF'i resme çevirme tek tek yapılır; OCR yine paralel sürer.
_PDFIUM_KILIDI = threading.Lock()


def _goruntuler(veri: bytes, pdf: bool):
    from PIL import Image, ImageOps
    if pdf:
        import pypdfium2 as pdfium
        with _PDFIUM_KILIDI:
            try:
                belge = pdfium.PdfDocument(veri)
            except pdfium.PdfiumError as e:
                raise kural.KuralHatasi("PDF açılamadı; dosya bozuk ya da boş olabilir.") from e
            try:
                return [belge[i].render(scale=300 / 72).to_pil().copy() for i in range(min(len(belge), EN_FAZLA_SAYFA))]
            finally:
                belge.close()
    try:
        import pillow_heif  # iPhone fotoğrafları (HEIC)
        pillow_heif.register_heif_opener()
    except ImportError:
        pass
    try:
        img = Image.open(io.BytesIO(veri))
        img.load()
    except Exception as e:  # noqa: BLE001
        raise kural.KuralHatasi("Resim açılamadı (desteklenen: JPG, PNG, WEBP, HEIC, TIFF).") from e
    return [ImageOps.exif_transpose(img)]


def _egiklik(gri) -> float:
    """Satırlar yatay olduğunda satır toplamlarının değişkenliği en yüksektir; ±6 derece taranır."""
    from PIL import ImageOps
    kucuk = gri.copy()
    kucuk.thumbnail((800, 800))
    siyah = ImageOps.invert(kucuk).point(lambda p: 255 if p > 110 else 0)

    def puan(aci):
        don = siyah.rotate(aci, expand=False, fillcolor=0)
        satirlar = list(don.resize((1, don.height)).tobytes())
        ort = sum(satirlar) / len(satirlar)
        return sum((x - ort) ** 2 for x in satirlar)
    en_iyi = max((a / 2 for a in range(-12, 13)), key=puan)
    # İnce ayar
    return max((en_iyi + a / 10 for a in range(-4, 5)), key=puan)


def _cizgileri_sil(gri):
    """Tablo çizgilerini siler: çizgiye yapışık yazıyı Tesseract okuyamaz. Yatayda/dikeyde uzun kesintisiz koyu
    şerit, kutu ortalamasında da koyu kalır; yazı ise aralıklı olduğundan açılır."""
    from PIL import Image, ImageChops
    w, h = gri.size
    boy = max(w, h) // 50
    maske = None
    ikili = gri.point(lambda p: 0 if p < 170 else 255)
    for kucuk in ((max(w // boy, 1), h), (w, max(h // boy, 1))):
        # Kutunun %90'ından fazlası koyuysa çizgidir; yazıda harf araları açık kalır
        m = ikili.resize(kucuk, Image.BOX).point(lambda p: 255 if p < 26 else 0).resize((w, h), Image.NEAREST)
        maske = m if maske is None else ImageChops.lighter(maske, m)
    # Çizgi kenarındaki gri pikseller de gitsin
    from PIL import ImageFilter
    maske = maske.filter(ImageFilter.MaxFilter(3))
    return ImageChops.lighter(gri, maske)


def iyilestir(img):
    from PIL import ImageFilter, ImageOps
    gri = ImageOps.grayscale(img.convert("RGB"))
    # Fotoğrafta yazı küçükse büyüt (Tesseract ~30 piksel yükseklikte harflerle iyi çalışır)
    if gri.width < 2000:
        oran = 2400 / gri.width
        gri = gri.resize((int(gri.width * oran), int(gri.height * oran)))
    elif gri.width > 4000:
        gri.thumbnail((4000, 4000))
    gri = ImageOps.autocontrast(gri, cutoff=1)
    # Gölge/ışık farkını azalt: arka planı büyük bulanıklıkla tahmin edip böl
    arka = gri.filter(ImageFilter.GaussianBlur(radius=max(gri.width // 60, 15)))
    from PIL import ImageChops
    gri = ImageChops.invert(ImageChops.subtract(arka, gri, scale=1, offset=0))
    gri = ImageOps.autocontrast(gri, cutoff=1)
    aci = _egiklik(gri)
    if abs(aci) >= 0.2:
        gri = gri.rotate(aci, expand=True, fillcolor=255, resample=3)
    gri = _cizgileri_sil(gri)
    return gri.filter(ImageFilter.SHARPEN)


def _tesseract(img, psm: int = 4) -> list[dict]:
    """Kelimeler: metin, güven, satır anahtarı, x konumu."""
    exe = tesseract()
    if not exe:
        raise kural.KuralHatasi(KURULU_DEGIL)
    with tempfile.TemporaryDirectory() as d:
        yol = Path(d) / "sayfa.png"
        img.save(yol)
        try:
            sonuc = subprocess.run(
                [exe, str(yol), "stdout", "--tessdata-dir", str(DIL_KLASORU), "-l", "tur+eng", "--psm", str(psm),
                 "-c", "preserve_interword_spaces=1", "-c", "tessedit_create_tsv=1"],
                capture_output=True, timeout=300, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                env={**os.environ, "OMP_THREAD_LIMIT": "1"})  # toplu yüklemede dosyalar zaten paralel okunuyor
        except (OSError, subprocess.TimeoutExpired) as e:
            raise kural.KuralHatasi("Resim okunamadı (metin tanıma çalışmadı).") from e
    kelimeler = []
    for satir in sonuc.stdout.decode("utf-8", "replace").splitlines()[1:]:
        p = satir.split("\t")
        if len(p) == 12 and p[11].strip() and p[10] != "-1":
            kelimeler.append({"m": p[11].strip(), "g": float(p[10]), "s": (int(p[2]), int(p[3]), int(p[4])),
                              "x": int(p[6]), "y": int(p[7])})
    return kelimeler


def _gurultu_mu(k: dict) -> bool:
    """Logo, kaşe ve çizgiden çıkan anlamsız parçalar düşük güvenle okunur. Rakamlı parça daha geç atılır:
    güveni orta olan tutar metinde kalır ve "belirsiz" diye işaretlenir."""
    if re.search(r"\d", k["m"]):
        return k["g"] < 30 and len(k["m"]) <= 2
    if re.fullmatch(rf"(?:TL|TRY|EUR|USD|%|{_BIRIM})[.,]?", k["m"], re.IGNORECASE):
        return False  # tutar sütununun parçası
    return k["g"] < 50


def _metin(kelimeler: list[dict]) -> str:
    satirlar: dict[tuple, list] = {}
    for k in kelimeler:
        if _gurultu_mu(k):
            continue
        satirlar.setdefault(k["s"], []).append(k)
    sirali = sorted(satirlar.values(), key=lambda s: (min(k["y"] for k in s), min(k["x"] for k in s)))
    return "\n".join(" ".join(k["m"] for k in sorted(s, key=lambda k: k["x"])) for s in sirali)


def _guven(kelimeler: list[dict]) -> float:
    anlamli = [k for k in kelimeler if len(k["m"]) > 1]
    return sum(k["g"] for k in anlamli) / len(anlamli) if anlamli else 0


def _yan_mi(img) -> bool:
    """Yazı satırları yatayken satır toplamları sütun toplamlarından çok daha dalgalıdır; tersi ise sayfa yan çekilmiştir."""
    from PIL import ImageOps
    k = ImageOps.grayscale(img.convert("RGB"))
    k.thumbnail((800, 800))
    k = ImageOps.invert(ImageOps.autocontrast(k, cutoff=1)).point(lambda p: 255 if p > 110 else 0)

    def dalga(v):
        ort = sum(v) / len(v)
        return sum((x - ort) ** 2 for x in v) / len(v)
    return dalga(k.resize((k.width, 1)).tobytes()) > dalga(k.resize((1, k.height)).tobytes())


def sayfa_oku(img) -> list[dict]:
    """İyileştirilmiş sayfa. Yan çekilmiş fotoğraf satır yönünden anlaşılır; ters/yan olup olmadığı okuma güveninden:
    önce olası iki yön, ikisi de kötüyse kalan iki yön denenir."""
    olasi = (90, 270) if _yan_mi(img) else (0, 180)
    en_iyi, puan = None, lambda k: _guven(k) * min(len(k), 150)
    for i, aci in enumerate(olasi + tuple(a for a in (0, 90, 180, 270) if a not in olasi)):
        kelimeler = _tesseract(iyilestir(img.rotate(aci, expand=True) if aci else img))
        if en_iyi is None or puan(kelimeler) > puan(en_iyi):
            en_iyi = kelimeler
        if _guven(kelimeler) >= 75 and len(kelimeler) >= 30 or i == 1 and _guven(en_iyi) >= 55:
            break
    return en_iyi


def metne_cevir(veri: bytes, pdf: bool) -> tuple[str, list[str], float]:
    """(metin, belirsiz tutarlar, ortalama güven)."""
    tum, belirsiz, guven = [], [], 0.0
    for img in _goruntuler(veri, pdf):
        kelimeler = sayfa_oku(img)
        tum.append(_metin(kelimeler))
        belirsiz += [k["m"] for k in kelimeler if k["g"] < DUSUK_GUVEN and re.search(r"\d[.,]\d{2}\b", k["m"])]
        guven = min(guven, _guven(kelimeler)) if tum[:-1] else _guven(kelimeler)
    metin = duzelt("\n".join(tum))
    return metin, list(dict.fromkeys(belirsiz)), guven


_ORANLAR = {"0", "1", "8", "10", "18", "20"}
_BIRIM = r"(?:Adet|Ad|Kg|Kgm|Lt|Litre|Mt|Metre|M2|M3|Ton|Set|Paket|Kutu|Koli|Çift|Cift|Saat|Gün|Ay|Top|Rulo|Takım)"


def _yuzde(x) -> str:
    """İki tutar arasındaki oran sütunu: başındaki yanlış okunmuş yüzde işareti atılır; kalan bilinen bir KDV oranı olmalı."""
    t = x.group(1)
    isaretli = t[0] in "%“”\"'°*"
    govde = t[1:] if isaretli else t
    for on in ("", "96", "9", "6"):
        if govde.startswith(on) and govde[len(on):] in _ORANLAR and (on or isaretli or len(t) <= 2):
            return "%" + govde[len(on):]
    return t


def duzelt(metin: str) -> str:
    """Metin tanımanın faturalarda sık yaptığı yazım kaymalarını düzeltir; yalnız biçim, tutar uydurulmaz."""
    m = metin.replace("|", " ").replace("¦", " ")
    m = re.sub(r"(?<!\S)[(\[{][oO0](?!\S)", "", m)                               # renkli hücre kenarı: "(o"
    m = re.sub(r"\bK\.?\s?D\.?\s?V\b\.?", "KDV", m, flags=re.IGNORECASE)
    m = re.sub(r"(\d)(TL|TRY|EUR|USD)\b", r"\1 \2", m)                      # 70,00TL
    m = re.sub(rf"(\d)({_BIRIM})[iıl1]?(?=\s|$)", r"\1 \2", m, flags=re.IGNORECASE)  # 1Adet, 17 Adeti
    m = re.sub(rf"(?<=\s)({_BIRIM})[iıl1](?=\s)", r"\1", m, flags=re.IGNORECASE)
    # Yüzde işareti tırnak/derece/6/X okunur: “10, (620), (X10) -> %10, (%20), (%10)
    m = re.sub(r"(?<!\S)[“”\"'«»°*](\d{1,2})(?!\S)", lambda x: "%" + x.group(1) if x.group(1) in _ORANLAR else x.group(0), m)
    m = re.sub(r"\(\s*[%6X8x9]\s?(\d{1,2})\s*\)", lambda x: "(%" + x.group(1) + ")" if x.group(1) in _ORANLAR else x.group(0), m)
    m = re.sub(r"%\s+(\d)", r"%\1", m)
    m = re.sub(r"\b[UÜ]r[iıüu]{1,2}n\b", "Ürün", m)                                  # "Uriin / Hizmet"
    # Etiketle tutar arasına düşen çizgi/kenar parçaları: "Tutar) 4.000,00", "KDV (%10): o 1.155,00", "Tutarı| o 30.000"
    m = re.sub(r"(?<=[A-Za-zÇĞİÖŞÜçğıöşü])[)\]},;](?=\s+-?\d)", "", m)
    m = re.sub(r"\)\)", ")", m)
    m = re.sub(r"(?<!\S)[oOe©°_—=](?=\s+-?\d)", "", m)
    # Fatura no önüne düşen kenar parçası: "Fatura No: «A İAVA2026000285213"
    m = re.sub(r"(Fatura\s*No\s*:?)[^\n]{0,12}?((?=[A-Z0-9]{0,2}[A-Z])[A-Z0-9]{3}20\d{11})\b", r"\1 \2", m, flags=re.IGNORECASE)
    # Kalem satırında iki tutar arasında yalnız kalmış oran: "500,00 TL 10 50,00 TL" -> %10
    # ya da yüzde işareti "96", "9", "6", tırnak okunmuş: "2.500,00 TL 9620 5.000,00 TL" -> %20
    m = re.sub(r"(?<=TL )([“”\"'°*%]?\d{1,4})(?= \d[\d.,]*,\d{2} ?TL)", _yuzde, m)
    # KDV satırında yüzde işareti rakam okunmuş: "KDV Matrahı (620)", "(2010)" -> (%20), (%10)
    def _oran(x):
        r = x.group(2)
        ek = next((r[i:] for i in range(len(r)) if r[i:] in _ORANLAR), None)
        return f"{x.group(1)}(%{ek})" if ek else x.group(0)
    m = re.sub(r"(KDV[^\n(]{0,30})\((\d{1,4})\)", _oran, m, flags=re.IGNORECASE)
    m = re.sub(r"(\d{1,3}(?:\.\d{3})+)\s?,\s?(\d{2})\b", r"\1,\2", m)            # 24.097, 19
    # Satır sonuna yapışan logo/çizgi kırıntısı: "SAN ve TİC LTD ŞTİ 5", "e-Fatura >"
    m = re.sub(r"(?<=[A-Za-zÇĞİÖŞÜçğıöşü]{2})(?: [^\w\s]{1,2}| \d)+[ \t]*$", "", m, flags=re.MULTILINE)
    m = "\n".join(x for x in m.splitlines() if len(re.sub(r"\W", "", x)) > 2)       # kenar/çizgi kırıntısı satırlar
    return re.sub(r"[ \t]{2,}", " ", m)


_SIRKET_TURU = re.compile(r"^(?:ŞTİ|STİ|ŞTI|STI|A\.?Ş|A\.?S|ŞİRKETİ|SİRKETİ|ŞIRKETI|SIRKETI|LİMİTED|LIMITED|LTD|ANONİM|ANONIM|"
                          r"KOOPERATİFİ|KOOPERATIFI|TİC\.?LTD\.?ŞTİ|TİC\.LTD\.ŞTİ|TEKS\.SAN\.TİC\.LTD\.ŞTİ)\.?$", re.IGNORECASE)


def unvan_temizle(unvan: str | None) -> str | None:
    """Resimden okunan ünvanın yanındaki logo/çizgi parçalarını atar: harfsiz parçalar ve şirket türünden sonrası."""
    if not unvan:
        return unvan
    parcalar = [p for p in unvan.split() if re.search(r"[A-Za-zÇĞİÖŞÜçğıöşü]{2}|^[&-]$", p) or re.fullmatch(r"\d+", p)]
    son = max((i for i, p in enumerate(parcalar) if _SIRKET_TURU.match(p) or _SIRKET_TURU.match(p.split(".")[-1] + ".")),
              default=None)
    if son is not None and son >= 1:
        parcalar = parcalar[:son + 1]
    temiz = " ".join(parcalar).strip(" -—=.,;:")
    return temiz or None


def _onemli_belirsizler(okunan: dict, belirsiz: list[str]) -> list[str]:
    """Güveni düşük okunan tutarlardan faturada kullanılanlar (kalem tutarı, KDV, toplamlar)."""
    kullanilan = {okunan.get(a) for a in ("ara_toplam", "kdv_toplam", "genel_toplam", "tevkifat_toplam")}
    for k in okunan.get("kalemler", []):
        kullanilan |= {k.get("tutar"), k.get("birim_fiyat"), k.get("kdv_tutari")}
    kullanilan = {round(float(x), 2) for x in kullanilan if x}
    sonuc = []
    for b in belirsiz:
        m = re.search(r"\d[\d.,]*[.,]\d{2}", b)
        deger = kural.para_coz(m.group(0)) if m else None
        if deger is not None and round(deger, 2) in kullanilan:
            sonuc.append(m.group(0))
    return list(dict.fromkeys(sonuc))


def resimden_fatura_oku(veri: bytes, pdf: bool, santiyeler=None, sirket_unvan=None, sirket_vkn=None, yon="gelen") -> dict:
    """Metin tanıma; faturada GİB karekodu varsa numara, tarih, VKN ve toplamlar ondan kesin alınır. Yazı hiç
    okunamazsa (Tesseract yok ya da sayfada yazı yok) karekod tek başına başlık ve toplamları verir."""
    from . import karekod
    kod = karekod.oku(veri, pdf)
    try:
        if not var_mi():
            raise kural.KuralHatasi(KURULU_DEGIL)
        metin, belirsiz, guven = metne_cevir(veri, pdf)
        okunan = metinden_fatura_oku(metin, belirsiz, guven, santiyeler, sirket_unvan, sirket_vkn, yon)
    except kural.KuralHatasi:
        if kod:
            return karekod.fatura(kod, sirket_vkn, yon)
        raise
    return karekod.uygula(okunan, kod, sirket_vkn, yon) if kod else okunan


def metinden_fatura_oku(metin: str, belirsiz: list[str], guven: float, santiyeler=None, sirket_unvan=None, sirket_vkn=None,
                        yon="gelen") -> dict:
    if len(metin.strip()) < 30:
        raise kural.KuralHatasi("Resimde okunabilir yazı bulunamadı. Daha net ve düz bir fotoğraf çekin ya da "
                                "faturanın XML/PDF dosyasını yükleyin.")
    okunan = kural.pdf_fatura_oku(b"", santiyeler, sirket_unvan, sirket_vkn, yon, metin=metin)
    for taraf in ("satici", "alici"):
        if isinstance(okunan.get(taraf), dict):
            okunan[taraf]["unvan"] = unvan_temizle(okunan[taraf].get("unvan"))
    okunan["resimden"] = {"guven": round(guven), "belirsiz": _onemli_belirsizler(okunan, belirsiz), "metin": metin[:20000]}
    return okunan


def pdf_kalemlerini_tamamla(okunan: dict, veri: bytes, santiyeler=None, sirket_unvan=None, sirket_vkn=None,
                            yon="gelen") -> dict:
    """PDF yazısından kalemler okunamadı ya da toplamı tutmadıysa sayfa resim olarak da okunur.

    Başlık bilgileri ve toplamlar PDF yazısından gelir (resimden daha güvenilir); resimden okunan kalemler ancak
    bu toplamları ve KDV'yi tutuyorsa alınır. PDF yazısında toplam da yoksa resimden okunan fatura kendi içinde
    tutarlıysa olduğu gibi kullanılır. İkisi de olmazsa PDF okuması değişmeden kalır (kırmızı uyarıyla)."""
    if kural.kalemler_tutarli(okunan) or not var_mi():
        return okunan
    try:
        resim = resimden_fatura_oku(veri, True, santiyeler, sirket_unvan, sirket_vkn, yon)
    except kural.KuralHatasi:
        return okunan
    aday = {**okunan, "kalemler": resim.get("kalemler") or [], "kalemler_okunamadi": False,
            **{a: resim.get(a) for a in ("ara_toplam", "kdv_toplam", "genel_toplam") if okunan.get(a) is None}}
    if kural.kalemler_tutarli(aday):
        aday["resimden"] = {**resim["resimden"], "yalniz_kalemler": True}
        aday["notlar"] = " ".join(x for x in (okunan.get("notlar"), "Kalemler sayfanın resminden okundu.") if x)
        return aday
    if not (okunan.get("genel_toplam") or okunan.get("ara_toplam")) and kural.kalemler_tutarli(resim):
        return resim
    return okunan
