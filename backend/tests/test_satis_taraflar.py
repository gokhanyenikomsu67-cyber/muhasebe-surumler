"""Satış faturası: SAYIN bloğundaki kurum adı (muhtarlık, OSB) cari adı olur; satıcı biz isek alış ekranından da
yüklense satışa düşer (sentetik veri)."""
from app import kural
from tests.test_api import client
from tests.test_kural import pdf_olustur, yeni

_BIZ = ["DENEME ENERJI MUHENDISLIK INSAAT LIMITED SIRKETI", "YILDIRIM MAH. ORNEK SK. NO: 12 IC KAPI NO:", "12 MERKEZ/ KUTAHYA",
        "Tel: 8500000000", "Vergi Dairesi: ORNEK VERGI DAIRESI MUD.", "VKN: 9999999999", "SUBENO:", "MERSISNO:", "TICARETSICILNO:"]
_ALT = ["ETTN: 1a2b3c4d-0000-4000-8000-000000000007", "Fatura No: DNM2026000000007", "Fatura Tarihi: 24-06-2026",
        "Mal Hizmet Toplam Tutari 8.000,00 TL", "Hesaplanan KDV(%20) 1.600,00 TL", "Odenecek Tutar 9.600,00 TL"]


def satis_pdf(alici):
    return pdf_olustur(_BIZ + ["SAYIN"] + alici + _ALT)


MUHTARLIK = ["ORNEKLI KOYU MUHTARLIGI MERKEZ", "MERKEZ ORNEKLI KOYU 2", "Kutahya Merkez/ Kutahya", "E-Posta:", "Tel:",
             "Vergi Dairesi: ORNEK VERGI DAIRESI MUD.", "VKN: 3300000001"]
OSB = ["ORNEKKENT ORGANIZE SANAYI BOLGESI", "-", "/", "E-Posta:", "Tel:", "Vergi Dairesi: bilinmiyor",
       "VKN: 6000000002", "MUSTERINO: 6000000002"]
SIRKET = ["ORNEK ENERJI SANAYI VE TICARET ANONIM", "SIRKETI", "-", "/", "E-Posta:", "Vergi Dairesi: ORNEK", "VKN: 1200000003"]


def test_sayin_blogundaki_kurum_adi_cari_adi_olur():
    beklenen = {"ORNEKLI KOYU MUHTARLIGI MERKEZ": MUHTARLIK, "ORNEKKENT ORGANIZE SANAYI BOLGESI": OSB,
                "ORNEK ENERJI SANAYI VE TICARET ANONIM SIRKETI": SIRKET}
    for ad, alici in beklenen.items():
        _, a = kural.pdf_taraflari(kural.pdf_metni(satis_pdf(alici)))
        assert a["unvan"] == ad and not kural.kotu_unvan(a["unvan"])


def test_satis_faturasi_alis_ekranindan_yuklense_de_satisa_duser():
    h = yeni()
    client.put("/api/sirket", json={"unvan": "DENEME ENERJI MUHENDISLIK INSAAT LTD. STI.", "vkn": "9999999999"}, headers=h)
    assert kural.pdf_yonu(satis_pdf(MUHTARLIK), "9999999999") == "giden"
    f = client.post("/api/faturalar/oku?yon=gelen", files={"dosya": ("s.pdf", satis_pdf(MUHTARLIK), "application/pdf")},
                    headers=h).json()[0]
    assert f["yon"] == "giden" and f["cari_unvan"] == "ORNEKLI KOYU MUHTARLIGI MERKEZ" and f["ai_okuma"]["genel_toplam"] == 9600
