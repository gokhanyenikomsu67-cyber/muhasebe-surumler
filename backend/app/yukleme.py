"""Yüklenen dosyalar için tek boyut sınırı: dosya parça parça okunur, sınır aşılınca okuma durur (büyük dosya belleği
doldurmaz). Toplu fatura ZIP'i daha büyük olabilir."""
import io
import re
from datetime import datetime
from html.parser import HTMLParser

from fastapi import HTTPException, UploadFile

MB = 1024 * 1024
EN_BUYUK_DOSYA = 25 * MB
EN_BUYUK_ZIP = 100 * MB
_PARCA = MB


class DosyaBuyuk(HTTPException):
    def __init__(self, ad: str, sinir: int):
        super().__init__(413, f"{ad or 'Dosya'} çok büyük: en çok {sinir // MB} MB olabilir. Dosyayı bölüp parça parça yükleyin.")


def sinir(ad: str | None) -> int:
    return EN_BUYUK_ZIP if (ad or "").lower().endswith(".zip") else EN_BUYUK_DOSYA


def dosyayi_oku(dosya: UploadFile, en_cok: int | None = None) -> bytes:
    """Yüklenen dosyanın içeriği; sınırı aşarsa DosyaBuyuk (413, kısa Türkçe mesaj)."""
    en_cok = en_cok or sinir(dosya.filename)
    dosya.file.seek(0)
    parcalar, toplam = [], 0
    while parca := dosya.file.read(_PARCA):
        toplam += len(parca)
        if toplam > en_cok:
            raise DosyaBuyuk(dosya.filename, en_cok)
        parcalar.append(parca)
    icerik = b"".join(parcalar)
    if (dosya.filename or "").lower().endswith(".xls"):
        # Eski Excel (.xls) ve bankaların .xls adıyla verdiği HTML/XML tablolar .xlsx'e çevrilir: bütün Excel
        # okuyucuları (ekstre, fatura, çek, cari listesi) aynı yoldan okur.
        icerik = xls_to_xlsx(icerik)
        dosya.filename = dosya.filename[:-4] + ".xlsx"
        dosya.file = io.BytesIO(icerik)
    return icerik


class _HtmlTablo(HTMLParser):
    def __init__(self):
        super().__init__()
        self.satirlar: list[list[str]] = []
        self._hucre: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.satirlar.append([])
        elif tag in ("td", "th"):
            self._hucre = []
        elif tag == "br" and self._hucre is not None:
            self._hucre.append("\n")

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._hucre is not None:
            if not self.satirlar:
                self.satirlar.append([])
            self.satirlar[-1].append(" ".join("".join(self._hucre).split()))
            self._hucre = None

    def handle_data(self, data):
        if self._hucre is not None:
            self._hucre.append(data)


def _metin_tablosu(icerik: bytes) -> list[list]:
    """.xls adlı HTML ya da XML (Excel 2003) tablo."""
    for kod in ("utf-8", "cp1254", "iso-8859-9"):
        try:
            metin = icerik.decode(kod)
            break
        except UnicodeDecodeError:
            continue
    if "urn:schemas-microsoft-com:office:spreadsheet" in metin and "<Row" in metin:
        satirlar = []
        for satir in re.findall(r"<(?:ss:)?Row\b.*?</(?:ss:)?Row>", metin, re.S):
            hucreler = re.findall(r"<(?:ss:)?Data[^>]*>(.*?)</(?:ss:)?Data>", satir, re.S)
            satirlar.append([re.sub(r"<[^>]+>", "", h) for h in hucreler])
        return satirlar
    ayristirici = _HtmlTablo()
    ayristirici.feed(metin)
    return [s for s in ayristirici.satirlar if any(s)]


def xls_to_xlsx(icerik: bytes) -> bytes:
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    if icerik[:8] == bytes.fromhex("D0CF11E0A1B11AE1"):
        try:
            import xlrd
        except ImportError as e:
            raise HTTPException(422, "Eski .xls dosyasını okumak için program güncellemesi gerekiyor (Araçlar > Güncellemeleri Denetle).") from e
        try:
            kitap = xlrd.open_workbook(file_contents=icerik)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(422, "Bu .xls dosyası açılamadı; bozuk ya da şifreli olabilir.") from e
        sayfa = kitap.sheet_by_index(0)
        ws.title = (sayfa.name or "Sayfa1")[:31].replace("/", "-")
        for i in range(sayfa.nrows):
            satir = []
            for h in sayfa.row(i):
                if h.ctype == xlrd.XL_CELL_DATE:
                    try:
                        satir.append(datetime(*xlrd.xldate_as_tuple(h.value, kitap.datemode)))
                        continue
                    except Exception:  # noqa: BLE001
                        pass
                satir.append(None if h.ctype in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK) else h.value)
            ws.append(satir)
    elif icerik.lstrip(b"\xef\xbb\xbf \r\n\t")[:1] == b"<":
        for satir in _metin_tablosu(icerik):
            ws.append(satir)
    elif icerik[:4] == b"PK\x03\x04":
        return icerik  # adı .xls ama aslında .xlsx
    else:
        raise HTTPException(422, "Bu .xls dosyası tanınmadı. Excel'de açıp .xlsx olarak kaydedip yükleyin.")
    tampon = io.BytesIO()
    wb.save(tampon)
    return tampon.getvalue()
