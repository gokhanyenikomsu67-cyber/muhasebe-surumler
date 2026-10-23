"""Program sürümü: paket (git archive) çıkarılırken tarih ve kısa kayıt kodu yazılır; ekranın altında görünür."""
_HAM = "2026-10-23 db40069"
SURUM = "geliştirme" if _HAM.startswith("$") else _HAM


def ek_paketler() -> dict:
    """İsteğe bağlı paketlerin kurulu olup olmadığı: karekod (zxing-cpp) ve el yazısı (RapidOCR)."""
    from . import el_yazisi
    try:
        import zxingcpp  # noqa: F401
        karekod = True
    except Exception:  # noqa: BLE001
        karekod = False
    return {"karekod": karekod, "el_yazisi": el_yazisi.var_mi()}
