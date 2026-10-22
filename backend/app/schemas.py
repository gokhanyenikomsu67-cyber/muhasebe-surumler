from datetime import date

from pydantic import BaseModel, ConfigDict


class Orm(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class KayitIstegi(BaseModel):
    sirket_unvan: str
    ad: str
    eposta: str
    sifre: str


class GirisIstegi(BaseModel):
    eposta: str
    sifre: str


class SirketBilgisi(BaseModel):
    unvan: str
    vkn: str | None = None
    vergi_dairesi: str | None = None
    adres: str | None = None
    telefon: str | None = None
    eposta: str | None = None
    iban: str | None = None
    fatura_seri: str | None = None


class KullaniciGiris(BaseModel):
    ad: str
    eposta: str
    sifre: str
    rol: str = "muhasebeci"


class CariGiris(BaseModel):
    unvan: str
    tur: str = "tedarikci"
    vkn: str | None = None
    vergi_dairesi: str | None = None
    adres: str | None = None
    telefon: str | None = None
    eposta: str | None = None
    iban: str | None = None
    vade_gun: int | None = None


class CariCikis(CariGiris, Orm):
    id: int


class SantiyeGiris(BaseModel):
    ad: str
    adres: str | None = None
    baslangic: date | None = None
    bitis: date | None = None
    butce: float | None = None
    durum: str = "aktif"


class SantiyeCikis(SantiyeGiris, Orm):
    id: int


class KalemGiris(BaseModel):
    aciklama: str
    miktar: float = 1
    birim: str | None = None
    birim_fiyat: float = 0
    kdv_orani: float = 20
    tutar: float | None = None
    santiye_id: int | None = None
    tevkifat_orani: float = 0  # onda kaç: 2 = 2/10
    tevkifat_kodu: str | None = None
    stopaj_orani: float = 0  # gelir/kurumlar vergisi stopajı yüzdesi (5 = %5)
    kdv_tutari: float | None = None  # faturada yazan KDV oran x tutardan farklıysa
    iskonto_orani: float = 0  # yüzde
    iskonto_tutari: float = 0  # tutar = miktar x birim fiyat - iskonto tutarı


class KalemCikis(KalemGiris, Orm):
    id: int
    tutar: float


class FaturaGiris(BaseModel):
    yon: str = "gelen"
    fatura_no: str | None = None
    tarih: date | None = None
    vade: date | None = None
    cari_id: int | None = None
    santiye_id: int | None = None
    gider_turu: str | None = None
    tevkifat: float = 0
    stopaj: float = 0
    diger_vergiler: float = 0
    yuvarlama: float = 0
    para_birimi: str = "TRY"
    kur: float | None = None  # dövizli faturada 1 birim dövizin TL karşılığı
    fatura_tipi: str | None = None  # SATIS, IADE, TEVKIFAT, ISTISNA...
    aciklama: str | None = None
    kalemler: list[KalemGiris] = []


class FaturaCikis(Orm):
    id: int
    yon: str
    durum: str
    iptal_nedeni: str | None = None
    fatura_no: str | None
    tarih: date | None
    vade: date | None
    cari_id: int | None
    cari_unvan: str | None = None
    santiye_id: int | None
    santiye_ad: str | None = None
    gider_turu: str | None
    ara_toplam: float
    kdv_toplam: float
    tevkifat: float
    stopaj: float = 0
    diger_vergiler: float = 0
    yuvarlama: float = 0
    genel_toplam: float
    para_birimi: str
    kur: float | None = None
    fatura_tipi: str | None = None
    aciklama: str | None
    kaynak_dosya: str | None
    xml_dosya: str | None = None
    ai_okuma: dict | None
    kalemler: list[KalemCikis] = []
    zaten_var: bool = False  # okutulan fatura daha önce eklenmişti


class BankaHesabiGiris(BaseModel):
    ad: str
    banka: str | None = None
    sube: str | None = None
    iban: str | None = None
    para_birimi: str = "TRY"
    acilis_bakiyesi: float = 0
    tur: str = "banka"  # banka | kredi_karti
    kart_no: str | None = None


class BankaHesabiCikis(BankaHesabiGiris, Orm):
    id: int
    bakiye: float = 0
    ekstre_bakiye: float | None = None
    ekstre_tarihi: date | None = None
    son_odeme_tarihi: date | None = None
    asgari_odeme: float | None = None
    mutabakat_farki: float | None = None  # ekstre bakiyesi - programdaki bakiye (ekstre tarihine kadar)
    hareket_sayisi: int = 0
    onay_bekleyen: int = 0


class CekGiris(BaseModel):
    yon: str = "alinan"
    tur: str = "cek"
    cek_no: str | None = None
    banka: str | None = None
    sube: str | None = None
    hesap_no: str | None = None
    kesideci: str | None = None
    tutar: float
    para_birimi: str = "TRY"
    vade: date
    alis_tarihi: date | None = None
    cari_id: int | None = None
    santiye_id: int | None = None
    aciklama: str | None = None
    ozel_kod: str | None = None  # Wolvox'taki özel kod (isteğe bağlı)
    lehtar: str | None = None  # çekin yazıldığı firma ("... emrine"); bize yazıldıysa çeki yazandan doğrudan aldık
    kesideci_vkn: str | None = None  # çeki yazanın VKN/TCKN'si (cari değil: cari çeki aldığımız/verdiğimiz firma)
    kaynak_dosya: str | None = None


class CekCikis(CekGiris, Orm):
    id: int
    durum: str
    durum_adi: str = ""
    cari_unvan: str | None = None
    ciro_cari_id: int | None = None
    ciro_cari_unvan: str | None = None
    banka_hesap_id: int | None = None
    banka_hesap_ad: str | None = None
    islem_tarihi: date | None = None
    vade_gunu: int | None = None
    kalan_gun: int | None = None


class CekIslem(BaseModel):
    islem: str  # ciro | tahsile_ver | teminata_ver | portfoye_al | tahsil | karsiliksiz | iade | ode
    tarih: date
    cari_id: int | None = None
    banka_hesap_id: int | None = None
    kasa: bool = False  # ödendi / tahsil edildi: Nakit Kasa'dan


class HareketGiris(BaseModel):
    tarih: date
    yon: str
    tur: str
    tutar: float
    cari_id: int | None = None
    banka_hesap_id: int | None = None
    santiye_id: int | None = None
    gider_turu: str | None = None
    aciklama: str | None = None


class HareketCikis(HareketGiris, Orm):
    id: int
    durum: str
    iptal_nedeni: str | None = None
    kaynak: str
    cek_id: int | None = None
    cari_unvan: str | None = None
    banka_hesap_ad: str | None = None
    santiye_ad: str | None = None
    ai_okuma: dict | None = None
    bagli_hareket_id: int | None = None
    sorun: str | None = None  # işlenemeyen satırın nedeni (kırmızı gösterilir)
