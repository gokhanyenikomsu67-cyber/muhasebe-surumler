"""PDF faturanın veritabanına dokunmayan okuması: toplu yüklemede ayrı işlemde (islemci) çalışır."""
import re
from types import SimpleNamespace

from . import karekod, kural, ocr


def karsi_tarafi_karekoddan(okunan: dict, icerik: bytes, sirket, yon: str) -> dict:
    """PDF yazısında karşı firmanın VKN'si bulunamadıysa ya da bizimki çıktıysa VKN faturanın GİB karekodundan alınır;
    kendi VKN'miz hiçbir yoldan cari olmaz."""
    taraf = "satici" if yon == "gelen" else "alici"
    vkn = re.sub(r"\D", "", str((okunan.get(taraf) or {}).get("vkn") or ""))
    kendi = re.sub(r"\D", "", sirket.vkn or "")
    if vkn and kendi and vkn != kendi:
        return okunan
    k = karekod.oku(icerik, True) if karekod.var_mi() else None
    if k and not kendi:
        # Firma bilgisinde VKN'miz yok: karekodda alış faturasının alıcısı, satış faturasının satıcısı biziz
        kendi = re.sub(r"\D", "", str(k.get("avkntckn" if yon == "gelen" else "vkntckn") or ""))
        if len(kendi) in (10, 11):
            sirket.vkn = kendi
        if vkn and vkn != kendi:
            return okunan
    if k and yon == "gelen":
        okunan = karekod.uygula(okunan, k, sirket.vkn, yon)
    if re.sub(r"\D", "", str((okunan.get(taraf) or {}).get("vkn") or "")) == kendi:
        okunan = {**okunan, taraf: {**okunan[taraf], "vkn": None}}
    return okunan


def pdf_oku(icerik: bytes, santiye_adlari: list[str], unvan: str | None, vkn: str | None, yon: str) -> dict:
    """{"yon", "okunan"} ya da okunamadıysa {"yon", "hata"} (resimden okumaya geçilir); "vkn": karekoddan öğrenilen VKN'miz."""
    sirket = SimpleNamespace(unvan=unvan, vkn=vkn)
    # Satış faturası alış ekranından (ya da tersi) yüklendiyse belgedeki taraflar esas alınır
    # GİB karekodundaki taraflar kesindir (yazıda satıcı yerine bizim VKN'miz okunabilir: Turkcell, Vodafone)
    yon = kural.pdf_yonu(icerik, vkn, lambda: karekod.yonu(karekod.oku(icerik, True), vkn)) or yon
    try:
        okunan = kural.pdf_fatura_oku(icerik, santiye_adlari, unvan, vkn, yon)
        if not (okunan["genel_toplam"] or okunan["fatura_no"]):
            raise kural.KuralHatasi("PDF'te fatura bilgisi bulunamadı. XML dosyasını yükleyin ya da elle girin.")
        # Kalemler PDF yazısından okunamadıysa ya da tutmadıysa sayfa resminden de okunur
        okunan = ocr.pdf_kalemlerini_tamamla(okunan, icerik, santiye_adlari, unvan, vkn, yon)
        okunan = karsi_tarafi_karekoddan(okunan, icerik, sirket, yon)
    except kural.KuralHatasi as e:
        return {"yon": yon, "hata": str(e), "vkn": sirket.vkn}
    return {"yon": yon, "okunan": okunan, "vkn": sirket.vkn}
