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
from sqlalchemy.orm import Session

from . import kural
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


def benzerlik(a: str, b: str) -> float:
    """0-1 arası; sayıları farklıysa 0."""
    if not a or not b or _sayilar(a) != _sayilar(b):
        return 0.0
    if sorted(a.split()) == sorted(b.split()):
        return 0.99
    return SequenceMatcher(None, _bitisik(a), _bitisik(b)).ratio()


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

    def benzerler(self, ad: str, adet: int = 5) -> list[tuple[float, Malzeme]]:
        a = anahtar(ad)
        en_iyi: dict[int, tuple[float, Malzeme]] = {}
        for b, m in self.sayiya_gore.get(_sayilar(a), []):
            if SequenceMatcher(None, _bitisik(a), _bitisik(b)).quick_ratio() < BENZERLIK and sorted(a.split()) != sorted(b.split()):
                continue
            o = benzerlik(a, b)
            if o >= BENZERLIK and o > en_iyi.get(m.id, (0, None))[0]:
                en_iyi[m.id] = (o, m)
        return sorted(en_iyi.values(), key=lambda t: -t[0])[:adet]


def onayli_kalemler(db: Session, sirket_id: int):
    return db.scalars(select(FaturaKalem).join(Fatura).where(Fatura.sirket_id == sirket_id, Fatura.durum == "onayli"))


def guncelle(db: Session, sirket_id: int) -> tuple[Dizin, list[dict]]:
    """Onaylı faturaların kalem adlarını kartlara bağlar: karta benzemeyen ada kendiliğinden kart açar; bir karta
    benzeyenleri (kullanıcıya sorulacak) döndürür: [{ad, kalem_sayisi, oneriler: [{id, ad, benzerlik}]}]."""
    dizin = Dizin(list(db.scalars(select(Malzeme).where(Malzeme.sirket_id == sirket_id).order_by(Malzeme.id))))
    sayac: Counter = Counter()
    ilk_yazilis: dict[str, str] = {}
    for kalem in onayli_kalemler(db, sirket_id):
        a = _bitisik(anahtar(kalem.aciklama))
        if a and a not in dizin.tam:
            sayac[a] += 1
            ilk_yazilis.setdefault(a, " ".join((kalem.aciklama or "").split()))
    bekleyen = []
    # En çok geçen yazılış önce: kart onun adıyla açılır, azınlık yazılışlar ona benzer diye sorulur
    for a, n in sorted(sayac.items(), key=lambda t: (-t[1], t[0])):
        ad = ilk_yazilis[a]
        if dizin.bul(ad):
            continue
        oneriler = dizin.benzerler(ad)
        if oneriler:
            bekleyen.append({"ad": ad, "kalem_sayisi": n,
                             "oneriler": [{"id": m.id, "ad": m.ad, "benzerlik": round(o, 2)} for o, m in oneriler]})
            continue
        m = Malzeme(sirket_id=sirket_id, ad=ad[:255])
        db.add(m)
        db.flush()
        dizin.kartlar.append(m)
        dizin.ekle(m)
    db.commit()
    return dizin, bekleyen
