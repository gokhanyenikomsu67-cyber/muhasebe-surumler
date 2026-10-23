"""Malzeme kartları: faturalarda biraz farklı yazılmış aynı malzemeyi ("ÇİMENTO 50KG", "Cimento 50 kg.") tek kartta
toplar. Kalem kendi adını korur; karta adıyla bağlanır (kartın adı ya da eski adlarından biri).

- Yazılışı aynı (harf, Türkçe karakter, boşluk, nokta farkı yok sayılır) -> o kart.
- Hiçbir karta benzemiyorsa kendiliğinden yeni kart açılır.
- Bir karta benziyorsa kullanıcıya sorulur (bekleyen); karar karta eski ad olarak eklenir ya da ayrı kart açılır.
Benzerlik: içindeki sayılar aynı olmalı (3x2,5 ile 3x4 ayrı malzemedir) ve yazılış çok yakın ya da kelimeler aynı olmalı.
"""
import re
from collections import Counter
from difflib import SequenceMatcher

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from . import kural
from .hesap import RAPOR_DURUMLARI, firma_adi, tl_kur
from .models import Fatura, FaturaKalem, Malzeme

BENZERLIK = 0.85


def anahtar(ad: str | None) -> str:
    """Karşılaştırma için sade yazılış (kelimeler boşlukla): '3 X 2,5 mm²' -> '3x2.5 mm2'."""
    m = kural.sade(ad).replace("²", "2").replace("³", "3")
    m = re.sub(r"(?<=\d),(?=\d)", ".", m)
    m = re.sub(r"(?<=\d)\s*[x*×]\s*(?=\d)", "x", m)
    m = re.sub(r"[^a-z0-9.x]+|(?<!\d)\.|\.(?!\d)", " ", m)
    m = re.sub(r"(?<=\d)(?=[a-wyz])|(?<=[a-wyz])(?=\d)", " ", m)  # "50kg" -> "50 kg"
    return " ".join(m.split())


def _bitisik(a: str) -> str:
    return a.replace(" ", "")


def _sayilar(a: str) -> tuple:
    return tuple(float(x) for x in re.findall(r"\d+(?:\.\d+)?", a))


def ayni_mi(a: str, b: str) -> bool:
    return bool(a) and _bitisik(a) == _bitisik(b)


# Ayırt edici kelimeler: aynı gruptan farklı iki kelime iki ayrı kalem demektir ("Yüksek Kademe" ile "Düşük Kademe").
_ZIT = [{"yuksek", "dusuk"}, {"alt", "ust"}, {"ic", "ici", "dis", "disi"}, {"sag", "sol"}, {"buyuk", "kucuk"},
        {"ince", "kalin"}, {"sicak", "soguk"}, {"on", "arka"}, {"giris", "cikis"}, {"gunduz", "gece", "puant"},
        {"erkek", "dis"}, {"tek", "cift"}, {"acik", "kapali"}, {"ana", "yan"}, {"min", "max", "maks"},
        {"beyaz", "siyah", "gri", "kirmizi", "mavi", "yesil", "sari", "kahverengi", "turuncu", "mor"},
        {"aktif", "reaktif"}, {"alis", "satis"}, {"dikey", "yatay"}, {"yeni", "eski"}, {"kisa", "uzun"},
        {"ilk", "son"}, {"tam", "yarim"}, {"erkek", "kadin"}, {"bay", "bayan"}]
_AYIRT_EDICI = set().union(*_ZIT)


def _kelime_esi(x: str, y: str) -> bool:
    """İki kelime aynı mı: aynı, kısaltma ("nak" = "nakliye") ya da harf hatası ("cimento" ~ "cimentu")."""
    if x == y:
        return True
    if x in _AYIRT_EDICI or y in _AYIRT_EDICI or x.isdigit() or y.isdigit():
        return False
    kisa, uzun = sorted((x, y), key=len)
    if len(kisa) >= 3 and uzun.startswith(kisa):
        return True
    return len(kisa) >= 4 and SequenceMatcher(None, x, y).ratio() >= 0.8


def karsilastir(a: str, b: str) -> tuple[float, bool, list[str]]:
    """(benzerlik 0-1, güçlü mü, yalnız birinde geçen kelimeler). Sayıları farklı ya da zıt kelimeli (yüksek/düşük)
    adlar benzer değildir (0). Güçlü: bütün kelimeler karşılıklı eşleşiyor (sıra, kısaltma, harf hatası farkı);
    bir tarafta fazladan kelime varsa ("KONAKLAMA" / "ODA KONAKLAMA") güçlü değildir, kullanıcı bakmalıdır."""
    if not a or not b or _sayilar(a) != _sayilar(b):
        return 0.0, False, []
    ka, kb = a.split(), b.split()
    kalan = list(kb)
    fazla_a = []
    for x in ka:
        es = next((y for y in kalan if _kelime_esi(x, y)), None)
        if es is None:
            fazla_a.append(x)
        else:
            kalan.remove(es)
    farklar = fazla_a + kalan
    if any(len(g & set(fazla_a)) and len(g & set(kalan)) and (g & set(fazla_a)) != (g & set(kalan)) for g in _ZIT):
        return 0.0, False, farklar
    oran = SequenceMatcher(None, _bitisik(a), _bitisik(b)).ratio()
    harfli = any(not x.isdigit() and not re.fullmatch(r"[\d.x]+", x) for x in ka)
    if not farklar and harfli:
        return max(oran, 0.95), True, []
    return (oran if oran >= BENZERLIK else 0.0), False, farklar


def benzerlik(a: str, b: str) -> float:
    """0-1 arası; sayıları farklı ya da zıt kelimeliyse 0."""
    return karsilastir(a, b)[0]


def kart_adlari(m: Malzeme) -> list[str]:
    return kural.kayit_adlari(m)


def ad_ekle(m: Malzeme, ad: str) -> None:
    """Kalemde geçen yazılışı kartın eski adlarına ekler (zaten varsa eklemez)."""
    if any(ayni_mi(anahtar(x), anahtar(ad)) for x in kart_adlari(m)):
        return
    m.eski_adlar = "\n".join([*(m.eski_adlar or "").splitlines(), ad.strip()]).strip() or None


class Dizin:
    """Şirketin kartları: yazılıştan karta hızlı arama ve benzer kart önerisi."""

    def __init__(self, kartlar: list[Malzeme]):
        self.kartlar = kartlar
        self.tam: dict[str, Malzeme] = {}
        self.sayiya_gore: dict[tuple, list[tuple[str, Malzeme]]] = {}
        for m in kartlar:
            self.ekle(m)

    def ekle(self, m: Malzeme) -> None:
        for x in kart_adlari(m):
            a = anahtar(x)
            if a:
                self.tam.setdefault(_bitisik(a), m)
                self.sayiya_gore.setdefault(_sayilar(a), []).append((a, m))

    def bul(self, ad: str | None) -> Malzeme | None:
        return self.tam.get(_bitisik(anahtar(ad)))

    def benzerler(self, ad: str, adet: int = 5) -> list[tuple[float, bool, list[str], Malzeme]]:
        """Benzer kartlar, güçlü öneriler önce: (benzerlik, güçlü mü, farklı kelimeler, kart)."""
        a = anahtar(ad)
        en_iyi: dict[int, tuple] = {}
        for b, m in self.sayiya_gore.get(_sayilar(a), []):
            if SequenceMatcher(None, _bitisik(a), _bitisik(b)).quick_ratio() < 0.6:
                continue
            o, guclu, farklar = karsilastir(a, b)
            if o and (m.id not in en_iyi or (guclu, o) > (en_iyi[m.id][1], en_iyi[m.id][0])):
                en_iyi[m.id] = (o, guclu, farklar, m)
        return sorted(en_iyi.values(), key=lambda t: (not t[1], -t[0]))[:adet]


def onayli_kalemler(db: Session, sirket_id: int):
    """Onaylı ve Wolvox'tan aktarılan faturaların kalemleri."""
    return db.scalars(select(FaturaKalem).join(Fatura).where(Fatura.sirket_id == sirket_id, Fatura.durum.in_(RAPOR_DURUMLARI))
                      .options(joinedload(FaturaKalem.fatura).joinedload(Fatura.cari)))


def _kalem_ozeti(k: FaturaKalem) -> dict:
    f = k.fatura
    kur = tl_kur(f)
    miktar = float(k.miktar or 0)
    return {"fatura_id": f.id, "fatura_no": f.fatura_no, "tarih": f.tarih, "yon": f.yon,
            "cari": firma_adi(f), "miktar": miktar, "birim": k.birim,
            "birim_fiyat": round(float(k.tutar or 0) * kur / miktar, 4) if miktar else None,
            "tutar": round(float(k.tutar or 0) * kur, 2)}


# Benzer kart önerileri pahalıdır (binlerce ad): kartlar değişmedikçe önceki sonuç kullanılır.
# {sirket_id: (kartların imzası, {ad anahtarı: [(benzerlik, güçlü, farklar, kart id)]})}
_ONERI_BELLEGI: dict[int, tuple[int, dict]] = {}


def _imza(kartlar: list[Malzeme]) -> int:
    return hash(tuple((m.id, m.ad, m.eski_adlar) for m in kartlar))


def guncelle(db: Session, sirket_id: int) -> tuple[Dizin, list[dict]]:
    """Onaylı faturaların kalem adlarını kartlara bağlar: karta benzemeyen ada kendiliğinden kart açar; bir karta
    benzeyenleri (kullanıcıya sorulacak) kalemleriyle döndürür:
    [{ad, kalem_sayisi, kalemler: [...], oneriler: [{id, ad, benzerlik, guclu, farklar, birim, ortalama_fiyat}]}]."""
    dizin = Dizin(list(db.scalars(select(Malzeme).where(Malzeme.sirket_id == sirket_id).order_by(Malzeme.id))))
    kalemler = list(onayli_kalemler(db, sirket_id))
    gruplar: dict[str, list[FaturaKalem]] = {}
    for kalem in kalemler:
        a = _bitisik(anahtar(kalem.aciklama))
        if a and a not in dizin.tam:
            gruplar.setdefault(a, []).append(kalem)
    sorulacak = []
    imza = _imza(dizin.kartlar)
    bellek = _ONERI_BELLEGI[sirket_id][1] if _ONERI_BELLEGI.get(sirket_id, (None,))[0] == imza else {}
    yeni_bellek, kart_acildi = {}, False
    kimlik = {m.id: m for m in dizin.kartlar}
    # En çok geçen yazılış önce: kart onun adıyla açılır, azınlık yazılışlar ona benzer diye sorulur
    for a, grup in sorted(gruplar.items(), key=lambda t: (-len(t[1]), t[0])):
        ad = " ".join((grup[0].aciklama or "").split())
        if dizin.bul(ad):
            continue
        if a in bellek:
            oneriler = [(o, g, f, kimlik[i]) for o, g, f, i in bellek[a]]
        else:
            oneriler = dizin.benzerler(ad)
        if oneriler:
            yeni_bellek[a] = [(o, g, f, m.id) for o, g, f, m in oneriler]
            sorulacak.append((ad, grup, oneriler))
            continue
        m = Malzeme(sirket_id=sirket_id, ad=ad[:255])
        db.add(m)
        db.flush()
        dizin.kartlar.append(m)
        dizin.ekle(m)
        kart_acildi = True
    if kart_acildi:
        # Yüklü kalem ve kartlar yeniden okunmasın (binlerce kalemde tek tek sorgu olur): yalnız yeni kartlar yazılır
        eski, db.expire_on_commit = db.expire_on_commit, False
        try:
            db.commit()
        finally:
            db.expire_on_commit = eski
    if kart_acildi:  # yeni kart, önceki adlara da öneri olabilir: bir dahaki sefer baştan hesaplanır
        _ONERI_BELLEGI.pop(sirket_id, None)
    else:
        _ONERI_BELLEGI[sirket_id] = (imza, yeni_bellek)
    if not sorulacak:
        return dizin, []
    # Önerilen kartın birimi ve ortalama fiyatı (kullanıcı karşılaştırsın)
    istenen = {m.id for _, _, o in sorulacak for *_, m in o}
    ozet: dict[int, dict] = {}
    for kalem in kalemler:
        m = dizin.bul(kalem.aciklama)
        if m and m.id in istenen:
            x = _kalem_ozeti(kalem)
            o = ozet.setdefault(m.id, {"birimler": Counter(), "miktar": 0.0, "tutar": 0.0, "sayi": 0})
            o["birimler"][x["birim"] or "-"] += 1
            o["miktar"] += x["miktar"]
            o["tutar"] += x["tutar"]
            o["sayi"] += 1
    bekleyen = []
    for ad, grup, oneriler in sorulacak:
        liste = []
        for o, guclu, farklar, m in oneriler:
            st = ozet.get(m.id) or {"birimler": Counter(), "miktar": 0, "tutar": 0, "sayi": 0}
            liste.append({"id": m.id, "ad": m.ad, "benzerlik": round(o, 2), "guclu": guclu, "farklar": farklar,
                          "birim": st["birimler"].most_common(1)[0][0] if st["birimler"] else None, "kalem_sayisi": st["sayi"],
                          "ortalama_fiyat": round(st["tutar"] / st["miktar"], 2) if st["miktar"] else None})
        bekleyen.append({"ad": ad, "kalem_sayisi": len(grup), "oneriler": liste,
                         "kalemler": sorted((_kalem_ozeti(k) for k in grup), key=lambda x: x["tarih"], reverse=True)})
    return dizin, bekleyen
