"""Veri modelleri. Her kayıt bir şirkete (sirket_id) bağlıdır; böylece
programı kullanan her kişinin verisi diğerlerinden ayrı kalır."""
from datetime import date, datetime

from sqlalchemy import Boolean, JSON, Date, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

Para = Numeric(18, 2)


class Sirket(Base):
    __tablename__ = "sirketler"
    id: Mapped[int] = mapped_column(primary_key=True)
    unvan: Mapped[str] = mapped_column(String(255))
    vkn: Mapped[str | None] = mapped_column(String(11))
    # Firma bilgileri: yazdırılan fatura, ekstre ve mutabakat mektuplarının başlığında kullanılır.
    vergi_dairesi: Mapped[str | None] = mapped_column(String(100))
    adres: Mapped[str | None] = mapped_column(Text)
    telefon: Mapped[str | None] = mapped_column(String(50))
    eposta: Mapped[str | None] = mapped_column(String(255))
    iban: Mapped[str | None] = mapped_column(String(34))
    fatura_seri: Mapped[str | None] = mapped_column(String(3))  # satış faturası numarası öneki, ör. AFS


class Kullanici(Base):
    __tablename__ = "kullanicilar"
    id: Mapped[int] = mapped_column(primary_key=True)
    eposta: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    ad: Mapped[str] = mapped_column(String(255))
    sifre_hash: Mapped[str] = mapped_column(String(255))
    sirket_id: Mapped[int] = mapped_column(ForeignKey("sirketler.id"))
    rol: Mapped[str] = mapped_column(String(20), default="sahip")  # sahip | muhasebeci | izleyici | uye
    # Bölüm yetkileri (yetki.py): {"fatura": ["gor", "ekle"], ...}; boşsa rolün varsayılanı
    yetkiler: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    sirket: Mapped[Sirket] = relationship()


class Oturum(Base):
    __tablename__ = "oturumlar"
    token: Mapped[str] = mapped_column(String(64), primary_key=True)
    kullanici_id: Mapped[int] = mapped_column(ForeignKey("kullanicilar.id"))
    olusturma: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    kullanici: Mapped[Kullanici] = relationship()


class HataliGiris(Base):
    """Hatalı giriş denemeleri (IP başına): program yeniden açılınca da kilit sürer."""
    __tablename__ = "hatali_girisler"
    id: Mapped[int] = mapped_column(primary_key=True)
    ip: Mapped[str] = mapped_column(String(64), index=True)
    zaman: Mapped[float] = mapped_column()


class Cari(Base):
    __tablename__ = "cariler"
    id: Mapped[int] = mapped_column(primary_key=True)
    sirket_id: Mapped[int] = mapped_column(ForeignKey("sirketler.id"), index=True)
    unvan: Mapped[str] = mapped_column(String(255))
    tur: Mapped[str] = mapped_column(String(20), default="tedarikci")  # musteri | tedarikci | her_ikisi
    vkn: Mapped[str | None] = mapped_column(String(11), index=True)
    vergi_dairesi: Mapped[str | None] = mapped_column(String(100))
    adres: Mapped[str | None] = mapped_column(Text)
    telefon: Mapped[str | None] = mapped_column(String(50))
    eposta: Mapped[str | None] = mapped_column(String(255))
    iban: Mapped[str | None] = mapped_column(String(34))
    # Ad PDF/XML'den otomatik geldiyse daha doğru okunan adla düzelebilir; kullanıcı düzenleyince sabitlenir.
    ad_otomatik: Mapped[bool] = mapped_column(Boolean, default=False)
    # Varsayılan vade (gün): faturada vade yazmıyorsa fatura tarihi + bu gün vade sayılır.
    vade_gun: Mapped[int | None] = mapped_column()


class Santiye(Base):
    __tablename__ = "santiyeler"
    id: Mapped[int] = mapped_column(primary_key=True)
    sirket_id: Mapped[int] = mapped_column(ForeignKey("sirketler.id"), index=True)
    ad: Mapped[str] = mapped_column(String(255))
    adres: Mapped[str | None] = mapped_column(Text)
    baslangic: Mapped[date | None] = mapped_column(Date)
    bitis: Mapped[date | None] = mapped_column(Date)
    butce: Mapped[float | None] = mapped_column(Para)
    durum: Mapped[str] = mapped_column(String(20), default="aktif")  # aktif | tamamlandi
    eski_adlar: Mapped[str | None] = mapped_column(Text)  # ad değişince eski adlar (satır satır); eski adla gelen belge buraya eşlenir


class Depo(Base):
    """Şantiye içindeki ayrı hesap (örn. "Taşeron Usta"). Fatura kalemi depoya ayrılırsa şantiye raporunda depo
    kırılımıyla görünür; depoya cari bağlıysa kalem tutarı o cariye borç yazılır (faturanın kendi carisi değişmez)."""
    __tablename__ = "depolar"
    id: Mapped[int] = mapped_column(primary_key=True)
    sirket_id: Mapped[int] = mapped_column(ForeignKey("sirketler.id"), index=True)
    ad: Mapped[str] = mapped_column(String(255))
    santiye_id: Mapped[int | None] = mapped_column(ForeignKey("santiyeler.id"))
    cari_id: Mapped[int | None] = mapped_column(ForeignKey("cariler.id"))
    aciklama: Mapped[str | None] = mapped_column(Text)
    durum: Mapped[str] = mapped_column(String(20), default="aktif")  # aktif | pasif
    eski_adlar: Mapped[str | None] = mapped_column(Text)
    santiye: Mapped["Santiye | None"] = relationship()
    cari: Mapped["Cari | None"] = relationship()


class TaseronGider(Base):
    """Taşeron adına yapılan faturasız harcama: elden verilen/harcanan para (tur=elden) ya da taşeronun personeline
    ödenen ücret ve SGK (tur=personel). Tutar taşeron carisine borç yazılır."""
    __tablename__ = "taseron_giderleri"
    id: Mapped[int] = mapped_column(primary_key=True)
    sirket_id: Mapped[int] = mapped_column(ForeignKey("sirketler.id"), index=True)
    cari_id: Mapped[int] = mapped_column(ForeignKey("cariler.id"), index=True)
    tur: Mapped[str] = mapped_column(String(10))  # elden | personel
    tarih: Mapped[date] = mapped_column(Date, index=True)
    donem: Mapped[str | None] = mapped_column(String(7))  # personelde bordro ayı: 2026-09
    aciklama: Mapped[str | None] = mapped_column(Text)
    santiye_id: Mapped[int | None] = mapped_column(ForeignKey("santiyeler.id"))
    depo_id: Mapped[int | None] = mapped_column(ForeignKey("depolar.id"))
    personel: Mapped[str | None] = mapped_column(String(255))
    tckn: Mapped[str | None] = mapped_column(String(11))
    gun: Mapped[int | None] = mapped_column(Integer)
    brut: Mapped[float | None] = mapped_column(Para)
    net: Mapped[float | None] = mapped_column(Para)  # personele ödenen net
    sgk_isci: Mapped[float | None] = mapped_column(Para)  # SGK masrafı (bordroda normal kazanç x oran)
    vergi: Mapped[float | None] = mapped_column(Para)  # gelir vergisi + damga vergisi
    isveren: Mapped[float | None] = mapped_column(Para)  # SGK + işsizlik işveren payları
    tutar: Mapped[float] = mapped_column(Para)  # cariye borç yazılan toplam
    # Kasadan ödendiyse kasadaki çıkış hareketi (cariye bağlı değildir; borcu bu kayıt yazar)
    hareket_id: Mapped[int | None] = mapped_column(ForeignKey("hareketler.id"))
    santiye: Mapped["Santiye | None"] = relationship()


class Fatura(Base):
    __tablename__ = "faturalar"
    id: Mapped[int] = mapped_column(primary_key=True)
    sirket_id: Mapped[int] = mapped_column(ForeignKey("sirketler.id"), index=True)
    yon: Mapped[str] = mapped_column(String(10), default="gelen")  # gelen (alış) | giden (satış)
    durum: Mapped[str] = mapped_column(String(10), default="taslak")  # taslak | onayli | iptal
    iptal_nedeni: Mapped[str | None] = mapped_column(Text)
    fatura_no: Mapped[str | None] = mapped_column(String(50))
    tarih: Mapped[date | None] = mapped_column(Date)
    vade: Mapped[date | None] = mapped_column(Date)
    cari_id: Mapped[int | None] = mapped_column(ForeignKey("cariler.id"))
    santiye_id: Mapped[int | None] = mapped_column(ForeignKey("santiyeler.id"))
    gider_turu: Mapped[str | None] = mapped_column(String(50))
    ara_toplam: Mapped[float] = mapped_column(Para, default=0)
    kdv_toplam: Mapped[float] = mapped_column(Para, default=0)
    tevkifat: Mapped[float] = mapped_column(Para, default=0)
    # Gelir/kurumlar vergisi stopajı: ödenecek tutardan düşülür (alıcı vergi dairesine öder)
    stopaj: Mapped[float] = mapped_column(Para, default=0)
    diger_vergiler: Mapped[float] = mapped_column(Para, default=0)  # konaklama vergisi, ÖTV, ÖİV vb.
    # Satıcının kendi kuruş yuvarlaması: kalemlerin toplamı faturada yazandan farklıysa fark (kalem uydurulmaz)
    yuvarlama: Mapped[float] = mapped_column(Para, default=0)
    genel_toplam: Mapped[float] = mapped_column(Para, default=0)
    para_birimi: Mapped[str] = mapped_column(String(3), default="TRY")
    # Dövizli faturada 1 birim dövizin TL karşılığı; raporlar ve cari bakiye TL karşılığıyla hesaplanır.
    kur: Mapped[float | None] = mapped_column(Numeric(18, 6))
    # e-Fatura tipi (SATIS, IADE, TEVKIFAT, ISTISNA...). İADE faturası raporlarda karşı tarafın tutarını azaltır.
    fatura_tipi: Mapped[str | None] = mapped_column(String(20))
    aciklama: Mapped[str | None] = mapped_column(Text)
    kaynak_dosya: Mapped[str | None] = mapped_column(String(255))  # görüntü (PDF/HTML/resim); yoksa XML
    # Yüklenen dosyanın özeti (sha256): aynı dosya yeniden yüklenirse okunmadan "zaten kayıtlı" denir.
    dosya_ozeti: Mapped[str | None] = mapped_column(String(64), index=True)
    xml_dosya: Mapped[str | None] = mapped_column(String(255))  # e-Fatura XML'i (resmi belge)
    # Yapay zekanın okuduğu ham bilgi ve uyarılar; onay ekranında gösterilir.
    ai_okuma: Mapped[dict | None] = mapped_column(JSON)
    olusturma: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    cari: Mapped[Cari | None] = relationship()
    santiye: Mapped[Santiye | None] = relationship()
    kalemler: Mapped[list["FaturaKalem"]] = relationship(
        back_populates="fatura", cascade="all, delete-orphan", order_by="FaturaKalem.id"
    )


class RedFatura(Base):
    """Karşı tarafça reddedilmiş / iptal edilmiş fatura: yüklemede kaydedilmez, kayıtlıysa iptal önerilir."""
    __tablename__ = "reddedilen_faturalar"
    id: Mapped[int] = mapped_column(primary_key=True)
    sirket_id: Mapped[int] = mapped_column(ForeignKey("sirketler.id"), index=True)
    yon: Mapped[str] = mapped_column(String(10), default="gelen")
    ettn: Mapped[str | None] = mapped_column(String(36), index=True)
    fatura_no: Mapped[str | None] = mapped_column(String(50), index=True)
    vkn: Mapped[str | None] = mapped_column(String(11))  # karşı firmanın
    unvan: Mapped[str | None] = mapped_column(String(255))
    tarih: Mapped[date | None] = mapped_column(Date)
    tutar: Mapped[float] = mapped_column(Para, default=0)
    olusturma: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class WolvoxAktarim(Base):
    """Wolvox'tan bir kerelik aktarım: aktarılan faturalar durum="aktarim" olur (cari bakiyesi, KDV ve mali raporlara
    girmez; şantiye, depo ve malzeme raporlarında görünür). Aktarım geri alınınca faturaları ve açtığı boş
    şantiye/depolar silinir."""
    __tablename__ = "wolvox_aktarimlari"
    id: Mapped[int] = mapped_column(primary_key=True)
    sirket_id: Mapped[int] = mapped_column(ForeignKey("sirketler.id"), index=True)
    tarih: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    dosya: Mapped[str | None] = mapped_column(String(255))
    fatura_sayisi: Mapped[int] = mapped_column(Integer, default=0)
    atlanan: Mapped[int] = mapped_column(Integer, default=0)
    toplam: Mapped[float] = mapped_column(Para, default=0)
    acilan_santiyeler: Mapped[list | None] = mapped_column(JSON)
    acilan_depolar: Mapped[list | None] = mapped_column(JSON)


class Malzeme(Base):
    """Malzeme (stok adı) kartı: faturalarda biraz farklı yazılan aynı malzemenin adları bir kartta toplanır
    (eski_adlar = kalemlerde geçen öteki yazılışlar, satır satır). Kalem kendi adını korur; karta adıyla bağlanır."""
    __tablename__ = "malzemeler"
    id: Mapped[int] = mapped_column(primary_key=True)
    sirket_id: Mapped[int] = mapped_column(ForeignKey("sirketler.id"), index=True)
    ad: Mapped[str] = mapped_column(String(255))
    eski_adlar: Mapped[str | None] = mapped_column(Text)


class FaturaKalem(Base):
    __tablename__ = "fatura_kalemleri"
    id: Mapped[int] = mapped_column(primary_key=True)
    fatura_id: Mapped[int] = mapped_column(ForeignKey("faturalar.id"), index=True)
    aciklama: Mapped[str] = mapped_column(Text)
    miktar: Mapped[float] = mapped_column(Numeric(18, 4), default=1)
    birim: Mapped[str | None] = mapped_column(String(20))
    birim_fiyat: Mapped[float] = mapped_column(Numeric(18, 4), default=0)
    kdv_orani: Mapped[float] = mapped_column(Numeric(5, 2), default=20)
    tutar: Mapped[float] = mapped_column(Para, default=0)  # KDV hariç
    # Boşsa faturanın şantiyesi geçerlidir; birden fazla şantiyeye ait faturalarda kalem bazında seçilir.
    santiye_id: Mapped[int | None] = mapped_column(ForeignKey("santiyeler.id"))
    # Şantiye içindeki depo (taşeron); boşsa kalem şantiyenin kendisine kalır
    depo_id: Mapped[int | None] = mapped_column(ForeignKey("depolar.id"))
    # Faturada yazan KDV tutarı oran x tutardan farklıysa (satıcının yazdığı esas): boşsa oran x tutar.
    kdv_tutari: Mapped[float | None] = mapped_column(Para, nullable=True)
    # KDV tevkifatı: oran onda kaç (2 = 2/10), KDVGUT kodu (624 yük taşımacılığı...). Tutar = KDV x oran / 10.
    tevkifat_orani: Mapped[float] = mapped_column(Numeric(4, 2), default=0)
    tevkifat_kodu: Mapped[str | None] = mapped_column(String(10))
    # Stopaj yüzdesi (5 = %5); tutar = KDV hariç tutar x oran / 100
    stopaj_orani: Mapped[float] = mapped_column(Numeric(5, 2), default=0)
    # İskonto: birim fiyat liste fiyatıdır; tutar = miktar x birim fiyat - iskonto tutarı.
    iskonto_orani: Mapped[float] = mapped_column(Numeric(6, 2), default=0)
    iskonto_tutari: Mapped[float] = mapped_column(Para, default=0)
    fatura: Mapped[Fatura] = relationship(back_populates="kalemler")
    santiye: Mapped[Santiye | None] = relationship()
    depo: Mapped[Depo | None] = relationship()

    @property
    def kdv(self) -> float:
        return float(self.kdv_tutari) if self.kdv_tutari is not None else float(self.tutar or 0) * float(self.kdv_orani or 0) / 100


class BankaHesabi(Base):
    __tablename__ = "banka_hesaplari"
    id: Mapped[int] = mapped_column(primary_key=True)
    sirket_id: Mapped[int] = mapped_column(ForeignKey("sirketler.id"), index=True)
    ad: Mapped[str] = mapped_column(String(100))
    banka: Mapped[str | None] = mapped_column(String(100))
    sube: Mapped[str | None] = mapped_column(String(100))
    iban: Mapped[str | None] = mapped_column(String(34))
    para_birimi: Mapped[str] = mapped_column(String(3), default="TRY")
    acilis_bakiyesi: Mapped[float] = mapped_column(Para, default=0)
    acilis_ekstreden: Mapped[bool] = mapped_column(Boolean, default=False)  # açılış bakiyesi ilk ekstre satırından
    # Son yüklenen ekstrenin son satırındaki bakiye; programdaki bakiyeyle mutabakat için.
    ekstre_bakiye: Mapped[float | None] = mapped_column(Para)
    ekstre_tarihi: Mapped[date | None] = mapped_column(Date)
    # Kredi kartı da bir hesaptır: bakiyesi eksiyse kart borcudur. Harcamalar işyeri carisine ödeme olarak işlenir.
    tur: Mapped[str] = mapped_column(String(12), default="banka")  # banka | kredi_karti
    kart_no: Mapped[str | None] = mapped_column(String(25))  # maskeli, ör. 5528 79** **** 1234
    son_odeme_tarihi: Mapped[date | None] = mapped_column(Date)  # son yüklenen kart ekstresinden
    asgari_odeme: Mapped[float | None] = mapped_column(Para)


class IsyeriEslesme(Base):
    """Kart ekstresindeki işyeri adının hangi cariye işlendiği; kullanıcı bir kez düzeltince sonraki ekstrelerde
    aynı işyeri o cariye gider. anahtar: kart.isyeri_anahtari (ör. 'migros')."""
    __tablename__ = "isyeri_eslesmeleri"
    id: Mapped[int] = mapped_column(primary_key=True)
    sirket_id: Mapped[int] = mapped_column(ForeignKey("sirketler.id"), index=True)
    anahtar: Mapped[str] = mapped_column(String(120), index=True)
    cari_id: Mapped[int] = mapped_column(ForeignKey("cariler.id"))


class Cek(Base):
    """Alınan (müşteriden) veya verilen (tedarikçiye) çek/senet."""
    __tablename__ = "cekler"
    id: Mapped[int] = mapped_column(primary_key=True)
    sirket_id: Mapped[int] = mapped_column(ForeignKey("sirketler.id"), index=True)
    yon: Mapped[str] = mapped_column(String(10))  # alinan | verilen
    tur: Mapped[str] = mapped_column(String(10), default="cek")  # cek | senet
    durum: Mapped[str] = mapped_column(String(20))  # CEK_DURUMLARI
    cek_no: Mapped[str | None] = mapped_column(String(50))
    banka: Mapped[str | None] = mapped_column(String(100))
    sube: Mapped[str | None] = mapped_column(String(100))
    hesap_no: Mapped[str | None] = mapped_column(String(50))
    kesideci: Mapped[str | None] = mapped_column(String(255))
    tutar: Mapped[float] = mapped_column(Para)
    para_birimi: Mapped[str] = mapped_column(String(3), default="TRY")
    vade: Mapped[date] = mapped_column(Date, index=True)
    alis_tarihi: Mapped[date | None] = mapped_column(Date)
    cari_id: Mapped[int | None] = mapped_column(ForeignKey("cariler.id"))  # kimden alındı / kime verildi
    ciro_cari_id: Mapped[int | None] = mapped_column(ForeignKey("cariler.id"))
    banka_hesap_id: Mapped[int | None] = mapped_column(ForeignKey("banka_hesaplari.id"))
    santiye_id: Mapped[int | None] = mapped_column(ForeignKey("santiyeler.id"))
    aciklama: Mapped[str | None] = mapped_column(Text)
    kaynak_dosya: Mapped[str | None] = mapped_column(String(255))
    islem_tarihi: Mapped[date | None] = mapped_column(Date)  # ödendiği / tahsil / ciro / takas tarihi
    ozel_kod: Mapped[str | None] = mapped_column(String(50))
    kesideci_vkn: Mapped[str | None] = mapped_column(String(11))
    lehtar: Mapped[str | None] = mapped_column(String(200))

    cari: Mapped[Cari | None] = relationship(foreign_keys=[cari_id])
    ciro_cari: Mapped[Cari | None] = relationship(foreign_keys=[ciro_cari_id])
    banka_hesap: Mapped[BankaHesabi | None] = relationship()
    santiye: Mapped["Santiye | None"] = relationship()


CEK_DURUMLARI = {
    "alinan": {"portfoyde": "Portföyde", "ciro_edildi": "Ciro edildi", "tahsilde": "Takasa verildi",
               "teminatta": "Teminata verildi", "tahsil_edildi": "Tahsil edildi", "karsiliksiz": "Karşılıksız / protesto",
               "iade": "İade edildi"},
    "verilen": {"verildi": "Ödenmedi", "odendi": "Ödendi", "iade": "İade alındı"},
}
# Henüz sonuçlanmamış çekler (vadesi gelince uyarılır, portföy/borç toplamına girer)
ACIK_CEK_DURUMLARI = ("portfoyde", "tahsilde", "teminatta", "verildi")


class Hareket(Base):
    """Para hareketi. giris: şirkete para girdi, cikis: şirketten para çıktı.

    cari_id doluysa carinin bakiyesini, banka_hesap_id doluysa banka
    bakiyesini etkiler. Banka ekstresinden gelen satırlar önce taslak olur.
    """
    __tablename__ = "hareketler"
    id: Mapped[int] = mapped_column(primary_key=True)
    sirket_id: Mapped[int] = mapped_column(ForeignKey("sirketler.id"), index=True)
    durum: Mapped[str] = mapped_column(String(10), default="onayli")  # taslak | onayli | iptal
    iptal_nedeni: Mapped[str | None] = mapped_column(Text)
    tarih: Mapped[date] = mapped_column(Date, index=True)
    yon: Mapped[str] = mapped_column(String(6))  # giris | cikis
    tur: Mapped[str] = mapped_column(String(20))  # HAREKET_TURLERI
    tutar: Mapped[float] = mapped_column(Para)
    cari_id: Mapped[int | None] = mapped_column(ForeignKey("cariler.id"), index=True)
    banka_hesap_id: Mapped[int | None] = mapped_column(ForeignKey("banka_hesaplari.id"), index=True)
    santiye_id: Mapped[int | None] = mapped_column(ForeignKey("santiyeler.id"))
    cek_id: Mapped[int | None] = mapped_column(ForeignKey("cekler.id"))
    gider_turu: Mapped[str | None] = mapped_column(String(50))
    aciklama: Mapped[str | None] = mapped_column(Text)
    kaynak: Mapped[str] = mapped_column(String(10), default="elle")  # elle | ekstre | cek
    ekstre_anahtari: Mapped[str | None] = mapped_column(String(64), index=True)  # mükerrer satır kontrolü
    ai_okuma: Mapped[dict | None] = mapped_column(JSON)
    # Bankadan nakit çekim / bankaya nakit yatırmanın kasadaki karşılığı bu alanla bankadaki harekete bağlanır.
    bagli_hareket_id: Mapped[int | None] = mapped_column(ForeignKey("hareketler.id"))

    cari: Mapped[Cari | None] = relationship()
    banka_hesap: Mapped[BankaHesabi | None] = relationship()
    santiye: Mapped[Santiye | None] = relationship()


HAREKET_TURLERI = {
    "tahsilat": "Tahsilat", "odeme": "Ödeme", "masraf": "Masraf", "banka_masrafi": "Banka masrafı",
    "virman": "Virman", "nakit_cekim": "Nakit çekim (bankadan kasaya)",
    "nakit_yatirma": "Nakit yatırma (kasadan bankaya)", "cek_tahsil": "Çek tahsili", "cek_odeme": "Çek ödemesi", "cek_ciro": "Çek cirosu",
    "cek_karsiliksiz": "Karşılıksız çek", "kredi_odeme": "Kredi / kredi kartı ödemesi", "diger": "Diğer",
}


GIDER_TURLERI = [
    "Beton", "Demir", "Çimento", "Tuğla/Blok", "Kum/Çakıl", "Kereste", "Elektrik malzemesi",
    "Tesisat malzemesi", "Boya/Yalıtım", "İşçilik/Taşeron", "Nakliye", "Makine kiralama",
    "Akaryakıt", "Yemek", "Konaklama", "Kira", "Elektrik/Su/Doğalgaz", "Haberleşme/İnternet", "Danışmanlık",
    "Vade farkı/Faiz", "Seyahat/Bilet", "Diğer",
]


class DuzenliOdeme(Base):
    """Her ay (ya da 3/6/12 ayda bir) tekrarlanan ödeme veya tahsilat: kira, kredi taksidi, SGK, maaş, vergi...
    Ödeme takviminde ve nakit akışında görünür; son_donem ödenen son dönemdir (YYYY-AA)."""
    __tablename__ = "duzenli_odemeler"
    id: Mapped[int] = mapped_column(primary_key=True)
    sirket_id: Mapped[int] = mapped_column(ForeignKey("sirketler.id"), index=True)
    ad: Mapped[str] = mapped_column(String(255))
    yon: Mapped[str] = mapped_column(String(6), default="cikis")  # cikis (ödeme) | giris (tahsilat)
    tutar: Mapped[float] = mapped_column(Para)
    gun: Mapped[int] = mapped_column(default=1)  # ayın kaçında; ay kısaysa ayın son günü
    periyot: Mapped[int] = mapped_column(default=1)  # kaç ayda bir
    baslangic: Mapped[date] = mapped_column(Date)
    bitis: Mapped[date | None] = mapped_column(Date)
    cari_id: Mapped[int | None] = mapped_column(ForeignKey("cariler.id"))
    banka_hesap_id: Mapped[int | None] = mapped_column(ForeignKey("banka_hesaplari.id"))
    aciklama: Mapped[str | None] = mapped_column(Text)
    son_donem: Mapped[str | None] = mapped_column(String(7))
    aktif: Mapped[bool] = mapped_column(Boolean, default=True)

    cari: Mapped[Cari | None] = relationship()
    banka_hesap: Mapped[BankaHesabi | None] = relationship()


class Degisiklik(Base):
    """Değişiklik geçmişi: kayıtlı fatura, para hareketi, çek, cari ve banka hesabında kim, ne zaman, neyi değiştirdi.
    Silinen kaydın son hali de saklanır; geçmiş silinmez."""
    __tablename__ = "degisiklikler"
    id: Mapped[int] = mapped_column(primary_key=True)
    sirket_id: Mapped[int] = mapped_column(ForeignKey("sirketler.id"), index=True)
    kullanici_id: Mapped[int | None] = mapped_column(ForeignKey("kullanicilar.id"))
    zaman: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)
    tablo: Mapped[str] = mapped_column(String(20))  # fatura | hareket | cek | cari | banka_hesabi
    kayit_id: Mapped[int] = mapped_column(index=True)
    islem: Mapped[str] = mapped_column(String(12))  # eklendi | degisti | onaylandi | iptal | iptal_geri | silindi
    ozet: Mapped[str] = mapped_column(Text)
    alanlar: Mapped[dict | None] = mapped_column(JSON)  # {alan: [eski, yeni]} ya da silinende son hali
