"""Çek okuma ölçümü: gerçek taramalarda alan alan doğruluk.

Kullanım (backend klasöründen):  python araclar/cek_olcum.py <klasör> [--ayrinti] [sonuc.json]
Klasörde taranmış çek dosyaları (PDF/resim) ve beklenen.json bulunur:
  {"firma": "firmamızın ünvanı (programdaki gibi)", "cekler": {"dosya.pdf": [{"cek_no": "...", "banka": "...", "tutar": 250000, "vade": "2027-01-25",
                             "kesideci": "...", "lehtar": "..."}, ...]}}
Gerçek çekler müşteri bilgisi taşır: ölçüm klasörü repoya konmaz.

Her alan için sonuç: doğru-yeşil, doğru-kırmızı, yanlış-kırmızı, boş, YANLIŞ-YEŞİL. Yanlış ama yeşil (emin) görünen
değer en tehlikelisidir; hedef sıfır. Her okuma değişikliğinden sonra bu ölçüm öncekiyle karşılaştırılır.
"""
import json
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import cek_okuma, kural  # noqa: E402

ALANLAR = ("cek_no", "banka", "tutar", "vade", "kesideci", "lehtar")


def _ayni(alan: str, okunan, beklenen) -> bool:
    if okunan in (None, ""):
        return False
    if alan == "tutar":
        return abs(float(okunan) - float(beklenen)) < 0.01
    if alan in ("kesideci", "lehtar"):
        # Ad: beklenen adın ilk iki kelimesi okunan adın başında olmalı (ekler, "ŞİRKETİ" satırı fark etmez)
        b = kural.sade(beklenen).split()[:2]
        return kural.sade(str(okunan)).split()[:len(b)] == b
    if alan == "banka":
        return cek_okuma.banka_anahtari(okunan) == cek_okuma.banka_anahtari(beklenen)
    return str(okunan).strip() == str(beklenen).strip()


def sinifla(alan: str, okunan: dict | None, beklenen: dict) -> str:
    if okunan is None or okunan.get(alan) in (None, ""):
        return "bos"
    yesil = alan not in okunan.get("belirsiz", [])
    if _ayni(alan, okunan.get(alan), beklenen[alan]):
        return "dogru_yesil" if yesil else "dogru_kirmizi"
    return "YANLIS_YESIL" if yesil else "yanlis_kirmizi"


def olc(klasor: Path, ayrinti: bool = False) -> dict:
    dosya = json.loads((klasor / "beklenen.json").read_text(encoding="utf-8"))
    beklenen, firma = dosya["cekler"], dosya.get("firma")
    sayim: dict[str, Counter] = {a: Counter() for a in ALANLAR}
    satirlar = []
    fazla = 0
    sure = 0.0
    for ad, liste in beklenen.items():
        bas = time.time()
        okunanlar = cek_okuma.dosyadan_oku((klasor / ad).read_bytes(), ad, "application/pdf")
        sure += time.time() - bas
        for o in okunanlar:
            cek_okuma.lehtari_belirle(o, firma)  # toplu girişte olduğu gibi
        kalan = list(okunanlar)
        for i, b in enumerate(liste):
            # Okunan çek: aynı çek no'lu; yoksa aynı sıradaki (çek no yanlış okunmuş olabilir)
            o = next((x for x in kalan if cek_okuma.cek_no_anahtari(x.get("cek_no")) == cek_okuma.cek_no_anahtari(b["cek_no"])), None)
            if o is None and i < len(okunanlar) and okunanlar[i] in kalan:
                o = okunanlar[i]
            if o is not None:
                kalan.remove(o)
            sonuc = {a: sinifla(a, o, b) for a in ALANLAR}
            for a, s in sonuc.items():
                sayim[a][s] += 1
            satirlar.append((ad, b["cek_no"], sonuc, {a: (o or {}).get(a) for a in ALANLAR}))
        fazla += len(kalan)
    toplam = sum(len(v) for v in beklenen.values())
    if ayrinti:
        for ad, no, sonuc, deger in satirlar:
            kotu = {a: f"{s}:{deger[a]}" for a, s in sonuc.items() if s != "dogru_yesil"}
            print(f"{ad} {no}: {kotu or 'tamam'}")
    return {"cek": toplam, "fazla_cek": fazla, "sure_sn": round(sure), "alanlar": {a: dict(sayim[a]) for a in ALANLAR}}


def yazdir(s: dict) -> None:
    print(f"{s['cek']} çek, fazladan bulunan {s['fazla_cek']}, süre {s['sure_sn']} sn")
    print(f"{'alan':10} {'doğru-yeşil':>12} {'doğru-kırmızı':>14} {'yanlış-kırmızı':>15} {'boş':>5} {'YANLIŞ-YEŞİL':>13}")
    for a, c in s["alanlar"].items():
        print(f"{a:10} {c.get('dogru_yesil', 0):>12} {c.get('dogru_kirmizi', 0):>14} {c.get('yanlis_kirmizi', 0):>15}"
              f" {c.get('bos', 0):>5} {c.get('YANLIS_YESIL', 0):>13}")


if __name__ == "__main__":
    s = olc(Path(sys.argv[1]), "--ayrinti" in sys.argv)
    yazdir(s)
    if len(sys.argv) > 2 and sys.argv[-1].endswith(".json"):
        Path(sys.argv[-1]).write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")
