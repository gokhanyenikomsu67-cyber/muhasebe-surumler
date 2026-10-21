"""Resimden (taranmış PDF, fotoğraf) yapay zekasız okuma. Tesseract kurulu değilse uçtan uca testler atlanır."""
import io
import uuid

import pytest

from app import ocr
from tests.test_api import client, yeni_kullanici

SATIRLAR = [
    "YILMAZ BETON SANAYI VE TICARET LTD STI",
    "Vergi Dairesi: Tuzla   VKN: 1234567890",
    "SAYIN TEST INSAAT",
    "VKN: 9999999999",
    "Fatura No: ABC2026000000123",
    "Fatura Tarihi: 01-10-2026",
    "Sira No  Mal Hizmet  Miktar  Birim Fiyat  KDV Orani  KDV Tutari  Mal Hizmet Tutari",
    "1  C30 HAZIR BETON  10 Adet  2.500,00 TL  %20  5.000,00 TL  25.000,00 TL",
    "2  BETON POMPASI  1 Adet  3.000,00 TL  %20  600,00 TL  3.000,00 TL",
    "Mal Hizmet Toplam Tutari: 28.000,00 TL",
    "Hesaplanan KDV (%20): 5.600,00 TL",
    "Vergiler Dahil Toplam Tutar: 33.600,00 TL",
    "Odenecek Tutar: 33.600,00 TL",
]


def yeni():
    return yeni_kullanici(f"{uuid.uuid4().hex}@ornek.com")


def fatura_resmi(aci=0, egiklik=0.0, bicim="PNG"):
    """Sentetik faturanın resmi: PDF çizilir, 200 dpi resme çevrilir; istenirse çevrilir/eğilir (fotoğraf gibi)."""
    canvas = pytest.importorskip("reportlab.pdfgen.canvas")
    pdfium = pytest.importorskip("pypdfium2")
    t = io.BytesIO()
    c = canvas.Canvas(t)
    c.setFont("Helvetica", 11)
    y = 800
    for s in SATIRLAR:
        c.drawString(40, y, s)
        y -= 22
    c.save()
    belge = pdfium.PdfDocument(t.getvalue())
    img = belge[0].render(scale=200 / 72).to_pil().convert("RGB")
    belge.close()
    if egiklik:
        img = img.rotate(egiklik, expand=True, fillcolor=(235, 235, 230))
    if aci:
        img = img.rotate(aci, expand=True)
    b = io.BytesIO()
    img.save(b, bicim, **({"quality": 85} if bicim == "JPEG" else {}))
    return b.getvalue(), t.getvalue()


def test_duzelt_yazim_kaymalari():
    d = ocr.duzelt("1 FOSFORLU YELEK 50Adeti 70,00TL “10 350,00TL 3.500,00 TL\n"
                   "K.DV. Matrahı (620): 800,00TL\nHesaplanan KDV (%10): o 1.155,00 TL\n"
                   "Uriin / Hizmet Toplam Tutarı) 24.097, 19 TL\nFatura No: «A İAVA2026000285213\n— =\n")
    assert "50 Adet 70,00 TL %10 350,00 TL" in d
    assert "KDV Matrahı (%20): 800,00 TL" in d
    assert "Hesaplanan KDV (%10): 1.155,00 TL" in d
    assert "Ürün / Hizmet Toplam Tutarı 24.097,19 TL" in d
    assert "Fatura No: AVA2026000285213" in d
    assert "— =" not in d
    # Rakam uydurulmaz: oran olmayan sayı yüzdeye çevrilmez
    assert "%" not in ocr.duzelt("Tutar 500,00 TL 37 50,00 TL")


def test_unvan_temizle():
    assert ocr.unvan_temizle("GEBZE İŞ GÜVENLİĞİ İNŞ TEKSTİL SAN ve TİC LTD ŞTİ 5 ey =") == \
        "GEBZE İŞ GÜVENLİĞİ İNŞ TEKSTİL SAN ve TİC LTD ŞTİ"
    assert ocr.unvan_temizle("AVANSAS OFİS ANONİM ŞİRKETİ DE hi PL") == "AVANSAS OFİS ANONİM ŞİRKETİ"
    assert ocr.unvan_temizle("MEHMET BAYAR") == "MEHMET BAYAR"
    assert ocr.unvan_temizle("= —") is None


def test_onemli_belirsizler():
    okunan = {"genel_toplam": 33600, "kalemler": [{"tutar": 25000, "birim_fiyat": 2500}]}
    assert ocr._onemli_belirsizler(okunan, ["25.000,00", "[KDVGUT", "12,50", "33.600,00TL"]) == ["25.000,00", "33.600,00"]


tesseract_gerekli = pytest.mark.skipif(not ocr.var_mi(), reason="Tesseract kurulu değil")


@tesseract_gerekli
@pytest.mark.parametrize("aci,egiklik,bicim", [(0, 0, "PNG"), (90, 1.5, "JPEG")])
def test_resimden_fatura_oku(aci, egiklik, bicim):
    resim, _ = fatura_resmi(aci, egiklik, bicim)
    o = ocr.resimden_fatura_oku(resim, False)
    assert o["fatura_no"] == "ABC2026000000123" and str(o["tarih"]) == "2026-10-01"
    assert (o["ara_toplam"], o["kdv_toplam"], o["genel_toplam"]) == (28000, 5600, 33600)
    assert [(k["aciklama"], k["miktar"], k["tutar"], k["kdv_orani"]) for k in o["kalemler"]] == [
        ("C30 HAZIR BETON", 10, 25000, 20), ("BETON POMPASI", 1, 3000, 20)]
    assert o["satici"]["vkn"] == "1234567890" and o["okuma_yontemi"] == "Resimden metin tanıma"
    assert o["resimden"]["guven"] > 60


@tesseract_gerekli
def test_fotograf_yuklenince_taslak_acilir():
    resim, _ = fatura_resmi(bicim="JPEG")
    r = client.post("/api/faturalar/oku", files={"dosya": ("fatura.jpg", resim, "image/jpeg")}, headers=yeni())
    assert r.status_code == 200, r.text
    f = r.json()[0]
    assert f["fatura_no"] == "ABC2026000000123" and float(f["genel_toplam"]) == 33600
    assert [k["aciklama"] for k in f["kalemler"]] == ["C30 HAZIR BETON", "BETON POMPASI"]
    assert any("resimden" in b for b in f["ai_okuma"]["bilgi"])


@tesseract_gerekli
def test_taranmis_pdf_resimden_okunur():
    """Metni olmayan PDF (tarayıcı çıktısı): sayfa resmi metin tanımayla okunur."""
    img = pytest.importorskip("PIL.Image")
    resim, _ = fatura_resmi()
    t = io.BytesIO()
    img.open(io.BytesIO(resim)).convert("RGB").save(t, "PDF", resolution=200)
    r = client.post("/api/faturalar/oku", files={"dosya": ("tarama.pdf", t.getvalue(), "application/pdf")}, headers=yeni())
    assert r.status_code == 200, r.text
    assert r.json()[0]["ai_okuma"]["okuma_yontemi"] == "Resimden metin tanıma"


def test_tesseract_yoksa_nedeni_soylenir(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(ocr, "tesseract", lambda: None)
    h = yeni()
    r = client.post("/api/faturalar/oku", files={"dosya": ("fis.png", b"\x89PNG", "image/png")}, headers=h)
    assert r.status_code == 422 and "Tesseract" in r.json()["detail"]
    ozet = client.get("/api/faturalar/okuma-raporu/ozet", headers=h).json()
    assert ozet["okunamayan_dosya"] == 1


@tesseract_gerekli
def test_pdf_kalemleri_okunamazsa_sayfa_resminden_okunur():
    """Başlık ve toplamlar PDF yazısında, kalem tablosu yalnız resimde (yazısı çıkarılamayan tablo): kalemler resimden
    okunur, PDF yazısındaki toplamları tuttuğu için alınır."""
    canvas = pytest.importorskip("reportlab.pdfgen.canvas")
    from reportlab.lib.utils import ImageReader
    resim, _ = fatura_resmi()
    t = io.BytesIO()
    c = canvas.Canvas(t)
    w, h = c._pagesize
    c.drawImage(ImageReader(io.BytesIO(resim)), 0, 0, w, h)
    yazi = c.beginText(40, 800)
    yazi.setTextRenderMode(3)  # görünmez yazı katmanı: kalemler hariç
    for s in SATIRLAR:
        if not s[:2].strip().isdigit() and not s.startswith("Sira"):
            yazi.textLine(s)
    c.drawText(yazi)
    c.save()
    r = client.post("/api/faturalar/oku", files={"dosya": ("f.pdf", t.getvalue(), "application/pdf")}, headers=yeni())
    assert r.status_code == 200, r.text
    f = r.json()[0]
    assert [(k["aciklama"], float(k["tutar"])) for k in f["kalemler"]] == [("C30 HAZIR BETON", 25000), ("BETON POMPASI", 3000)]
    assert f["ai_okuma"]["okuma_yontemi"] == "PDF metni" and f["ai_okuma"]["resimden"]["yalniz_kalemler"]
    assert any("sayfanın resminden" in b for b in f["ai_okuma"]["bilgi"])
