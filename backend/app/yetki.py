"""Kişi bazında bölüm yetkileri. Sahip her şeyi yapar; öteki kullanıcılara sahip her bölüm için ayrı ayrı
Görür / Girer / Düzenler / Siler yetkisi verir (Kullanici.yetkiler: {"fatura": ["gor", "ekle"], ...}).

Her istek (aktif_kullanici içinde) adresinden bölüme, yönteminden işleme çevrilip denetlenir; yeni bir uç eklenince
bölümü BOLUM_KURALLARI'na yazılmalıdır (test_yetki bütün uçların bir bölümü olduğunu denetler).
"""
import re

from fastapi import HTTPException

BOLUMLER = {
    "fatura": "Faturalar",
    "malzeme": "Malzemeler",
    "cari": "Cariler ve mutabakat",
    "santiye": "Şantiye, depo ve taşeron",
    "cek": "Çek / Senet",
    "banka": "Banka / Kasa / Kredi kartı",
    "rapor": "Mali raporlar ve Genel Durum",
    "araclar": "Araçlar (yedek, değişiklik geçmişi)",
}
DUZEYLER = {"gor": "Görür", "ekle": "Girer (yeni kayıt, belge okuma, onay)", "duzenle": "Düzenler", "sil": "Siler"}

# Herkese açık (giriş yapmış her kullanıcı): ekranların ortak listeleri ve bilgileri
_ACIK = [
    ("GET", r"ben|ara|sistem-durumu|hareket-turleri|sirket|kullanicilar"),
    ("GET", r"(cariler|santiyeler|depolar|banka-hesaplari)"),
    ("GET", r"cariler/(benzer|kontrol)|faturalar/(sonraki-no|tcmb-kuru)"),
]
# Sahip denetimi uçta yapılır (kullanıcı ekleme, firma bilgisi, sistem işlemleri)
_SAHIP_UCTA = [(None, r"kullanicilar(/.*)?|sirket|sistem/.*|yedekler/(geri-yukle|sil)")]

BOLUM_KURALLARI = [
    ("fatura", r"faturalar(/.*)?|reddedilen-faturalar(/.*)?|excel/(faturalar|fatura-).*|yazdir/fatura/.*"),
    ("malzeme", r"malzemeler(/.*)?|(raporlar|excel)/malzeme"),
    ("cari", r"cariler(/.*)?|excel/(cariler|cari-).*|raporlar/cari-.*|yazdir/(cari-ekstre|mutabakat).*|mutabakat"),
    ("santiye", r"santiyeler(/.*)?|depolar(/.*)?|taseron.*|(raporlar|excel)/(santiye-|depo-|taseron).*"),
    ("cek", r"cekler(/.*)?|excel/(cekler|cek-).*|raporlar/cekler|yazdir/cek-.*"),
    ("banka", r"banka-hesaplari(/.*)?|hareketler(/.*)?|kasa|ekstre-yukle|kredi-karti-ekstresi|duzenli-odemeler(/.*)?|"
              r"(raporlar|excel)/(virmanlar|hareketler|nakit-akisi)"),
    ("rapor", r"(raporlar|excel)/(kdv|tevkifat|stopaj|ba-bs|gelir-gider|yaslandirma|ozet)"),
    ("araclar", r"yedekler(/.*)?|gecmis"),
]
_SIL = {"sil", "toplu-sil", "okunamayanlar"}
_DUZENLE = {"iptal", "iptal-geri", "iptal-et", "toplu-guncelle", "toplu-islem", "islem", "karsi-hesap", "esle",
            "birlestir", "ad-cikar", "odendi"}
# Kayıt açmak için gereken yardımcı kayıtlar: fatura/çek/banka girebilen, oradan yeni cari/şantiye de açabilir
_YARDIMCI = {"cari", "santiye"}
_GIRIS_BOLUMLERI = {"fatura", "cek", "banka", "santiye", "cari"}


def _yol(path: str) -> str:
    return path.removeprefix("/api/").strip("/")


def bolum(path: str) -> str | None:
    y = _yol(path)
    return next((b for b, d in BOLUM_KURALLARI if re.fullmatch(d, y)), None)


def duzey(method: str, path: str) -> str:
    if method in ("GET", "HEAD"):
        return "gor"
    if method == "DELETE":
        return "sil"
    if method in ("PUT", "PATCH"):
        return "duzenle"
    son = _yol(path).rsplit("/", 1)[-1]
    if son in _SIL:
        return "sil"
    if son in _DUZENLE:
        return "duzenle"
    return "ekle"


def acik_mi(method: str, path: str) -> bool:
    y = _yol(path)
    return any((m is None or m == method) and re.fullmatch(d, y) for m, d in _ACIK + _SAHIP_UCTA)


def varsayilan(rol: str) -> dict[str, list[str]]:
    """Yetkisi ayrıca işaretlenmemiş eski kullanıcılar: muhasebeci her bölümde her şey, izleyici yalnız görür."""
    if rol == "izleyici":
        return {b: ["gor"] for b in BOLUMLER}
    return {b: list(DUZEYLER) for b in BOLUMLER}


def yetkileri(k) -> dict[str, list[str]]:
    if k.rol == "sahip":
        return {b: list(DUZEYLER) for b in BOLUMLER}
    if k.yetkiler is not None:
        return {b: [d for d in DUZEYLER if d in (k.yetkiler.get(b) or [])] for b in BOLUMLER}
    return varsayilan(k.rol)


def temizle(veri: dict) -> dict[str, list[str]]:
    """Ekrandan gelen yetkiler: bilinmeyen bölüm/düzey atılır; giren, düzenleyen ya da silen görür de."""
    sonuc = {}
    for b in BOLUMLER:
        d = [x for x in DUZEYLER if x in (veri.get(b) or [])]
        if d and "gor" not in d:
            d.insert(0, "gor")
        sonuc[b] = d
    return sonuc


def denetle(k, method: str, path: str) -> None:
    if k.rol == "sahip" or not path.startswith("/api/") or acik_mi(method, path):
        return
    b = bolum(path)
    if b is None:
        raise HTTPException(403, "Bu işlem için yetkiniz yok.")
    d = duzey(method, path)
    y = yetkileri(k)
    if d in y.get(b, []):
        return
    # Fatura/çek/banka girerken yeni cari ya da şantiye açılabilsin
    if b in _YARDIMCI and d == "ekle" and re.fullmatch(r"(cariler|santiyeler|depolar)", _yol(path)) and \
            any("ekle" in y.get(x, []) for x in _GIRIS_BOLUMLERI):
        return
    raise HTTPException(403, f"Bu işlem için yetkiniz yok ({BOLUMLER[b]}: {DUZEYLER[d].split(' (')[0].lower()}). "
                             "Yetkiyi firma sahibi Araçlar > Kullanıcılar'dan verebilir.")
