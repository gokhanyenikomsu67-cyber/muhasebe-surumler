"""Eski sürümün yanlış okuduğu kayıtları yeni okuyucuyla düzeltir (bir kez, program açılırken).

- Adı etiket/adres olarak açılmış ("Ticaret Sicil No", "ANKARA Öveçler") ya da bizim VKN'mizi taşıyan cariler,
  bağlı faturalarının PDF'i yeniden okunarak düzeltilir.
- Kalemleri tek satıra toplanmış taslak faturalar yeniden okunur; kalemler artık çıkıyorsa yerine yazılır.
- Eski sürümün farkı kapatmak için uydurduğu "KDV'siz / istisna tutar" satırlı taslaklar yeniden okunur.
- Kalemleri geçici satırda kalmış, KDV'si ya da toplamı faturadakini tutmayan onaylı faturalar kaydedilmiş belgeden
  (XML/PDF) yeniden okunur; okuma tam ve kendi içinde tutarlıysa kalemler belgedekiyle değiştirilir (şantiye, durum ve
  cari kalır). Okunamayanlara dokunulmaz; Genel Durum'da kırmızı listelenir (tani.onayli_sorunlari).
- Okuma Hata Raporu'nda sorunlu çıkan taslaklar (kalem/tutar/firma) yeni sürümle yeniden okunur; yeni okuma kendi
  içinde tutarlıysa yazılır, yanlış açılmış ve artık hiçbir kayda bağlı olmayan otomatik cari silinir.
- Aynı adla iki kez açılmış şantiye ve cariler birleştirilir (tekrarlari_birlestir).
- Firma bilgisinde VKN'miz yazılmamışsa faturalardan öğrenilir (kendi_vkn_ogren); dövizli taslakların kuru belgeden
  yazılır, kalem adlarındaki süs işaretleri ("## ... ##") temizlenir.
Kullanıcının kendi verdiği adlara dokunulmaz. Düzeltilemeyenler raporda listelenir.
"""
import json
import re

from sqlalchemy import select

from . import kural, schemas
from .db import VERI_KLASORU, SessionLocal
from .models import Cari, Fatura, Sirket

SURUM = 15
UYDURMA_SATIR = "KDV'siz / istisna tutar"  # eski sürüm toplam farkını bu satırla kapatıyordu
RAPOR = VERI_KLASORU / "onarim-raporu.json"


def _vkn(x) -> str:
    return re.sub(r"\D", "", str(x or ""))


def _pdf_oku(f: Fatura, sirket: Sirket, resimle: bool = False) -> dict | None:
    from .routers.faturalar import DOSYA_KLASORU
    if not (f.kaynak_dosya or "").endswith(".pdf"):
        return None
    try:
        from . import ocr
        veri = (DOSYA_KLASORU / f.kaynak_dosya).read_bytes()
        okunan = kural.pdf_fatura_oku(veri, [], sirket.unvan, sirket.vkn, f.yon)
        # Sorunlu taslakta kalemler yazıdan okunamazsa sayfa resminden de denenir (yavaş, yalnız orada)
        return ocr.pdf_kalemlerini_tamamla(okunan, veri, [], sirket.unvan, sirket.vkn, f.yon) if resimle else okunan
    except Exception:  # noqa: BLE001  okunamayan belge onarımı durdurmasın
        return None


def _belge_oku(f: Fatura, sirket: Sirket, resimle: bool = False) -> dict | None:
    from .routers.faturalar import DOSYA_KLASORU
    if f.xml_dosya:
        try:
            return kural.efatura_xml_oku((DOSYA_KLASORU / f.xml_dosya).read_bytes())
        except (OSError, kural.KuralHatasi):
            pass
    return _pdf_oku(f, sirket, resimle)


def kendi_vkn_ogren(db, sirket: Sirket) -> str | None:
    """Firma bilgisinde VKN yazılmamışsa faturalardan öğrenilir: alış faturalarının alıcısı (karekodda "avkntckn") hep
    biziz. Bir VKN en az 3 faturada ve alıcı VKN'si okunan alış faturalarının yarısından fazlasında alıcıysa bizimdir.
    Kendi VKN'miz bilinmezse satıcı yerine kendi firmamız cari olarak açılabiliyordu."""
    if _vkn(sirket.vkn):
        return sirket.vkn
    from collections import Counter
    sayac, toplam = Counter(), 0
    for (o,) in db.execute(select(Fatura.ai_okuma).where(Fatura.sirket_id == sirket.id, Fatura.yon == "gelen")):
        o = o or {}
        v = _vkn((o.get("karekod") or {}).get("avkntckn")) or _vkn((o.get("alici") or {}).get("vkn"))
        if len(v) in (10, 11):
            sayac[v] += 1
            toplam += 1
    if not sayac:
        return None
    vkn, adet = sayac.most_common(1)[0]
    if adet >= 3 and adet * 2 > toplam:
        sirket.vkn = vkn
        db.flush()
        return vkn
    return None


def cari_sorunu(c: Cari, sirket: Sirket) -> str | None:
    if c.vkn and c.unvan == f"VKN {c.vkn}":
        return "adı faturada yazmıyor; adını yazın"
    if _vkn(sirket.vkn) and _vkn(c.vkn) == _vkn(sirket.vkn):
        return "VKN'si firmamızın VKN'si"
    if not c.vkn and kural.kendi_unvani_mi(c.unvan, sirket.unvan):
        return "firmamızın kendi adı"
    if kural.kotu_unvan(c.unvan):
        return "adı etiket ya da adres gibi görünüyor"
    return None


def tekrarlari_birlestir(db, sirket: Sirket) -> tuple[list[str], list[str]]:
    """Aynı adla iki kez açılmış şantiye ve cariler (harf/Türkçe karakter/nokta farkı yok sayılır) ilk açılanda
    birleşir; faturalar, kalemler, çekler ve banka hareketleri ona taşınır. VKN'leri farklı cariler ayrı firmadır."""
    from sqlalchemy import update

    from .models import Cek, Depo, FaturaKalem, Hareket, Santiye, TaseronGider
    santiye, cari = [], []
    ilk: dict[str, Santiye] = {}
    for st in db.scalars(select(Santiye).where(Santiye.sirket_id == sirket.id).order_by(Santiye.id)).all():
        a = kural.ad_anahtari(st.ad)
        if not a or a not in ilk:
            ilk.setdefault(a, st)
            continue
        kalan = ilk[a]
        for m in (Fatura, FaturaKalem, Cek, Hareket, Depo, TaseronGider):
            db.execute(update(m).where(m.santiye_id == st.id).values(santiye_id=kalan.id))
        for alan in ("adres", "baslangic", "bitis", "butce"):
            if getattr(kalan, alan) is None:
                setattr(kalan, alan, getattr(st, alan))
        db.delete(st)
        santiye.append(kalan.ad)
    gruplar: dict[str, list[Cari]] = {}
    for c in db.scalars(select(Cari).where(Cari.sirket_id == sirket.id).order_by(Cari.id)).all():
        a = kural.ad_anahtari(c.unvan)
        kalan = next((x for x in gruplar.get(a, []) if not (c.vkn and x.vkn and _vkn(c.vkn) != _vkn(x.vkn))), None) if a else None
        if kalan is None:
            gruplar.setdefault(a, []).append(c)
            continue
        for m, alan in ((Fatura, "cari_id"), (Cek, "cari_id"), (Cek, "ciro_cari_id"), (Hareket, "cari_id"),
                        (Depo, "cari_id"), (TaseronGider, "cari_id")):
            db.execute(update(m).where(getattr(m, alan) == c.id).values({alan: kalan.id}))
        for alan in ("vkn", "vergi_dairesi", "adres", "telefon", "eposta", "iban"):
            if not getattr(kalan, alan):
                setattr(kalan, alan, getattr(c, alan))
        if kalan.tur != c.tur:
            kalan.tur = "her_ikisi"
        db.delete(c)
        cari.append(kalan.unvan)
    db.flush()
    db.expire_all()
    return santiye, cari


def ekstre_bilgilerini_tazele(db, sirket: Sirket) -> list[str]:
    """Eski sürümde hareketleri silinen hesapta ekstre bakiyesi/tarihi kalıyor, sahte mutabakat farkı çıkıyordu.
    Açılış bakiyesi ilk ekstre satırından geldiyse işaretlenir; ekstre bilgisi kalan satırlardan yeniden kurulur."""
    from .models import BankaHesabi, Hareket
    from .routers.banka import ekstre_tazele
    temizlenen = []
    for b in db.scalars(select(BankaHesabi).where(BankaHesabi.sirket_id == sirket.id, BankaHesabi.ekstre_tarihi.is_not(None))).all():
        ilk = next((h for h in db.scalars(select(Hareket).where(Hareket.banka_hesap_id == b.id, Hareket.ekstre_anahtari.is_not(None))
                                          .order_by(Hareket.tarih, Hareket.id))
                    if (h.ai_okuma or {}).get("bakiye") is not None), None)
        if ilk is None:
            b.acilis_ekstreden = True  # açılış bakiyesi ekstreden gelmişti; ekstre satırı kalmadı
            temizlenen.append(b.ad)
        else:
            isaretli = float(ilk.tutar) if ilk.yon == "giris" else -float(ilk.tutar)
            b.acilis_ekstreden = abs(float(b.acilis_bakiyesi or 0) - (float(ilk.ai_okuma["bakiye"]) - isaretli)) < 0.005
        ekstre_tazele(db, b)
    db.flush()
    return temizlenen


def carileri_duzelt(db, sirket: Sirket, eski_surum: int = SURUM, yalniz_sorunlu: bool = False) -> tuple[list[str], list[dict]]:
    """Bizim VKN'mizle / adımızla ya da etiket/adres adıyla açılmış cariler bağlı faturaların belgesinden düzelir.
    yalniz_sorunlu: yalnız cari_sorunu olanlar (fatura okunurken VKN'miz yeni öğrenildiğinde)."""
    duzelen_cari, kalan_cari = [], []
    for c in db.scalars(select(Cari).where(Cari.sirket_id == sirket.id)).all():
        sorun = cari_sorunu(c, sirket)
        suphe = sorun or (not yalniz_sorunlu and (eski_surum < 12 or c.ad_otomatik)
                          and c.unvan and not kural.SIRKET_EKLERI.search(kural.sade(c.unvan)))  # "ANKARA Öveçler" olabilir
        if not suphe:
            continue
        eski = f"{c.unvan} · {c.vkn or '-'}"
        kendi = (bool(_vkn(sirket.vkn)) and _vkn(c.vkn) == _vkn(sirket.vkn)) or (not c.vkn and kural.kendi_unvani_mi(c.unvan, sirket.unvan))
        if yalniz_sorunlu and not kendi:
            continue
        if kendi:
            c.vkn = None
        for f in db.scalars(select(Fatura).where(Fatura.cari_id == c.id)).all():
            okunan = _pdf_oku(f, sirket)
            if kendi and okunan is not None:
                from .routers.faturalar import DOSYA_KLASORU, karsi_tarafi_karekoddan
                try:
                    okunan = karsi_tarafi_karekoddan(okunan, (DOSYA_KLASORU / f.kaynak_dosya).read_bytes(), sirket, f.yon)
                except OSError:
                    pass
            karsi = (okunan or {}).get("satici" if f.yon == "gelen" else "alici") or {}
            vkn = _vkn(karsi.get("vkn"))
            if not vkn or vkn == _vkn(sirket.vkn):
                if kendi:
                    f.cari = None  # karşı firma okunamadı: kendi firmamıza bağlı kalmaz, fatura "firma okunamadı" görünür
                continue
            if c.vkn and vkn != c.vkn:
                if kendi:  # bizim VKN'mizle açılmış cariye başka firmaların faturaları da bağlanmış: her biri kendi carisine
                    from types import SimpleNamespace

                    from .routers.faturalar import cari_bul_ya_ac
                    yeni, _ = cari_bul_ya_ac(db, SimpleNamespace(sirket_id=sirket.id), karsi,
                                             "tedarikci" if f.yon == "gelen" else "musteri")
                    if yeni is not None and yeni is not c:
                        f.cari = yeni
                continue
            if not c.vkn and not db.scalar(select(Cari.id).where(Cari.sirket_id == sirket.id, Cari.vkn == vkn, Cari.id != c.id)):
                c.vkn = vkn
                if kendi and karsi.get("unvan") and not kural.kotu_unvan(karsi["unvan"]):
                    c.unvan = karsi["unvan"].strip()  # cari bu firmanınmış; eski ad bizim faturamızdan karışmıştı
            if kural.daha_iyi_unvan(c.unvan, karsi.get("unvan")):
                c.unvan = karsi["unvan"].strip()
            if not kendi:
                break
        if kendi:
            db.flush()
            from .models import Cek, Hareket
            if not any(db.scalar(select(m.id).where(m.cari_id == c.id).limit(1)) for m in (Fatura, Cek, Hareket)) \
                    and not db.scalar(select(Cek.id).where(Cek.ciro_cari_id == c.id).limit(1)) and kural.kendi_unvani_mi(c.unvan, sirket.unvan):
                db.delete(c)  # kendi firmamız adına açılmış, artık hiçbir kayda bağlı olmayan cari
                db.flush()
                duzelen_cari.append(f"{eski} silindi")
                continue
        if f"{c.unvan} · {c.vkn or '-'}" != eski:
            duzelen_cari.append(f"{eski} → {c.unvan} · {c.vkn or '-'}")
        if cari_sorunu(c, sirket):
            kalan_cari.append({"id": c.id, "unvan": c.unvan, "neden": cari_sorunu(c, sirket)})
        db.commit()  # belge okuması uzun sürer: kayıtlar arada kilitli kalmasın
    return duzelen_cari, kalan_cari


def onar(db, sirket: Sirket, eski_surum: int = 0) -> dict:
    """eski_surum: bu veritabanında daha önce çalışmış onarımın sürümü. Şirket eki taşımayan adlı carilerin
    ("ANKARA Öveçler") belgeden düzeltilmesi yalnız ilk onarımda yapılır; sonrakilerde kullanıcının verdiği ad ve
    bilerek boş bıraktığı VKN değişmez (yalnız otomatik açılan ya da sorunlu cariler düzelir)."""
    from .routers.faturalar import kalem_giris, kalemleri_yaz
    ogrenilen_vkn = None if _vkn(sirket.vkn) else kendi_vkn_ogren(db, sirket)
    db.commit()
    ekstresi_temizlenen = ekstre_bilgilerini_tazele(db, sirket)
    birlesen_santiye, birlesen_cari = tekrarlari_birlestir(db, sirket)
    db.commit()
    duzelen_fatura = []
    duzelen_cari, kalan_cari = carileri_duzelt(db, sirket, eski_surum)

    for f in db.scalars(select(Fatura).where(Fatura.sirket_id == sirket.id)).all():
        uydurma = any(k.aciklama == UYDURMA_SATIR for k in f.kalemler)
        if not uydurma and not any("ayrıştırılamadı" in (k.aciklama or "") for k in f.kalemler):
            continue
        if f.durum != "taslak":
            continue
        okunan = _pdf_oku(f, sirket)
        if not okunan:
            continue
        # Yeni sürüm de okuyamıyorsa geçici satır silinir (kullanıcı kuralı); fatura kırmızı kalır, kalemler elle girilir.
        f.tevkifat, f.diger_vergiler, f.stopaj = okunan.get("tevkifat") or 0, okunan.get("diger_vergiler") or 0, okunan.get("stopaj") or 0
        f.yuvarlama, f.aciklama = okunan.get("yuvarlama") or 0, f.aciklama or okunan.get("aciklama")
        santiye = next((k.santiye_id for k in f.kalemler if k.santiye_id), None)
        kalemleri_yaz(f, [kalem_giris(k, santiye) for k in okunan["kalemler"]])
        eski = f.ai_okuma or {}
        f.ai_okuma = {**eski, **okunan, "uyarilar": [u for u in eski.get("uyarilar", []) if "ayrıştırılamadı" not in u
                                                     and "geçici satır" not in u]
                      + (["Kalemler tek tek okunamadı; faturadaki kalemleri girin."] if okunan.get("kalemler_okunamadi") else []),
                      "bilgi": eski.get("bilgi", []) + ["Kalemler programın yeni sürümüyle yeniden okundu."]}
        duzelen_fatura.append(f.fatura_no or str(f.id))
        db.commit()
    # Faturada satır KDV'si oran x tutardan farklı yazılmışsa (Öztaş) eski sürüm KDV'yi yeniden hesaplıyordu.
    kdv_fatura = []
    for f in db.scalars(select(Fatura).where(Fatura.sirket_id == sirket.id)).all():
        okuma = f.ai_okuma or {}
        if okuma.get("kdv_toplam") is None or abs(float(f.kdv_toplam) - okuma["kdv_toplam"]) <= 0.05:
            continue
        if f.durum != "taslak":
            continue
        satirlar = ((_belge_oku(f, sirket) or {}).get("kalemler")) or []
        if len(satirlar) != len(f.kalemler) or not any(x.get("kdv_tutari") is not None for x in satirlar):
            continue
        kalemleri_yaz(f, [schemas.KalemGiris(
            aciklama=kl.aciklama, miktar=float(kl.miktar), birim=kl.birim, birim_fiyat=float(kl.birim_fiyat),
            kdv_orani=float(kl.kdv_orani), tutar=float(kl.tutar), santiye_id=kl.santiye_id, depo_id=kl.depo_id, tevkifat_orani=float(kl.tevkifat_orani or 0),
            tevkifat_kodu=kl.tevkifat_kodu, stopaj_orani=float(kl.stopaj_orani or 0), kdv_tutari=x.get("kdv_tutari"), iskonto_orani=float(kl.iskonto_orani or 0),
            iskonto_tutari=float(kl.iskonto_tutari or 0)) for kl, x in zip(f.kalemler, satirlar)])
        kdv_fatura.append(f.fatura_no or str(f.id))
        db.commit()
    tevkifat_fatura = []
    for f in db.scalars(select(Fatura).where(Fatura.sirket_id == sirket.id, Fatura.tevkifat != 0)).all():
        # Tevkifatı yalnız fatura toplamında olan eski kayıtlar: oran ve kod belgeden okunup kalemlere yazılır.
        # Tutarlar değişmez; okunan satır tevkifatı faturadakini tutmuyorsa dokunulmaz.
        if any(float(kl.tevkifat_orani or 0) for kl in f.kalemler):
            continue
        okunan = _belge_oku(f, sirket)
        satirlar = (okunan or {}).get("kalemler") or []
        if len(satirlar) != len(f.kalemler) or not any(x.get("tevkifat_orani") for x in satirlar):
            continue
        if abs(sum(kural.tevkifat_tutari(kl.tutar, kl.kdv_orani, x.get("tevkifat_orani"), kl.kdv_tutari) for kl, x in zip(f.kalemler, satirlar))
               - float(f.tevkifat)) > 0.02 * len(satirlar):
            continue
        for kl, x in zip(f.kalemler, satirlar):
            kl.tevkifat_orani, kl.tevkifat_kodu = x.get("tevkifat_orani") or 0, x.get("tevkifat_kodu")
        tevkifat_fatura.append(f.fatura_no or str(f.id))
        db.commit()
    # Eski kayıtlarda iskonto açıklamaya yazılıyordu ("(İsk. %60, liste fiyatı 1.600)"): standart sütunlara taşınır.
    # Tutar ve fatura toplamları değişmez; birim fiyat liste fiyatı olur.
    iskonto_kalem = 0
    for f in db.scalars(select(Fatura).where(Fatura.sirket_id == sirket.id)).all():
        for kl in f.kalemler:
            if "(İsk. " not in (kl.aciklama or "") or float(kl.iskonto_tutari or 0):
                continue
            x = kural.iskontoyu_ayir({"aciklama": kl.aciklama, "miktar": float(kl.miktar), "birim_fiyat": float(kl.birim_fiyat),
                                      "tutar": float(kl.tutar)})
            if x["aciklama"] == kl.aciklama:
                continue
            kl.aciklama, kl.birim_fiyat = x["aciklama"], x["birim_fiyat"]
            kl.iskonto_orani, kl.iskonto_tutari = x["iskonto_orani"], x["iskonto_tutari"]
            iskonto_kalem += 1
    db.commit()
    kur_yazilan, sus_temizlenen = _kur_ve_adlar(db, sirket)
    yonu_duzelen = _yonu_duzelt(db, sirket)
    yeniden = _sorunlu_taslaklari_oku(db, sirket)
    onayli, tutari_degisen = _sorunlu_onaylilari_oku(db, sirket)
    db.commit()
    return {"ekstre_bilgisi_temizlenen_hesaplar": ekstresi_temizlenen, "birlesen_santiyeler": birlesen_santiye, "birlesen_cariler": birlesen_cari, "yeniden_okunan_taslaklar": yeniden, "yeniden_okunan_onaylilar": onayli, "tutari_degisen_onaylilar": tutari_degisen, "duzelen_cariler": duzelen_cari, "kontrol_edilecek_cariler": kalan_cari, "kalemleri_okunan_faturalar": duzelen_fatura,
            "tevkifati_kalemlere_yazilan": tevkifat_fatura, "satisa_alinan_taslaklar": yonu_duzelen,
            "kdv_tutari_duzeltilen": kdv_fatura, "iskontosu_sutuna_tasinan_kalem": iskonto_kalem,
            "ogrenilen_kendi_vkn": ogrenilen_vkn, "kuru_yazilan_faturalar": kur_yazilan, "adi_temizlenen_kalem": sus_temizlenen}


def _kur_ve_adlar(db, sirket: Sirket) -> tuple[list[str], int]:
    """Dövizli taslakta kur boşsa önce okunan bilgiden, yoksa belgeden yazılır (faturada kur ya da TL toplamı varsa).
    Taslak kalem adlarındaki süs işaretleri ("## RACK KABİNET ##") temizlenir."""
    kur_yazilan, sus = [], 0
    for f in db.scalars(select(Fatura).where(Fatura.sirket_id == sirket.id, Fatura.durum == "taslak")).all():
        if (f.para_birimi or "TRY") not in ("TRY", "TL") and not float(f.kur or 0):
            kur = (f.ai_okuma or {}).get("kur")
            if not (isinstance(kur, (int, float)) and kur > 0):
                kur = (_belge_oku(f, sirket) or {}).get("kur")
            if isinstance(kur, (int, float)) and kur > 0:
                f.kur = kur
                f.ai_okuma = {**(f.ai_okuma or {}), "kur": kur, "uyarilar": [
                    u for u in (f.ai_okuma or {}).get("uyarilar", []) if "kuru girin" not in u and "kur girilmemiş" not in u]}
                kur_yazilan.append(f.fatura_no or str(f.id))
        for kl in f.kalemler:
            temiz = kural.susu_temizle({"aciklama": kl.aciklama})["aciklama"]
            if temiz != kl.aciklama:
                kl.aciklama = temiz
                sus += 1
        db.commit()
    return kur_yazilan, sus


def _yonu_duzelt(db, sirket: Sirket) -> list[str]:
    """Satış faturası alış olarak (ya da tersi) okunmuş taslaklar: PDF'te satıcı VKN'si bizimse satışa alınır, belge doğru
    yönle yeniden okunur ve cari karşı firmayla düzeltilir. Onaylı faturalara dokunulmaz."""
    from types import SimpleNamespace

    from .routers.faturalar import DOSYA_KLASORU, cari_bul_ya_ac, kalem_giris, kalemleri_yaz, notlari_ayir, toplam_farki
    duzelen = []
    for f in db.scalars(select(Fatura).where(Fatura.sirket_id == sirket.id, Fatura.durum == "taslak")).all():
        if f.xml_dosya or not (f.kaynak_dosya or "").endswith(".pdf"):
            continue
        try:
            dogru = kural.pdf_yonu((DOSYA_KLASORU / f.kaynak_dosya).read_bytes(), sirket.vkn)
        except OSError:
            continue
        if not dogru or dogru == f.yon:
            continue
        f.yon = dogru
        okunan = _pdf_oku(f, sirket)
        if not okunan:
            continue
        karsi = okunan.get("satici" if dogru == "gelen" else "alici") or {}
        c, _ = cari_bul_ya_ac(db, SimpleNamespace(sirket_id=sirket.id), karsi, "tedarikci" if dogru == "gelen" else "musteri")
        f.cari = c
        f.fatura_no = f.fatura_no or okunan.get("fatura_no")
        f.tevkifat, f.diger_vergiler, f.stopaj = okunan.get("tevkifat") or 0, okunan.get("diger_vergiler") or 0, okunan.get("stopaj") or 0
        f.yuvarlama = okunan.get("yuvarlama") or 0
        if okunan.get("kalemler"):
            santiye = next((k.santiye_id for k in f.kalemler if k.santiye_id), None)
            kalemleri_yaz(f, [kalem_giris(k, santiye) for k in okunan["kalemler"]])
        f.ai_okuma = {**(f.ai_okuma or {}), **okunan, "uyarilar": toplam_farki(f, okunan) + notlari_ayir(okunan.get("notlar"))[0],
                      "bilgi": ["Satıcı firmanız olduğu için satış faturası olarak yeniden okundu." if dogru == "giden"
                                else "Alıcı firmanız olduğu için alış faturası olarak yeniden okundu."]}
        duzelen.append(f.fatura_no or str(f.id))
        db.commit()
    return duzelen


def _sorunlu_taslaklari_oku(db, sirket: Sirket) -> list[str]:
    from types import SimpleNamespace

    from . import ai, tani
    from .models import Cek, Hareket
    from .routers.faturalar import cari_bul_ya_ac, kalem_giris, kalemleri_yaz, notlari_ayir, toplam_farki
    duzelen = []
    duzeltilir = {"kalem_okunamadi", "kalem_tutari", "kdv", "toplam", "cari", "tevkifat"}
    for f in db.scalars(select(Fatura).where(Fatura.sirket_id == sirket.id, Fatura.durum == "taslak")).all():
        if not {x["kategori"] for x in tani.fatura_teshis(f, sirket)} & duzeltilir:
            continue
        okunan = _belge_oku(f, sirket, resimle=True)
        # Yeni okuma da eksik ya da kendi içinde tutarsızsa taslağa dokunulmaz (kırmızı kalır)
        if not okunan or okunan.get("kalemler_okunamadi") or not okunan.get("kalemler") or ai.tutarlilik_uyarilari(okunan):
            continue
        karsi = okunan.get("satici" if f.yon == "gelen" else "alici") or {}
        eski_cari = f.cari
        if karsi.get("vkn") and (not eski_cari or _vkn(eski_cari.vkn) != _vkn(karsi["vkn"])):
            c, _ = cari_bul_ya_ac(db, SimpleNamespace(sirket_id=sirket.id), karsi, "tedarikci" if f.yon == "gelen" else "musteri")
            if c:
                f.cari = c
        f.tevkifat, f.diger_vergiler, f.stopaj = okunan.get("tevkifat") or 0, okunan.get("diger_vergiler") or 0, okunan.get("stopaj") or 0
        f.yuvarlama, f.aciklama = okunan.get("yuvarlama") or 0, f.aciklama or okunan.get("aciklama")
        if (okunan.get("para_birimi") or "TRY") == (f.para_birimi or "TRY") and okunan.get("kur") and not float(f.kur or 0):
            f.kur = okunan["kur"]
        santiye = next((k.santiye_id for k in f.kalemler if k.santiye_id), None)
        kalemleri_yaz(f, [kalem_giris(k, santiye) for k in okunan["kalemler"]])
        notlar = notlari_ayir(okunan.get("notlar"))[0]
        f.ai_okuma = {**(f.ai_okuma or {}), **okunan, "uyarilar": toplam_farki(f, okunan) + notlar,
                      "bilgi": ["Okuma Hata Raporu'ndan sonra programın yeni sürümüyle yeniden okundu."]}
        db.flush()
        if eski_cari is not None and f.cari is not eski_cari and eski_cari.ad_otomatik and not any(
                db.scalar(select(m.id).where(m.cari_id == eski_cari.id).limit(1)) for m in (Fatura, Cek, Hareket)) \
                and not db.scalar(select(Cek.id).where(Cek.ciro_cari_id == eski_cari.id).limit(1)):
            db.delete(eski_cari)  # yanlış okunan adla otomatik açılmış, artık kullanılmayan cari
            db.flush()
        duzelen.append(f.fatura_no or str(f.id))
        db.commit()  # resimden okuma yavaştır; her fatura ayrı kaydedilir, program bu sırada kilitlenmez
    return duzelen


def _no(x) -> str:
    return re.sub(r"[^0-9A-Z]", "", str(x or "").upper())


def _sorunlu_onaylilari_oku(db, sirket: Sirket) -> tuple[list[str], list[str]]:
    """Onaylı faturada kalemler/KDV/toplam faturadakini tutmuyorsa belge yeniden okunur. Yazılması için okuma tam
    (kalemler çıkmış), kendi içinde tutarlı, numarası faturanınkiyle aynı ve para birimi aynı olmalı; kalemlerden
    hesaplanan KDV ve toplam okunan belgeyi tutmazsa değişiklik geri alınır. Faturadaki toplam kayıttakinden farklıysa
    (eski sürüm yanlış işlemiş) belgedeki esas alınır ve ayrıca raporlanır."""
    from . import ai, tani
    from .routers.faturalar import kalem_giris, kalemleri_yaz, notlari_ayir, toplam_farki
    duzelen, tutari_degisen = [], []
    duzeltilir = {"kalem_okunamadi", "kalem_tutari", "kdv", "toplam", "tevkifat"}
    for f in db.scalars(select(Fatura).where(Fatura.sirket_id == sirket.id, Fatura.durum == "onayli")).all():
        if not {x["kategori"] for x in tani.fatura_teshis(f, sirket)} & duzeltilir:
            continue
        okunan = _belge_oku(f, sirket, resimle=True)
        if not okunan or not f.fatura_no or _no(okunan.get("fatura_no")) != _no(f.fatura_no) \
                or (okunan.get("para_birimi") or "TRY") != (f.para_birimi or "TRY") or ai.tutarlilik_uyarilari(okunan):
            continue
        toplamlar = {a: okunan.get(a) for a in ("ara_toplam", "kdv_toplam", "tevkifat", "genel_toplam")}
        if None not in toplamlar.values() and not toplam_farki(f, okunan) \
                and abs(float(f.ara_toplam) - toplamlar["ara_toplam"]) <= 0.05:
            # Kayıt faturayı tutuyor, eski okumanın rakamları yanlışmış (ör. "KDV faturada 0,00"): yalnız okuma yenilenir
            f.ai_okuma = {**(f.ai_okuma or {}), **toplamlar}
            if not {x["kategori"] for x in tani.fatura_teshis(f, sirket)} & duzeltilir:
                duzelen.append(f.fatura_no)
                continue
        if okunan.get("kalemler_okunamadi") or not okunan.get("kalemler") or okunan.get("genel_toplam") is None:
            continue
        eski_genel = float(f.genel_toplam or 0)
        santiye = next((k.santiye_id for k in f.kalemler if k.santiye_id), None) or f.santiye_id
        nokta = db.begin_nested()
        f.tevkifat, f.diger_vergiler, f.stopaj = okunan.get("tevkifat") or 0, okunan.get("diger_vergiler") or 0, okunan.get("stopaj") or 0
        f.yuvarlama, f.aciklama = okunan.get("yuvarlama") or 0, f.aciklama or okunan.get("aciklama")
        kalemleri_yaz(f, [kalem_giris(k, santiye) for k in okunan["kalemler"]])
        db.flush()
        if toplam_farki(f, okunan):
            nokta.rollback()  # kalemlerden çıkan KDV/toplam faturadakini tutmuyor: eski kayıt kalır, kırmızı listelenir
            continue
        nokta.commit()
        notlar = notlari_ayir(okunan.get("notlar"))[0]
        f.ai_okuma = {**(f.ai_okuma or {}), **okunan, "uyarilar": notlar,
                      "bilgi": ["Onaylı fatura programın yeni sürümüyle belgesinden yeniden okundu."]}
        duzelen.append(f.fatura_no)
        if abs(float(f.genel_toplam) - eski_genel) > 0.05:
            tutari_degisen.append(f"{f.fatura_no}: {eski_genel:.2f} → {float(f.genel_toplam):.2f}")
        db.commit()
    return duzelen, tutari_degisen


def rapor_oku() -> dict:
    try:
        return json.loads(RAPOR.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def baslangicta_onar() -> None:
    """Her sürüm için bir kez çalışır; hata programın açılmasını engellemez."""
    eski_surum = rapor_oku().get("surum", 0)
    if eski_surum >= SURUM:
        return
    rapor = {"surum": SURUM, "sirketler": {}}
    db = SessionLocal()
    try:
        if db.scalar(select(Fatura.id).limit(1)) is not None:
            from . import yedek
            try:
                yedek.yedek_al()  # onarım kayıtları değiştirebilir: önce yedek, yedek alınamazsa onarım yapılmaz
            except Exception as e:  # noqa: BLE001
                print("Onarımdan önce yedek alınamadı, onarım sonraki açılışa kaldı:", e)
                return
        for sirket in db.scalars(select(Sirket)).all():
            rapor["sirketler"][str(sirket.id)] = onar(db, sirket, eski_surum)
    except Exception as e:  # noqa: BLE001
        print("Kayıt onarımı yapılamadı:", e)
        return
    finally:
        db.close()
    RAPOR.write_text(json.dumps(rapor, ensure_ascii=False, indent=1), encoding="utf-8")
