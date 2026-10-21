# Muhasebe Programı

Şantiye bazlı çalışan işletmeler için, faturaları ve banka ekstrelerini dosyadan okuyan muhasebe programı. Yapay zeka isteğe bağlıdır; anahtar olmadan da çalışır. Arayüz AKINSOFT Wolvox 9 tarzındadır.

## 1. aşamada olanlar

- **Belgeden fatura okuma (yapay zekasız; yapay zeka isteğe bağlı):** e-Fatura XML/ZIP, PDF veya fotoğrafı sürükle-bırak yapın. Fatura no, tarih, satıcı, VKN, kalemler, KDV, tevkifat ve toplamlar okunur. Cari ve şantiye önerilir. Toplamlar tutmazsa ya da fatura daha önce girildiyse uyarı verilir. Siz onaylamadan hiçbir şey deftere işlenmez.
- **Cari:** kart, liste, bakiye raporu, cari ekstre. Excel şablonuyla toplu cari yükleme.
- **Şantiye:** kart, bütçe, maliyet raporu (gider türüne göre dağılım, bütçeden kalan, kâr).
- **Alış ve satış faturaları:** liste, elle giriş, KDV hesabı. Tevkifat kalem bazındadır: her satırda oran ve KDVGUT kodu seçilir (2/10 · 624 yük taşımacılığı, 4/10 · 601 yapım işleri…); faturanın tevkifatı satırların toplamıdır. PDF/XML okurken oran ve kod satıra yazılır, faturadaki tevkifatla tutmazsa uyarı verilir.
- **Excel:** her liste ve rapor tek tıkla .xlsx olarak iner. Wolvox'a aktarım için satır bazlı fatura listesi.
- **Yedekleme:** her gün otomatik, istendiğinde elle. Birden fazla klasöre (ör. bilgisayardaki klasör ve Google Drive klasörü) yazılır, 30 günden eski yedekler silinir. Her yedek alınırken açılıp denenir (bozuksa Genel Durum'da kırmızı uyarı), kopyası kaynakla karşılaştırılır; haftada bir son yedek ayrıca denenir. Yedekler ekranında "Bu yedeğe dön": önce bugünkü veri yedeklenir, seçilen yedek denenmeden hiçbir şey değişmez.
- **Çok şirketli:** her hesap kendi şirketini görür; arkadaşlarınızın verisi sizinkinden ayrıdır.

## 2. aşamada eklenenler

- **Çek / senet takibi:** alınan ve verilen çekler, çek fotoğrafından yapay zekasız okuma ve toplu çek girişi, vade takvimi (geçen ve 7 gün içinde gelen vadeler vurgulanır). Tahsile verme, tahsil, ciro, karşılıksız, iade ve ödeme işlemleri cari ve banka bakiyelerine kendiliğinden işlenir.
- **Banka / kasa:** banka hesapları ve bakiyeleri, elle tahsilat/ödeme/masraf girişi.
- **Banka ekstresi (yapay zekasız):** Excel, CSV, PDF veya ekran görüntüsü yüklenir. Her satır okunur, cariyle eşleştirilir ve türü (tahsilat, ödeme, masraf, banka masrafı…) önerilir. Satırlar onay ekranında düzeltilip toplu onaylanır. Aynı ekstre ikinci kez yüklenirse satırlar tekrar eklenmez.
- **Gösterge paneli:** banka toplamı, portföydeki ve ödenecek çekler, yaklaşan vadeler, toplam alacak/borç, onay bekleyenler.
- Cari ekstre artık fatura, tahsilat, ödeme ve çek hareketlerini birlikte gösterir. Şantiye raporu şantiyeye bağlanan masrafları da içerir.

Sonraki aşamalar: fatura kesme ve e-Fatura, Wolvox şablonlarına birebir aktarım, masaüstü uygulama paketi.

## 3. aşamada eklenenler (Wolvox muhasebe karşılıkları)

- **Mali Raporlar menüsü:** KDV özeti (aylık hesaplanan/indirilecek KDV, devir, tevkifat ve KDV-2), tevkifat raporu (dönem içinde alış ve satış tevkifatı KDVGUT koduna göre, KDV-2 tutarı), Ba-Bs formları (ay içinde aynı kişiyle 5.000 TL ve üzeri belgeler), aylık gelir-gider tablosu (gider türüne göre) ve yaşlandırma / vade analizi (açık bakiyenin 0-30, 31-60, 61-90, 90+ gün dilimleri ve vadesi geçmiş faturalar). Hepsi Excel'e aktarılır.
- **Yazdırma:** fatura (Yazdır düğmesi), cari ekstre ve cari mutabakat mektubu yeni pencerede açılır; yazıcıya ya da "PDF olarak kaydet" ile dosyaya alınır. Araç çubuğundaki Yazdır yalnız açık sekmeyi basar.
- **Firma Bilgileri (Araçlar):** adres, VKN, vergi dairesi, IBAN çıktılarda görünür. Satış faturası serisi (ör. AFS) girilirse yeni satış faturasına sıradaki numara önerilir.
- **Kullanıcılar (Araçlar):** sahip, muhasebeci (kayıt girer) ve izleyici (yalnız görür) yetkileriyle kullanıcı ekleme, yetki ve şifre değiştirme.
- PDF kalem tablosu firmaya özel düzen aranmadan okunur: tablo PDF'teki çizgilerden bulunur, sütunlar başlık adından (Mal Hizmet Adı, Miktar, Birim Fiyat, İskonto, Net Tutar, KDV Tutarı…) eşlenir, alt satıra bölünmüş adlar birleştirilir. Olmazsa eski okuma yöntemleri denenir.
- PDF okuma: TTNET / Türk Telekom ve Turkcell kurumsal faturaları gibi kalem tablosu olmayan faturalar vergi özetinden, sıra numarasız tablolar ve tevkifatlı "#" tabloları da okunur.

Mali raporlar onaylı kayıtlardan hesaplanır; beyanname yerine geçmez, mali müşavirle karşılaştırma içindir.

## Doğruluk, iptal ve mutabakat

- **Çek ve ekstre**: tahsil edilen/ödenen çek bankanın ekstresinde de görünür; program o satırı çekin hareketine bağlar, ikinci tahsilat yazmaz. Ekstre önce gelirse tahsildeki çek kendiliğinden "tahsil edildi" olur. Elle girilen banka hareketi de aynı ekstre satırıyla eşleşir.
- **Tek bakiye**: cari kartı, cari bakiye raporu, yaşlandırma, Genel Durum, banka ekranı ve yazdırılan ekstre aynı hesaptan gelir; senaryo testleri her adımda bunu denetler.
- **İptal**: onaylı fatura ya da para hareketi silinmeden "İptal et" ile iptal edilir; bakiyeden ve raporlardan düşer, kaydı ve nedeni kalır, "İptali geri al" ile döner.
- **Değişiklik geçmişi** (Araçlar > Değişiklik Geçmişi, formlarda "Geçmiş"): kayıtlı fatura, hareket, çek, cari ve banka hesabında kim, ne zaman, neyi neyken neye çevirdi; silinen kaydın son hali de saklanır.
- **Mutabakat** (Banka / Kasa ve Cari menüsünde): banka ekstresi ile program farkı ve nedeni olabilecek kayıtlar, vadesi geçip bekleyen ya da ekstrede görünmeyen çekler, seçilen carilere toplu mutabakat mektubu.
- **Mali raporlar** resmi beyan değildir; ekranda ve Excel'de "mali müşavirle karşılaştırma amaçlıdır" notu bulunur. Ba-Bs bildirimi Eylül 2024 döneminden itibaren kaldırıldı (VUK Genel Tebliği 565); liste iç kontrol için kalır. Kısmi tevkifatta KDV dahil yıllık sınırın (2026: 12.000 TL) altındaki faturalar tevkifat raporunda uyarılır.


### Döviz faturaları
- Faturada yazan kur ("Döviz Kuru", "Fatura Kuru", "1 USD = …") Kur alanına yazılır; kur yazmıyorsa faturadaki TL toplamından bulunur.
- İkisi de yoksa fatura ekranında **TCMB kurunu getir** fatura tarihindeki TCMB döviz alış kurunu getirir (internet gerekir; yoksa kur elle girilir).
- Fatura ekranında döviz toplamlarının altında TL karşılıkları (ara toplam, KDV, genel toplam) görünür; cari, raporlar ve Wolvox aktarımı TL karşılığıyla işler.
## Yapay zekasız çalışma

API anahtarı gerekmez: XML, PDF, fotoğraf, Excel ve ekstreler bu bilgisayarda yapay zekasız okunur. Anahtar yalnız isteğe bağlı yapay zeka okuması içindir. Okuma ekranlarında "Okuma yöntemi" seçilir: Otomatik (önce yapay zekasız, olmazsa ve anahtar varsa yapay zeka), Yapay zekasız veya Yapay zeka ile.

| Belge | Yapay zekasız | Not |
|---|---|---|
| e-Fatura / e-Arşiv XML, GİB ZIP | Tam okunur | En doğru yol. ZIP içindeki her fatura ayrı taslak olur; aynı adlı PDF/HTML ya da XML içindeki görüntü faturaya eklenir. Satır ve fatura altı iskonto, karışık KDV, istisna, tevkifat, ÖTV/ÖİV okunur. Satıcı biz isek satış faturası olur. Aynı faturanın PDF taslağı varsa XML ile düzeltilir, ikinci kayıt açılmaz |
| Metinli PDF fatura | Fatura no, tarih, VKN, kalemler, toplamlar | Kalem tablosu tanınmazsa kırmızı uyarı verilir, kalemler elle girilir |
| Taranmış PDF, fotoğraf (JPG, PNG, HEIC, TIFF) | Metin tanımayla okunur | Bilgisayarda çalışan Tesseract ile, internetsiz. Yan/ters çekilmiş ve eğik fotoğraf düzeltilir. Net okunamayan tutarlar ve tutmayan toplamlar kırmızı gösterilir; belgeyle karşılaştırın |
| Banka ekstresi (.xlsx, .csv, metinli PDF) | Okunur | Cari VKN, IBAN veya ünvandan bulunur; eski .xls dosyası .xlsx olarak kaydedilmeli |
| Excel fatura / çek / cari şablonu | Okunur | Excel İşlemleri'nden şablon indirilir; hatalı satır varsa hiçbir şey eklenmez |

## Windows'ta çalıştırma

1. Zip dosyasını bir klasöre çıkarın (sağ tık > Tümünü ayıkla).
2. Klasördeki `baslat.bat` dosyasına çift tıklayın.
   - Bilgisayarda Python yoksa kendisi kurar; kurulum bitince `baslat.bat`'a bir kez daha çift tıklayın.
   - İlk açılışta Claude API anahtarını sorar. Anahtarınız yoksa boş bırakıp Enter'a basabilirsiniz; program açılır ve bütün okumalar yapay zekasız çalışır.
   - İlk açılışta fotoğraf ve taranmış belge okuma programını (Tesseract) kurar; Windows izin sorarsa Evet deyin. Türkçe dil verisi programla gelir. Kurulamazsa günde bir kez yeniden dener; Genel Durum'daki "Kur" düğmesiyle de hemen denenebilir.
   - İlk açılışta gerekli paketleri internetten indirir (birkaç dakika). Sonraki açılışlarda internete gitmez; yalnız yeni sürümde paket listesi değiştiyse günceller. Zorunlu bir paket kurulamazsa program açılmaz ve nedenini yazar.
3. Tarayıcıda program açılır. "Yeni şirket hesabı aç" ile hesabınızı oluşturun.

**Verileriniz nerede:** `Belgeler\Muhasebe Verileri` klasöründe. Program klasöründen ayrı durduğu için yeni paketi başka bir klasöre açsanız da hesabınız ve kayıtlarınız kaybolmaz; aynı e-posta ve şifreyle girersiniz. Eski sürümlerde veri program klasörünün içindeydi; yeni sürüm ilk açılışta Masaüstü, İndirilenler ve Belgeler'deki eski klasörlerden en çok kayıt içeren veritabanını bulup buraya kopyalar.

**Güncelleme:** yeni paketi istediğiniz yere açıp `baslat.bat`'a çift tıklamanız yeterli.

**Şifremi unuttum:** klasördeki `sifre_sifirla.bat` dosyasına çift tıklayın, listeden hesabınızın numarasını yazıp yeni şifre belirleyin. Eski şifre öğrenilemez, çünkü şifreler geri çevrilemeyecek şekilde saklanır.

Siyah pencere açık kaldığı sürece program çalışır; kapatınca program da kapanır. Ayarlar `.env` dosyasındadır (Not Defteri ile açılabilir). Yedekler varsayılan olarak `Belgeler\MuhasebeYedek` klasörüne alınır.

**Başka bilgisayarlardan erişim:** `.env` dosyasına `MUHASEBE_AG=1` satırını ekleyip programı yeniden açın; aynı ağdaki bilgisayarlar `http://<bu-bilgisayarın-ip-adresi>:8000` adresinden girer. Bu modda:
- her işlem için giriş zorunludur; oturum 30 gün sonra kapanır, 5 hatalı şifre denemesinde o bilgisayardan giriş 10 dakika kapanır;
- yeni şirket hesabı yalnız programın kurulu olduğu bilgisayardan açılır; diğer kişileri Araçlar > Kullanıcılar'dan siz eklersiniz (izleyici yalnız görür, hiçbir şeyi değiştiremez);
- her firma yalnız kendi kayıtlarını görür. Programı internete (modem port yönlendirme) açmayın; yalnız kendi yerel ağınızda kullanın.

### Google Drive yedeği

[Google Drive masaüstü uygulamasını](https://www.google.com/drive/download/) kurun. `.env` içindeki `MUHASEBE_YEDEK_KLASORLERI` satırına Drive klasörünüzü ekleyin (ör. `C:\MuhasebeYedek;G:\My Drive\MuhasebeYedek`). Yedekler hem bilgisayara hem Drive'a gider.

## Geliştirici notları

```
backend/app/
  main.py          uygulama, yedek uçları, günlük otomatik yedek
  models.py        veri modelleri (her kayıt sirket_id ile ayrılır)
  ai.py            Claude API ile fatura okuma ve tutarlılık kontrolü (isteğe bağlı)
  kural.py         yapay zekasız okuma: e-Fatura XML, PDF metni, Excel/CSV/PDF ekstre, cari eşleştirme
  ocr.py           taranmış PDF ve fotoğraftan okuma (Tesseract; ocr_veri/ Türkçe dil verisi), sonra kural.py ile çözülür
  yedek.py         .zip yedek
  hesap.py         cari ve banka bakiyesi hesapları
  routers/         temel (giriş, cari, şantiye), faturalar, cekler, banka (+ekstre), raporlar (+Excel), aktarim (Excel fatura/çek yükleme)
web/               arayüz (derleme gerektirmez)
```

Testler: `cd backend && python -m pytest tests`

Veritabanı varsayılan olarak `backend/veri/muhasebe.db` (SQLite). Sunucuda PostgreSQL için `DATABASE_URL` verilir.
