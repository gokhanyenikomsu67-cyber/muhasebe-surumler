"""Mali raporlar: KDV özeti, Ba-Bs formları, gelir-gider tablosu ve cari yaşlandırma (vade analizi).

Hepsi onaylı kayıtlardan hesaplanır; beyanname yerine geçmez, mali müşavire ön bilgi ve kontrol amaçlıdır.
"""
MALI_UYARI = "Mali müşavirle karşılaştırma amaçlıdır; resmi beyan yerine geçmez."
BABS_KALDIRILDI = "Ba-Bs bildirimi Eylül 2024 döneminden itibaren verilmiyor (VUK Genel Tebliği 565); bu liste iç kontrol içindir."
from collections import defaultdict
from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import aktif_kullanici
from ..db import get_db
from ..hesap import cari_hareketleri, fatura_vadesi, isaret, satis_tarafi, tl_kur
from ..models import Cari, Fatura, Hareket, Kullanici
from .raporlar import _excel

router = APIRouter(prefix="/api")

AYLAR = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]


def _yil_faturalari(db: Session, k: Kullanici, yil: int) -> list[Fatura]:
    return db.scalars(select(Fatura).where(Fatura.sirket_id == k.sirket_id, Fatura.durum == "onayli",
                                           Fatura.tarih >= date(yil, 1, 1), Fatura.tarih <= date(yil, 12, 31))).all()


# --- KDV özeti -------------------------------------------------------------

def kdv_veri(db: Session, k: Kullanici, yil: int, devreden: float = 0) -> dict:
    """Aylık hesaplanan / indirilecek KDV. Satıştaki tevkifatı alıcı öder (KDV-1'den düşülür);
    alıştaki tevkifatı biz sorumlu sıfatıyla KDV-2 ile öderiz."""
    aylar = [{"ay": i + 1, "ad": AYLAR[i], "satis_matrah": 0.0, "hesaplanan": 0.0, "satis_tevkifat": 0.0,
              "alis_matrah": 0.0, "indirilecek": 0.0, "alis_tevkifat": 0.0, "oranlar": defaultdict(lambda: [0.0, 0.0])}
             for i in range(12)]
    for f in _yil_faturalari(db, k, yil):
        a = aylar[f.tarih.month - 1]
        # TL karşılığıyla; müşteriden gelen iade hesaplanan KDV'yi, tedarikçiye kestiğimiz iade indirilecek KDV'yi azaltır
        satis, c = satis_tarafi(f), isaret(f) * tl_kur(f)
        a["satis_matrah" if satis else "alis_matrah"] += c * float(f.ara_toplam)
        a["hesaplanan" if satis else "indirilecek"] += c * float(f.kdv_toplam)
        a["satis_tevkifat" if satis else "alis_tevkifat"] += c * float(f.tevkifat or 0)
        if satis:
            for kl in f.kalemler:
                o = a["oranlar"][float(kl.kdv_orani)]
                o[0] += c * float(kl.tutar)
                o[1] += c * kl.kdv
    devir = float(devreden or 0)
    for a in aylar:
        a["onceki_devreden"] = round(devir, 2)
        sonuc = a["hesaplanan"] - a["satis_tevkifat"] - a["indirilecek"] - devir
        a["odenecek"] = round(max(sonuc, 0), 2)
        devir = max(-sonuc, 0)
        a["devreden"] = round(devir, 2)
        a["kdv2"] = round(a["alis_tevkifat"], 2)
        a["oranlar"] = [{"oran": o, "matrah": round(v[0], 2), "kdv": round(v[1], 2)} for o, v in sorted(a["oranlar"].items())]
        for alan in ("satis_matrah", "hesaplanan", "satis_tevkifat", "alis_matrah", "indirilecek", "alis_tevkifat"):
            a[alan] = round(a[alan], 2)
    return {"yil": yil, "aylar": aylar}


@router.get("/raporlar/kdv")
def kdv_ozeti(yil: int, devreden: float = 0, db: Session = Depends(get_db), k: Kullanici = Depends(aktif_kullanici)):
    return kdv_veri(db, k, yil, devreden)


@router.get("/excel/kdv")
def excel_kdv(yil: int, devreden: float = 0, db: Session = Depends(get_db), k: Kullanici = Depends(aktif_kullanici)):
    v = kdv_veri(db, k, yil, devreden)
    return _excel(f"KDV {yil}", ["Ay", "Satış Matrahı", "Hesaplanan KDV", "Satışta Tevkifat (alıcı öder)", "Alış Matrahı",
                                 "İndirilecek KDV", "Önceki Aydan Devreden", "Ödenecek KDV (KDV-1)", "Sonraki Aya Devreden",
                                 "Sorumlu Sıfatıyla KDV-2 (alıştaki tevkifat)"],
                  [[a["ad"], a["satis_matrah"], a["hesaplanan"], a["satis_tevkifat"], a["alis_matrah"], a["indirilecek"],
                    a["onceki_devreden"], a["odenecek"], a["devreden"], a["kdv2"]] for a in v["aylar"]], f"kdv-ozeti-{yil}",
                  dipnot=MALI_UYARI)


# --- Tevkifat ----------------------------------------------------------------

def _sinir_uyarisi(f: Fatura, parcalar: list[tuple], c: float) -> str | None:
    """Kısmi tevkifatlı fatura KDV dahil yıllık sınırı aşmıyorsa tevkifat gerekmeyebilir (rakamlara dokunulmaz)."""
    from .. import kural
    sinir = kural.tevkifat_siniri(f.tarih.year)
    kismi = any(0 < p[1] < 10 for p in parcalar)
    kdv_dahil = c * (float(f.ara_toplam) + float(f.kdv_toplam))
    if sinir and kismi and kdv_dahil <= sinir:
        return f"KDV dahil {sinir:,.0f} TL sınırını aşmıyor; tevkifat gerekmeyebilir.".replace(",", ".")
    return None


def tevkifat_veri(db: Session, k: Kullanici, yil: int, ay: int = 0) -> dict:
    """Dönemdeki tevkifatlı onaylı faturalar; alış (KDV-2 ile biz öderiz) ve satış (alıcı öder) ayrı, KDVGUT koduna göre.
    Satırında oran olmayan eski kayıtlar 'kodsuz' grupta fatura toplamıyla yer alır."""
    from .. import kural
    bas, son = (date(yil, ay, 1), date(yil + (ay == 12), ay % 12 + 1, 1)) if ay else (date(yil, 1, 1), date(yil + 1, 1, 1))
    q = select(Fatura).where(Fatura.sirket_id == k.sirket_id, Fatura.durum == "onayli", Fatura.tarih >= bas, Fatura.tarih < son,
                             Fatura.tevkifat != 0).order_by(Fatura.tarih, Fatura.id)
    gruplar: dict[tuple, dict] = {}
    faturalar = []
    for f in db.scalars(q):
        yon = "satis" if f.yon == "giden" else "alis"
        c = tl_kur(f)  # dövizli fatura TL karşılığıyla
        satirlar = [kl for kl in f.kalemler if float(kl.tevkifat_orani or 0)]
        parcalar = [(kl.tevkifat_kodu or "", float(kl.tevkifat_orani), c * float(kl.tutar), c * kl.kdv,
                     c * kural.tevkifat_tutari(kl.tutar, kl.kdv_orani, kl.tevkifat_orani, kl.kdv_tutari)) for kl in satirlar] or \
                   [("", 0.0, c * float(f.ara_toplam), c * float(f.kdv_toplam), c * float(f.tevkifat))]
        for kod, pay, matrah, kdv, tevk in parcalar:
            g = gruplar.setdefault((yon, kod, pay), {
                "yon": yon, "kod": kod or None, "oran": f"{pay:g}/10" if pay else "-",
                "aciklama": kural.TEVKIFAT_KODLARI.get(kod, (None, "Kodu girilmemiş" if pay else "Satırlarda oran yok (fatura toplamı)"))[1],
                "belge_sayisi": 0, "matrah": 0.0, "kdv": 0.0, "tevkifat": 0.0, "_faturalar": set()})
            g["_faturalar"].add(f.id)
            g["matrah"] += matrah
            g["kdv"] += kdv
            g["tevkifat"] += tevk
        faturalar.append({"id": f.id, "yon": yon, "tarih": f.tarih.isoformat(), "fatura_no": f.fatura_no,
                          "cari": f.cari.unvan if f.cari else None, "vkn": f.cari.vkn if f.cari else None,
                          "kodlar": ", ".join(sorted({p[0] for p in parcalar if p[0]})) or None,
                          "matrah": round(sum(p[2] for p in parcalar), 2), "kdv": round(sum(p[3] for p in parcalar), 2),
                          "tevkifat": round(c * float(f.tevkifat), 2), "odenecek": round(c * float(f.genel_toplam), 2),
                          "uyari": _sinir_uyarisi(f, parcalar, c)})
    sonuc = {"yil": yil, "ay": ay, "alis": [], "satis": [], "faturalar": faturalar}
    for (yon, _, _), g in sorted(gruplar.items(), key=lambda x: (x[0][1] or "999", x[0][2])):
        g["belge_sayisi"] = len(g.pop("_faturalar"))
        for a in ("matrah", "kdv", "tevkifat"):
            g[a] = round(g[a], 2)
        sonuc[yon].append(g)
    sonuc["kdv2"] = round(sum(g["tevkifat"] for g in sonuc["alis"]), 2)
    sonuc["satis_tevkifat"] = round(sum(g["tevkifat"] for g in sonuc["satis"]), 2)
    return sonuc


@router.get("/raporlar/tevkifat")
def tevkifat_raporu(yil: int, ay: int = 0, db: Session = Depends(get_db), k: Kullanici = Depends(aktif_kullanici)):
    return tevkifat_veri(db, k, yil, ay)


@router.get("/excel/tevkifat")
def excel_tevkifat(yil: int, ay: int = 0, db: Session = Depends(get_db), k: Kullanici = Depends(aktif_kullanici)):
    v = tevkifat_veri(db, k, yil, ay)
    donem = f"{ay:02d}-{yil}" if ay else str(yil)
    satirlar = [[("Alış (KDV-2, biz öderiz)" if g["yon"] == "alis" else "Satış (alıcı öder)"), g["kod"], g["oran"], g["aciklama"],
                 g["belge_sayisi"], g["matrah"], g["kdv"], g["tevkifat"]] for y in ("alis", "satis") for g in v[y]]
    satirlar.append([None] * 11)
    baslik = len(satirlar)
    satirlar.append(["Fatura", "Tarih", "Fatura No", "Cari", "VKN", "Kod", "KDV Hariç", "KDV", "Tevkifat", "Ödenecek", "Uyarı"])
    satirlar += [["Alış" if f["yon"] == "alis" else "Satış", f["tarih"], f["fatura_no"], f["cari"], f["vkn"], f["kodlar"],
                  f["matrah"], f["kdv"], f["tevkifat"], f["odenecek"], f["uyari"]] for f in v["faturalar"]]
    return _excel(f"Tevkifat {donem}", ["Taraf", "Kod", "Oran", "Açıklama", "Belge Sayısı", "Tevkifata Tabi Tutar",
                                        "Hesaplanan KDV", "Tevkifat"], satirlar, f"tevkifat-{yil}{'-%02d' % ay if ay else ''}",
                  {baslik}, dipnot=MALI_UYARI)


# --- Stopaj ------------------------------------------------------------------

def stopaj_veri(db: Session, k: Kullanici, yil: int, ay: int = 0) -> dict:
    """Dönemdeki stopajlı onaylı faturalar, orana göre. Alışta stopajı biz keseriz (muhtasar ile vergi dairesine öderiz);
    satışta alıcı keser, bizim adımıza öder (mahsup edilir)."""
    from .. import kural
    bas, son = (date(yil, ay, 1), date(yil + (ay == 12), ay % 12 + 1, 1)) if ay else (date(yil, 1, 1), date(yil + 1, 1, 1))
    q = select(Fatura).where(Fatura.sirket_id == k.sirket_id, Fatura.durum == "onayli", Fatura.tarih >= bas, Fatura.tarih < son,
                             Fatura.stopaj != 0).order_by(Fatura.tarih, Fatura.id)
    gruplar: dict[tuple, dict] = {}
    faturalar = []
    for f in db.scalars(q):
        yon = "satis" if f.yon == "giden" else "alis"
        c = tl_kur(f)
        parcalar = [(float(kl.stopaj_orani), c * float(kl.tutar), c * kural.stopaj_tutari(kl.tutar, kl.stopaj_orani))
                    for kl in f.kalemler if float(kl.stopaj_orani or 0)] or [(0.0, c * float(f.ara_toplam), c * float(f.stopaj))]
        for oran, matrah, tutar in parcalar:
            g = gruplar.setdefault((yon, oran), {"yon": yon, "oran": f"%{oran:g}" if oran else "-", "belge_sayisi": 0,
                                                 "matrah": 0.0, "stopaj": 0.0, "_faturalar": set()})
            g["_faturalar"].add(f.id)
            g["matrah"] += matrah
            g["stopaj"] += tutar
        faturalar.append({"id": f.id, "yon": yon, "tarih": f.tarih.isoformat(), "fatura_no": f.fatura_no,
                          "cari": f.cari.unvan if f.cari else None, "vkn": f.cari.vkn if f.cari else None,
                          "oran": ", ".join(sorted({f"%{p[0]:g}" for p in parcalar if p[0]})) or None,
                          "matrah": round(sum(p[1] for p in parcalar), 2), "stopaj": round(c * float(f.stopaj), 2),
                          "odenecek": round(c * float(f.genel_toplam), 2)})
    sonuc = {"yil": yil, "ay": ay, "alis": [], "satis": [], "faturalar": faturalar}
    for (yon, _), g in sorted(gruplar.items(), key=lambda x: x[0][1]):
        g["belge_sayisi"] = len(g.pop("_faturalar"))
        g["matrah"], g["stopaj"] = round(g["matrah"], 2), round(g["stopaj"], 2)
        sonuc[yon].append(g)
    sonuc["alis_stopaj"] = round(sum(g["stopaj"] for g in sonuc["alis"]), 2)
    sonuc["satis_stopaj"] = round(sum(g["stopaj"] for g in sonuc["satis"]), 2)
    return sonuc


@router.get("/raporlar/stopaj")
def stopaj_raporu(yil: int, ay: int = 0, db: Session = Depends(get_db), k: Kullanici = Depends(aktif_kullanici)):
    return stopaj_veri(db, k, yil, ay)


@router.get("/excel/stopaj")
def excel_stopaj(yil: int, ay: int = 0, db: Session = Depends(get_db), k: Kullanici = Depends(aktif_kullanici)):
    v = stopaj_veri(db, k, yil, ay)
    donem = f"{ay:02d}-{yil}" if ay else str(yil)
    satirlar = [[("Alış (biz keseriz, muhtasar ile öderiz)" if g["yon"] == "alis" else "Satış (alıcı keser)"), g["oran"],
                 g["belge_sayisi"], g["matrah"], g["stopaj"]] for y in ("alis", "satis") for g in v[y]]
    satirlar.append([None] * 9)
    baslik = len(satirlar)
    satirlar.append(["Fatura", "Tarih", "Fatura No", "Cari", "VKN", "Oran", "KDV Hariç", "Stopaj", "Ödenecek"])
    satirlar += [["Alış" if f["yon"] == "alis" else "Satış", f["tarih"], f["fatura_no"], f["cari"], f["vkn"], f["oran"],
                  f["matrah"], f["stopaj"], f["odenecek"]] for f in v["faturalar"]]
    return _excel(f"Stopaj {donem}", ["Taraf", "Oran", "Belge Sayısı", "Stopaja Tabi Tutar", "Stopaj"], satirlar,
                  f"stopaj-{yil}{'-%02d' % ay if ay else ''}", {baslik}, dipnot=MALI_UYARI)


# --- Ba-Bs -----------------------------------------------------------------

def babs_veri(db: Session, k: Kullanici, yil: int, ay: int, limit: float = 5000) -> dict:
    """Form Ba (alışlar) ve Form Bs (satışlar): aynı kişiden ay içinde KDV hariç limit ve üzeri belgeler."""
    q = select(Fatura).where(Fatura.sirket_id == k.sirket_id, Fatura.durum == "onayli")
    son = date(yil + (ay == 12), ay % 12 + 1, 1)
    toplam: dict[tuple, dict] = {}
    for f in db.scalars(q.where(Fatura.tarih >= date(yil, ay, 1), Fatura.tarih < son)):
        anahtar = ("bs" if f.yon == "giden" else "ba", f.cari_id)
        t = toplam.setdefault(anahtar, {"cari_id": f.cari_id, "unvan": f.cari.unvan if f.cari else "(carisiz)",
                                         "vkn": f.cari.vkn if f.cari else None, "belge_sayisi": 0, "tutar": 0.0})
        t["belge_sayisi"] += 1
        t["tutar"] += float(f.ara_toplam) * tl_kur(f)
    # 565 Sıra No'lu VUK Genel Tebliği: Eylül 2024 ve sonrası dönemler için Ba-Bs bildirimi verilmez.
    sonuc = {"ba": [], "bs": [], "limit": limit, "kaldirildi": (yil, ay) >= (2024, 9)}
    for (form, _), t in toplam.items():
        t["tutar"] = round(t["tutar"], 2)
        if t["tutar"] >= limit:
            sonuc[form].append(t)
    for form in ("ba", "bs"):
        sonuc[form].sort(key=lambda t: -t["tutar"])
    return sonuc


@router.get("/raporlar/ba-bs")
def babs(yil: int, ay: int, limit: float = 5000, db: Session = Depends(get_db), k: Kullanici = Depends(aktif_kullanici)):
    return babs_veri(db, k, yil, ay, limit)


@router.get("/excel/ba-bs")
def excel_babs(yil: int, ay: int, limit: float = 5000, db: Session = Depends(get_db), k: Kullanici = Depends(aktif_kullanici)):
    v = babs_veri(db, k, yil, ay, limit)
    satirlar = [[ad, t["unvan"], t["vkn"], t["belge_sayisi"], t["tutar"]]
                for form, ad in (("ba", "Form Ba (alış)"), ("bs", "Form Bs (satış)")) for t in v[form]]
    return _excel(f"Ba-Bs {ay:02d}-{yil}", ["Form", "Ünvan", "VKN/TCKN", "Belge Sayısı", "KDV Hariç Tutar"], satirlar,
                  f"ba-bs-{yil}-{ay:02d}", dipnot=MALI_UYARI + (" " + BABS_KALDIRILDI if v["kaldirildi"] else ""))


# --- Gelir-gider -------------------------------------------------------------

def gelir_gider_veri(db: Session, k: Kullanici, yil: int) -> dict:
    """Aylık KDV hariç satışlar, gider türüne göre alışlar ve doğrudan masraflar; net sonuç."""
    gelir = [0.0] * 12
    gider: dict[str, list[float]] = defaultdict(lambda: [0.0] * 12)
    for f in _yil_faturalari(db, k, yil):
        i = f.tarih.month - 1
        c = isaret(f) * tl_kur(f)  # TL karşılığı; iade faturası ilgili tarafı azaltır
        if satis_tarafi(f):
            gelir[i] += c * float(f.ara_toplam)
        else:
            # Gider: KDV hariç tutar + indirilemeyen diğer vergiler (ÖİV, konaklama vergisi…)
            gider[f.gider_turu or "Belirtilmemiş"][i] += c * (float(f.ara_toplam) + float(f.diger_vergiler or 0))
    for h in db.scalars(select(Hareket).where(Hareket.sirket_id == k.sirket_id, Hareket.durum == "onayli",
                                              Hareket.tur == "masraf", Hareket.tarih >= date(yil, 1, 1),
                                              Hareket.tarih <= date(yil, 12, 31))):
        gider[h.gider_turu or "Belirtilmemiş"][h.tarih.month - 1] += float(h.tutar)
    gider_satir = [{"tur": t, "aylar": [round(x, 2) for x in v], "toplam": round(sum(v), 2)}
                   for t, v in sorted(gider.items(), key=lambda x: -sum(x[1]))]
    gider_toplam = [round(sum(g["aylar"][i] for g in gider_satir), 2) for i in range(12)]
    return {"yil": yil, "aylar": AYLAR, "gelir": [round(x, 2) for x in gelir], "gider": gider_satir,
            "gider_toplam": gider_toplam, "net": [round(gelir[i] - gider_toplam[i], 2) for i in range(12)]}


@router.get("/raporlar/gelir-gider")
def gelir_gider(yil: int, db: Session = Depends(get_db), k: Kullanici = Depends(aktif_kullanici)):
    return gelir_gider_veri(db, k, yil)


@router.get("/excel/gelir-gider")
def excel_gelir_gider(yil: int, db: Session = Depends(get_db), k: Kullanici = Depends(aktif_kullanici)):
    v = gelir_gider_veri(db, k, yil)
    satirlar = [["SATIŞLAR (KDV hariç)", *v["gelir"], round(sum(v["gelir"]), 2)]]
    satirlar += [[f"  {g['tur']}", *g["aylar"], g["toplam"]] for g in v["gider"]]
    satirlar += [["GİDERLER TOPLAMI", *v["gider_toplam"], round(sum(v["gider_toplam"]), 2)],
                 ["NET (gelir - gider)", *v["net"], round(sum(v["net"]), 2)]]
    kalin = {0, len(satirlar) - 2, len(satirlar) - 1}
    return _excel(f"Gelir-Gider {yil}", ["Kalem", *AYLAR, "Yıl Toplamı"], satirlar, f"gelir-gider-{yil}", kalin, dipnot=MALI_UYARI)


# --- Yaşlandırma -------------------------------------------------------------

DILIMLER = [("vadesi_gelmemis", "Vadesi gelmemiş"), ("g0_30", "0-30 gün"), ("g31_60", "31-60 gün"),
            ("g61_90", "61-90 gün"), ("g90", "90+ gün")]


def _dilim(gecen: int) -> str:
    if gecen < 0:
        return "vadesi_gelmemis"
    return "g0_30" if gecen <= 30 else "g31_60" if gecen <= 60 else "g61_90" if gecen <= 90 else "g90"


def yaslandirma_veri(db: Session, k: Kullanici, tarih: date | None = None) -> dict:
    """Açık bakiyeyi faturalara ilk giren ilk çıkar (FIFO) mantığıyla dağıtır: ödemeler en eski faturayı kapatır,
    kapanmayan fatura tutarları vadesinden (yoksa tarihinden) bu yana geçen güne göre dilimlere ayrılır."""
    tarih = tarih or date.today()
    vadeler = {f.id: fatura_vadesi(f) for f in db.scalars(select(Fatura).where(
        Fatura.sirket_id == k.sirket_id, Fatura.durum == "onayli"))}
    satirlar: dict[int, list[dict]] = defaultdict(list)
    for s in cari_hareketleri(db, k.sirket_id):
        if s["tarih"] is None or s["tarih"] <= tarih:
            satirlar[s["cari_id"]].append(s)
    unvanlar = {c.id: (c.unvan, c.vkn) for c in db.scalars(select(Cari).where(Cari.sirket_id == k.sirket_id))}
    sonuc = {"alacak": [], "borc": [], "tarih": tarih, "dilimler": DILIMLER, "acik_faturalar": []}
    for cari_id, dizi in satirlar.items():
        bakiye = round(sum(s["borc"] - s["alacak"] for s in dizi), 2)
        if abs(bakiye) < 0.01:
            continue
        alacakli = bakiye > 0  # cari bize borçlu
        acan = sorted((s for s in dizi if (s["borc"] if alacakli else s["alacak"]) > 0),
                      key=lambda s: (s["tarih"] or date.min, s["sira"]), reverse=True)
        kalan = abs(bakiye)
        satir = {"cari_id": cari_id, "unvan": unvanlar.get(cari_id, ("?", None))[0], "vkn": unvanlar.get(cari_id, ("?", None))[1],
                 "bakiye": round(abs(bakiye), 2), **{d: 0.0 for d, _ in DILIMLER}, "en_eski": None}
        # En yeni belgeden geriye doğru: açık bakiye son faturalardan oluşur.
        for s in acan:
            if kalan <= 0.005:
                break
            pay = min(kalan, s["borc"] if alacakli else s["alacak"])
            kalan -= pay
            vade = vadeler.get(s["fatura_id"]) or s["tarih"] or tarih
            gecen = (tarih - vade).days
            satir[_dilim(gecen)] += pay
            satir["en_eski"] = vade
            if s["fatura_id"]:
                sonuc["acik_faturalar"].append({"cari_id": cari_id, "unvan": satir["unvan"], "fatura_id": s["fatura_id"],
                                                "belge": s["belge"], "tarih": s["tarih"], "vade": vade, "gecen_gun": gecen,
                                                "acik_tutar": round(pay, 2), "tur": "alacak" if alacakli else "borc"})
        if kalan > 0.005:  # faturaya bağlanamayan açılış bakiyesi vb.
            satir["g90"] += kalan
        for d, _ in DILIMLER:
            satir[d] = round(satir[d], 2)
        sonuc["alacak" if alacakli else "borc"].append(satir)
    for t in ("alacak", "borc"):
        sonuc[t].sort(key=lambda r: -r["bakiye"])
    sonuc["acik_faturalar"].sort(key=lambda r: -r["gecen_gun"])
    return sonuc


@router.get("/raporlar/yaslandirma")
def yaslandirma(tarih: date | None = None, db: Session = Depends(get_db), k: Kullanici = Depends(aktif_kullanici)):
    return yaslandirma_veri(db, k, tarih)


@router.get("/excel/yaslandirma")
def excel_yaslandirma(tarih: date | None = None, db: Session = Depends(get_db), k: Kullanici = Depends(aktif_kullanici)):
    v = yaslandirma_veri(db, k, tarih)
    satirlar = [["Alacak (cari bize borçlu)" if t == "alacak" else "Borç (biz cariye borçluyuz)", r["unvan"], r["vkn"],
                 r["bakiye"], *[r[d] for d, _ in DILIMLER], r["en_eski"]] for t in ("alacak", "borc") for r in v[t]]
    return _excel("Yaşlandırma", ["Tür", "Cari", "VKN", "Açık Bakiye", *[a for _, a in DILIMLER], "En Eski Açık Vade"],
                  satirlar, f"yaslandirma-{v['tarih']}")
