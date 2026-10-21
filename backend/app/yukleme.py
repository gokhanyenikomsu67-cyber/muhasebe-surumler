"""Yüklenen dosyalar için tek boyut sınırı: dosya parça parça okunur, sınır aşılınca okuma durur (büyük dosya belleği
doldurmaz). Toplu fatura ZIP'i daha büyük olabilir."""
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
    return b"".join(parcalar)
