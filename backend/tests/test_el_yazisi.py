"""El yazısı vade/tutar kuralları (model gerekmez: okunan yazı kutuları elle verilir)."""
from datetime import date

from app import el_yazisi


def test_sayi_yazisi():
    assert el_yazisi.sayi_yazisi(350000) == "ucyuzellibin"
    assert el_yazisi.sayi_yazisi(1000) == "bin" and el_yazisi.sayi_yazisi(1250500) == "birmilyonikiyuzellibinbesyuz"


def test_tutar_rakam_ve_yazi_tutarsa_emin():
    assert el_yazisi.tutar_bul(["TL#250.000#", "ikiyu2ellibn", "YALNIZ"]) == (250000, True)
    # Yazı net, rakam başka okunmuş: yazı geçerlidir ama kırmızı
    assert el_yazisi.tutar_bul(["TL#350.000.#", "Ye diyonelli bin"]) == (750000, False)
    # Yalnız rakam: kırmızı; hiçbir şey: boş
    assert el_yazisi.tutar_bul(["TL # 3 30.000#", "Dgyphe lli bia"]) == (330000, False)
    assert el_yazisi.tutar_bul(["TL+300.0#", "KODEYINIZ"]) == (None, False)


def test_vade():
    bugun = date(2026, 10, 20)
    assert el_yazisi.vade_bul(["KUTAHYA", "22.12.2026"], bugun) == (date(2026, 12, 22), True)
    assert el_yazisi.vade_bul(["120,12.2026"], bugun) == (date(2026, 12, 20), True)  # baştaki "/" 1 okunmuş
    # Yıl imkânsız (2024) ya da eksik: gün/aydan en yakın ileri tarih, kırmızı
    assert el_yazisi.vade_bul(["20.01.2024"], bugun) == (date(2027, 1, 20), False)
    assert el_yazisi.vade_bul(["2201-2024"], bugun) == (date(2027, 1, 22), False)
    assert el_yazisi.vade_bul(["BASIM TARIHI 17.01.2025", "TARIH"], bugun) == (None, False)


def test_etiketsiz_ve_bozuk_etiketli_tarih():
    from datetime import date
    from app import el_yazisi as e
    b = date(2026, 10, 21)
    assert e.vade_bul(["Trn:05 01 2024"], bugun=b) == (date(2027, 1, 5), False)  # yıl 2027'nin 7'si 4 okunmuş
    assert e.vade_bul(["KUTAHYA", "10 12 2026"], bugun=b) == (date(2026, 12, 10), True)
    assert e.vade_bul(["05012027"], bugun=b) == (date(2027, 1, 5), True)
    assert e.vade_bul(["IBAN TR17 0006 7010 0000 0011 2233 44"], bugun=b) == (None, False)


def test_rakamin_bir_hanesi_dusunce_yazi_esas_alinir_ve_yesil_olmaz():
    # "#750.000#" el yazısı "#+50.000#" okundu: yazı "yediyüzellibin" 5 haneliler içinde "ellibin"e benzese de yeşil olmaz
    from app import el_yazisi
    deger, emin, neden = el_yazisi.tutar_bul_nedenli(["yediyozelibin", "TL #+50.000#"])
    assert (deger, emin) == (750000.0, False) and "yazıyla" in neden
    assert el_yazisi.tutar_bul_nedenli(["TL #250.000#", "ikiyuzellibin"])[:2] == (250000.0, True)


def test_vade_basim_tarihinden_once_olamaz_ve_yil_okunmazsa_neden_yazilir():
    from datetime import date
    from app import cek_okuma, el_yazisi
    basim = cek_okuma.basim_tarihi(["BASIM TARIHI 17 0CAK 2025"])
    assert basim == date(2025, 1, 17)
    assert el_yazisi.vade_bul_nedenli(["Tarih: 10.01.2025"], date(2025, 1, 20), basim)[:2] == (None, False)
    t, emin, neden = el_yazisi.vade_bul_nedenli(["KUTAyA Tain.O6O1 201T"], date(2026, 10, 21))
    assert (t, emin) == (date(2027, 1, 6), False) and neden == el_yazisi.YIL_YOK
    # Kaşedeki telefonun "/" işareti tarih sanılmaz
    assert el_yazisi.vade_bul(["sM(0274)2/20101"], date(2026, 10, 21)) == (None, False)
