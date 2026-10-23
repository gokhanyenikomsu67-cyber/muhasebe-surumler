"""Kısa sorulara programdaki verilerden cevap (WhatsApp botu ve programdaki "Soru sor" kutusu). Yapay zeka kullanmaz:
soru kelimelerine bakılır, adı geçen şantiye/cari bulunur, cevap var olan rapor hesaplarıyla verilir.

Örnek sorular: "GEBZE şantiye harcaması bu ay", "ABC bakiye", "bu hafta vadesi gelen çekler", "banka bakiyeleri",
"genel durum", "kime borçluyuz". Cevaplar yalnız görüntülemedir; soran kişinin bölüm yetkisi ("Görür") denetlenir.
"""
import re
from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import kural, yetki
from .hesap import RAPOR_DURUMLARI, banka_bakiyeleri, cari_bakiyeleri, isaret, kasa_bakiyesi, satis_tarafi
from .models import ACIK_CEK_DURUMLARI, CEK_DURUMLARI, BankaHesabi, Cari, Cek, Fatura, Hareket, Kullanici, Santiye

AYLAR = ["ocak", "subat", "mart", "nisan", "mayis", "haziran", "temmuz", "agustos", "eylul", "ekim", "kasim", "aralik"]
EN_COK_SATIR = 15

YARDIM = ("Şunları sorabilirsiniz:\n"
          "• *GEBZE şantiye harcaması* (sonuna \"bu ay\", \"geçen ay\", \"mart\", \"2026\" eklenebilir)\n"
          "• *ABC bakiye* (cari bakiyesi)\n"
          "• *bu hafta çekler* / *bu ay ödenecek çekler* / *alınan çekler*\n"
          "• *banka bakiyeleri*\n"
          "• *kime borçluyuz* / *alacaklarımız*\n"
          "• *genel durum*")

# Ad aranırken sorudan atılan kelimeler (sade yazılış)
_ATILAN = set("""
bakiye bakiyesi bakiyemiz bakiyeleri borc borcu borcumuz borclu borclari alacak alacagi alacagimiz alacaklari ne kadar nedir
cari carisi carinin firma firmasi firmanin firmasinin santiye santiyesi santiyenin santiyesinin santiyede harcama harcamasi
harcamalari harcanan gider gideri giderleri gelir geliri toplam toplami bu ay ayi hafta haftaki yil yili gecen bugun yarin
cek cekler cekleri ceki senet senetler banka bankalar kasa hesap hesaplar ve ile mi mu kac para tl son durum durumu var
lutfen bot muhasebe soyle goster ver yaz bana bize acaba icin olan olarak tum hepsi butun genel ozet vade vadesi gelen
gelecek odenecek odeyecegimiz alinan verilen tahsil kalan nedir kadardir simdiye simdiki su an anki
""".split()) | set(AYLAR)


def para(x: float) -> str:
    return f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + " TL"


def gun_ay(t: date | None) -> str:
    return f"{t:%d.%m.%Y}" if t else "-"


def _gorebilir(k: Kullanici, b: str) -> bool:
    return "gor" in yetki.yetkileri(k).get(b, [])


def _yetkisiz(b: str) -> str:
    return f"Bu bilgiyi görme yetkiniz yok ({yetki.BOLUMLER[b]})."


def _kelimeler(s: str) -> list[str]:
    return re.sub(r"[^a-z0-9 ]+", " ", s).split()


def donem(s: str, bugun: date) -> tuple[date | None, date | None, str]:
    """Sorudaki zaman: (başlangıç, bitiş, yazılışı); zaman yoksa (None, None, "")."""
    k = _kelimeler(s)
    if "bugun" in k:
        return bugun, bugun, "bugün"
    if "dun" in k:
        return bugun - timedelta(days=1), bugun - timedelta(days=1), "dün"
    if "hafta" in k or "haftaki" in k:
        bas = bugun - timedelta(days=bugun.weekday())
        if "gecen" in k:
            return bas - timedelta(days=7), bas - timedelta(days=1), "geçen hafta"
        return bas, bas + timedelta(days=6), "bu hafta"
    if "ay" in k or "ayi" in k:
        bas = bugun.replace(day=1)
        if "gecen" in k:
            onceki = bas - timedelta(days=1)
            return onceki.replace(day=1), onceki, "geçen ay"
        sonraki = (bas + timedelta(days=32)).replace(day=1)
        return bas, sonraki - timedelta(days=1), "bu ay"
    yil = next((int(x) for x in k if re.fullmatch(r"20\d\d", x)), None)
    for i, ay in enumerate(AYLAR, 1):
        if ay in k:
            y = yil or bugun.year
            sonraki = date(y + (i == 12), i % 12 + 1, 1)
            return date(y, i, 1), sonraki - timedelta(days=1), f"{ay.capitalize()} {y}"
    if yil:
        return date(yil, 1, 1), date(yil, 12, 31), str(yil)
    if "yil" in k or "yili" in k:
        y = bugun.year - ("gecen" in k)
        return date(y, 1, 1), date(y, 12, 31), str(y)
    return None, None, ""


def _santiye_yazilisi(w: str) -> bool:
    """'şantiye' kelimesi ve yanlış yazılışları: santiye, santiesi, santyesi, şantiyede..."""
    return w.startswith(("santi", "santy"))


# Grupta sohbet sayılan kısa yazılar: cevap verilmez
_SOHBET = {"tamam", "ok", "okey", "peki", "evet", "hayir", "sagol", "sagolun", "tesekkur", "tesekkurler", "eyvallah", "merhaba",
           "selam", "gunaydin", "iyi", "aksamlar", "geceler", "gunler", "hayirli", "isler", "kolay", "gelsin", "olur", "anladim",
           "super", "harika", "guzel", "haha", "tmm", "slm", "mrb", "tsk", "saol"}
ANLAMADIM = "Anlayamadım. Neler sorabileceğinizi görmek için *yardım* yazın."


def _yalniz_ad(s: str, adlar: list[str]) -> bool:
    """Yazıda adın kelimeleri ve soru/zaman kelimelerinden başka kelime yok mu ("gebze santiesi" evet,
    "yarın gebzeye gidiyorum" hayır)."""
    ad_kelimeleri = [a for ad in adlar for a in kural.ad_anahtari(ad).split()]
    return all(x in _ATILAN or x.isdigit() or _santiye_yazilisi(x) or _ad_puani([x], ad_kelimeleri) for x in _kelimeler(s))


def _ad_puani(soru_kelimeleri: list[str], ad_kelimeleri: list[str]) -> int:
    """Sorudaki kaç kelime adın bir kelimesiyle başlıyor (ya da ad kelimesi soru kelimesinin başı: "gebzeye" -> "gebze")."""
    puan = 0
    for s in soru_kelimeleri:
        if any(a.startswith(s) or (len(a) >= 3 and s.startswith(a)) for a in ad_kelimeleri):
            puan += 1
    return puan


def ad_bul(s: str, kayitlar: list, ad=lambda x: kural.kayit_adlari(x), cekirdek=lambda a: kural.ad_anahtari(a)) -> list:
    """Soruda adı geçen kayıtlar: önce tam ad geçen (en uzun ad), yoksa kelime kelime en çok tutanlar."""
    m = f" {s} "
    tam = [(len(a), x) for x in kayitlar for n in ad(x) if len(a := kural.ad_anahtari(n)) >= 3 and f" {a} " in m]
    if tam:
        en = max(t[0] for t in tam)
        return list({id(x): x for n, x in tam if n == en}.values())
    kelimeler = [w for w in _kelimeler(s) if len(w) >= 3 and w not in _ATILAN and not w.isdigit() and not _santiye_yazilisi(w)]
    if not kelimeler:
        return []
    puanli = []
    for x in kayitlar:
        p = max((_ad_puani(kelimeler, cekirdek(n).split()) for n in ad(x)), default=0)
        if p:
            puanli.append((p, x))
    if not puanli:
        return []
    en = max(p for p, _ in puanli)
    return [x for p, x in puanli if p == en]


def _hangisi(tur: str, adaylar: list[str]) -> str:
    satirlar = "\n".join(f"• {a}" for a in adaylar[:8])
    fazla = f"\n… ve {len(adaylar) - 8} tane daha" if len(adaylar) > 8 else ""
    return f"Birden fazla {tur} buldum, adını biraz daha yazar mısınız?\n{satirlar}{fazla}"


# --- Cevaplar ---------------------------------------------------------------

def banka_cevabi(db: Session, k: Kullanici) -> str:
    hesaplar = list(db.scalars(select(BankaHesabi).where(BankaHesabi.sirket_id == k.sirket_id)))
    bakiye = banka_bakiyeleri(db, k.sirket_id)
    satirlar, toplam, kart = [], 0.0, 0.0
    for b in sorted(hesaplar, key=lambda x: kural.tr_sira(x.ad)):
        v = bakiye.get(b.id, 0.0)
        if b.tur == "kredi_karti":
            kart += -v
            satirlar.append(f"• {b.ad}: borç {para(-v)}" if v < 0 else f"• {b.ad}: {para(v)}")
        else:
            toplam += v
            tarih = f" (ekstre {gun_ay(b.ekstre_tarihi)})" if b.ekstre_tarihi else ""
            satirlar.append(f"• {b.ad}: {para(v)}{tarih}")
    kasa = kasa_bakiyesi(db, k.sirket_id)
    satirlar.append(f"• Nakit Kasa: {para(kasa)}")
    alt = f"\n*Banka toplamı: {para(toplam)}*"
    if kart:
        alt += f"\nKredi kartı borcu: {para(kart)}"
    return "*Banka ve kasa bakiyeleri*\n" + "\n".join(satirlar) + alt


def cek_cevabi(db: Session, k: Kullanici, s: str, bugun: date, cari: Cari | None = None) -> str:
    w = _kelimeler(s)
    q = select(Cek).where(Cek.sirket_id == k.sirket_id, Cek.durum.in_(ACIK_CEK_DURUMLARI))
    if cari:
        q = q.where(Cek.cari_id == cari.id)
    yon = None
    if any(x in w for x in ("verilen", "odenecek", "odeyecegimiz", "odeme", "verdigimiz", "kestigimiz")):
        yon = "verilen"
    elif any(x in w for x in ("alinan", "aldigimiz", "tahsil", "portfoy", "portfoydeki", "musteri")):
        yon = "alinan"
    if yon:
        q = q.where(Cek.yon == yon)
    bas, bit, etiket = donem(s, bugun)
    gun = next((int(m.group(1)) for m in [re.search(r"\b(\d{1,3}) gun", s)] if m), None)
    if gun is not None:
        bit, etiket = bugun + timedelta(days=gun), f"{gun} gün içinde"
    if any(x in w for x in ("tum", "hepsi", "butun", "portfoy", "portfoydeki")) and not etiket:
        bit, etiket = None, "tümü"
    elif not etiket and not cari:
        bit, etiket = bugun + timedelta(days=7), "7 gün içinde"
    if bit:
        # Vadesi geçip hâlâ açık olanlar da gösterilir (bas'tan öncekiler gecikmiştir)
        q = q.where(Cek.vade <= bit)
    cekler = list(db.scalars(q.order_by(Cek.vade, Cek.id)))
    baslik = "*Açık çekler*" + (f" — {cari.unvan}" if cari else "") + (f" ({etiket}, vadesi geçenler dahil)" if bit else "")
    if not cekler:
        return baslik + "\nKayıt yok."
    parcalar = [baslik]
    for y, ad in (("alinan", "Alınan (tahsil edilecek)"), ("verilen", "Verilen (ödenecek)")):
        liste = [c for c in cekler if c.yon == y]
        if not liste:
            continue
        parcalar.append(f"\n_{ad}: {len(liste)} çek, {para(sum(float(c.tutar) for c in liste))}_")
        for c in liste[:EN_COK_SATIR]:
            gecti = " ⚠️ vadesi geçti" if c.vade < bugun else ""
            kim = c.cari.unvan if c.cari else (c.kesideci or c.lehtar or "")
            durum = CEK_DURUMLARI[y].get(c.durum, c.durum)
            parcalar.append(f"• {gun_ay(c.vade)} · {kim or '-'} · {para(float(c.tutar))} ({durum}){gecti}")
        if len(liste) > EN_COK_SATIR:
            parcalar.append(f"… ve {len(liste) - EN_COK_SATIR} çek daha")
    return "\n".join(parcalar)


def santiye_cevabi(db: Session, k: Kullanici, santiye: Santiye, s: str, bugun: date) -> str:
    from .routers.raporlar import santiye_paylari
    bas, bit, etiket = donem(s, bugun)
    q = select(Fatura).where(Fatura.sirket_id == k.sirket_id, Fatura.durum.in_(RAPOR_DURUMLARI))
    if bas:
        q = q.where(Fatura.tarih >= bas, Fatura.tarih <= bit)
    gider = gelir = 0.0
    turler: dict[str, float] = defaultdict(float)
    fatura_sayisi = 0
    for f in db.scalars(q):
        p = santiye_paylari(f).get(santiye.id)
        if not p:
            continue
        fatura_sayisi += 1
        tutar = p["genel"] * isaret(f)
        if satis_tarafi(f):
            gelir += tutar
        else:
            gider += tutar
            turler[f.gider_turu or "Belirtilmemiş"] += tutar
    hq = select(Hareket).where(Hareket.sirket_id == k.sirket_id, Hareket.durum == "onayli", Hareket.santiye_id == santiye.id,
                               Hareket.tur.in_(["masraf", "banka_masrafi"]))
    if bas:
        hq = hq.where(Hareket.tarih >= bas, Hareket.tarih <= bit)
    for h in db.scalars(hq):
        gider += float(h.tutar)
        turler[h.gider_turu or "Belirtilmemiş"] += float(h.tutar)
    satirlar = [f"*{santiye.ad}* şantiyesi" + (f" ({etiket})" if etiket else " (tüm zamanlar)"),
                f"Harcama (KDV dahil): *{para(gider)}*"]
    if gelir:
        satirlar.append(f"Satış: {para(gelir)}  ·  Fark: {para(gelir - gider)}")
    if santiye.butce is not None and not bas:
        satirlar.append(f"Bütçe: {para(float(santiye.butce))}  ·  Kalan: {para(float(santiye.butce) - gider)}")
    if turler:
        satirlar.append("En büyük gider türleri:")
        for t, v in sorted(turler.items(), key=lambda x: -x[1])[:5]:
            satirlar.append(f"• {t}: {para(v)}")
    satirlar.append(f"_{fatura_sayisi} fatura_" if fatura_sayisi else "_Bu dönemde fatura yok._")
    return "\n".join(satirlar)


def cari_cevabi(db: Session, k: Kullanici, c: Cari) -> str:
    t = cari_bakiyeleri(db, k.sirket_id).get(c.id, {"borc": 0.0, "alacak": 0.0})
    bakiye = round(t["borc"] - t["alacak"], 2)
    if bakiye > 0:
        durum = f"{c.unvan} *bize {para(bakiye)} borçlu*."
    elif bakiye < 0:
        durum = f"*Biz {c.unvan} firmasına {para(-bakiye)} borçluyuz.*"
    else:
        durum = f"{c.unvan}: bakiye sıfır."
    satirlar = [durum, f"Toplam borç: {para(t['borc'])} · Toplam alacak: {para(t['alacak'])}"]
    if _gorebilir(k, "cek"):
        acik = list(db.scalars(select(Cek).where(Cek.sirket_id == k.sirket_id, Cek.cari_id == c.id,
                                                 Cek.durum.in_(ACIK_CEK_DURUMLARI))))
        if acik:
            satirlar.append(f"Açık çek: {len(acik)} adet, {para(sum(float(x.tutar) for x in acik))} "
                            f"(en yakın vade {gun_ay(min(x.vade for x in acik))})")
    return "\n".join(satirlar)


def borc_listesi(db: Session, k: Kullanici, alacak: bool) -> str:
    toplam = cari_bakiyeleri(db, k.sirket_id)
    adlar = {c.id: c.unvan for c in db.scalars(select(Cari).where(Cari.sirket_id == k.sirket_id))}
    liste = [(adlar.get(i, "?"), round(t["borc"] - t["alacak"], 2)) for i, t in toplam.items()]
    liste = [(a, v) for a, v in liste if (v > 0.005 if alacak else v < -0.005)]
    liste.sort(key=lambda x: -abs(x[1]))
    baslik = "*Alacaklarımız (bize borçlu olanlar)*" if alacak else "*Borçlarımız (borçlu olduğumuz firmalar)*"
    if not liste:
        return baslik + "\nKayıt yok."
    satirlar = [baslik] + [f"• {a}: {para(abs(v))}" for a, v in liste[:EN_COK_SATIR]]
    if len(liste) > EN_COK_SATIR:
        satirlar.append(f"… ve {len(liste) - EN_COK_SATIR} firma daha")
    satirlar.append(f"*Toplam: {para(sum(abs(v) for _, v in liste))}*")
    return "\n".join(satirlar)


def genel_durum(db: Session, k: Kullanici, bugun: date) -> str:
    satirlar = ["*Genel durum*"]
    if _gorebilir(k, "banka"):
        hesaplar = {b.id: b for b in db.scalars(select(BankaHesabi).where(BankaHesabi.sirket_id == k.sirket_id))}
        bakiye = banka_bakiyeleri(db, k.sirket_id)
        satirlar.append(f"Banka: {para(sum(v for i, v in bakiye.items() if hesaplar[i].tur != 'kredi_karti'))}")
        satirlar.append(f"Kasa: {para(kasa_bakiyesi(db, k.sirket_id))}")
    if _gorebilir(k, "cari"):
        degerler = [t["borc"] - t["alacak"] for t in cari_bakiyeleri(db, k.sirket_id).values()]
        satirlar.append(f"Alacaklarımız: {para(sum(v for v in degerler if v > 0))}")
        satirlar.append(f"Borçlarımız: {para(-sum(v for v in degerler if v < 0))}")
    if _gorebilir(k, "cek"):
        acik = list(db.scalars(select(Cek).where(Cek.sirket_id == k.sirket_id, Cek.durum.in_(ACIK_CEK_DURUMLARI))))
        hafta = bugun + timedelta(days=7)
        for y, ad in (("alinan", "Portföydeki çek"), ("verilen", "Ödenecek çek")):
            liste = [c for c in acik if c.yon == y]
            yakin = [c for c in liste if c.vade <= hafta]
            satirlar.append(f"{ad}: {para(sum(float(c.tutar) for c in liste))}"
                            + (f" (7 gün içinde {len(yakin)} çek, {para(sum(float(c.tutar) for c in yakin))})" if yakin else ""))
    return "\n".join(satirlar) if len(satirlar) > 1 else _yetkisiz("rapor")


# --- Soruyu anlama ----------------------------------------------------------

def cevapla(db: Session, k: Kullanici, metin: str, bugun: date | None = None, sohbet: bool = False) -> str | None:
    """Sorunun cevabı; anlaşılmazsa None (WhatsApp'ta sohbet mesajlarına karışmamak için sessiz kalınır).
    sohbet=True (WhatsApp grubu): uzun yazıda yalnız ad geçiyorsa ("yarın Gebze'ye gidiyorum") cevap verilmez; soru kelimesi
    (harcama, bakiye, çek, banka...), soru işareti ya da kısa yazı (en çok 4 kelime) gerekir. Anlaşılmayan kısa yazıya
    "Anlayamadım, yardım yazın" denir; "tamam", "sağol" gibi sohbete cevap verilmez."""
    bugun = bugun or date.today()
    s = kural.sade(metin).strip(" ?!.")
    w = _kelimeler(s)
    if not w:
        return None
    if s in ("yardim", "menu", "neler sorabilirim", "ne sorabilirim", "komutlar") or w[0] == "yardim":
        return YARDIM
    ws = set(w)
    if ws & {"genel", "ozet"} and ("durum" in ws or "ozet" in ws):
        return genel_durum(db, k, bugun)
    if re.search(r"\b(kime borcluyuz|borclarimiz|borclu oldugumuz|odenecek borclar)\b", s):
        return borc_listesi(db, k, alacak=False) if _gorebilir(k, "cari") else _yetkisiz("cari")
    if re.search(r"\b(alacaklarimiz|kimden alacag|bize borclu|alacakli oldugumuz)\b", s):
        return borc_listesi(db, k, alacak=True) if _gorebilir(k, "cari") else _yetkisiz("cari")

    cek_sorusu = bool(ws & {"cek", "cekler", "cekleri", "ceki", "ceklerimiz", "senet", "senetler"})
    banka_sorusu = bool(ws & {"banka", "bankalar", "bankada", "bankadaki", "kasa", "kasada", "hesaplar", "kart"}) and not cek_sorusu
    santiye_adi_gecti = any(_santiye_yazilisi(x) for x in w)
    santiye_kelimesi = santiye_adi_gecti or any(x.startswith(("harca", "gider")) for x in w)
    cari_kelimesi = any(x.startswith(("bakiy", "borc", "alaca", "cari", "ekstre")) for x in w)
    # Grupta kısa yazı (en çok 4 kelime) soru sayılır: "gebze", "gebze santiesi", "ahmet yapı"
    kisa = len(w) <= 4 and not set(w) <= _SOHBET
    anlamadim = ANLAMADIM if sohbet and kisa else None

    if sohbet and not (cek_sorusu or banka_sorusu or santiye_kelimesi or cari_kelimesi or kisa or metin.strip().endswith("?")):
        return None

    if banka_sorusu and not cari_kelimesi or banka_sorusu and ws & {"bakiyeleri", "bakiyemiz"}:
        return banka_cevabi(db, k) if _gorebilir(k, "banka") else _yetkisiz("banka")

    santiyeler = list(db.scalars(select(Santiye).where(Santiye.sirket_id == k.sirket_id)))
    cariler = list(db.scalars(select(Cari).where(Cari.sirket_id == k.sirket_id)))
    cari_bul = lambda: ad_bul(s, cariler, ad=lambda c: [c.unvan], cekirdek=lambda a: kural.unvan_cekirdegi(a, True))  # noqa: E731

    if cek_sorusu:
        if not _gorebilir(k, "cek"):
            return _yetkisiz("cek")
        bulunan = cari_bul()
        if len(bulunan) > 1:
            return _hangisi("firma", [c.unvan for c in bulunan])
        return cek_cevabi(db, k, s, bugun, bulunan[0] if bulunan else None)

    s_bulunan = ad_bul(s, santiyeler) if not cari_kelimesi or santiye_kelimesi else []
    soru_kelimesi = santiye_kelimesi or cari_kelimesi or metin.strip().endswith("?")
    if s_bulunan and (santiye_kelimesi or not cari_kelimesi):
        if sohbet and not soru_kelimesi and not _yalniz_ad(s, [n for x in s_bulunan for n in kural.kayit_adlari(x)]):
            return None
        if not _gorebilir(k, "santiye"):
            return _yetkisiz("santiye")
        if len(s_bulunan) > 1:
            return _hangisi("şantiye", [x.ad for x in s_bulunan])
        return santiye_cevabi(db, k, s_bulunan[0], s, bugun)
    c_bulunan = cari_bul()
    if c_bulunan:
        if sohbet and not soru_kelimesi and not _yalniz_ad(s, [x.unvan for x in c_bulunan]):
            return None
        if not _gorebilir(k, "cari"):
            return _yetkisiz("cari")
        if len(c_bulunan) > 1:
            return _hangisi("firma", [c.unvan for c in c_bulunan])
        return cari_cevabi(db, k, c_bulunan[0])
    if santiye_adi_gecti:
        return "Hangi şantiye? Şantiyenin adını da yazar mısınız? (ör. \"GEBZE şantiye harcaması bu ay\")"
    if cari_kelimesi:
        return "Hangi firma? Firmanın adını da yazar mısınız? (ör. \"ABC bakiye\")"
    return anlamadim
