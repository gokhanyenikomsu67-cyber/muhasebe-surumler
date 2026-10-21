"""Yazdırılabilir sayfalar: fatura, cari ekstre ve cari mutabakat mektubu.

Tarayıcı bu HTML'i yeni pencerede açar ve yazdırma penceresini getirir; 'PDF olarak kaydet' ile dosya da alınabilir.
"""
from datetime import date
from html import escape

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from .. import kural
from ..auth import aktif_kullanici
from ..db import get_db
from ..hesap import cari_hareketleri
from ..models import Cari, Fatura, Kullanici, Sirket
from .temel import sirket_kaydi

router = APIRouter(prefix="/api/yazdir")

STIL = """
body{font:12px/1.45 Arial,Helvetica,sans-serif;color:#111;margin:24px}
h1{font-size:18px;margin:0 0 4px} h2{font-size:14px;margin:18px 0 6px}
.ust{display:flex;justify-content:space-between;gap:24px;border-bottom:2px solid #1f4e79;padding-bottom:10px;margin-bottom:14px}
.kutu{border:1px solid #999;padding:8px 10px;min-width:240px}
table{width:100%;border-collapse:collapse;margin-top:8px} th,td{border:1px solid #999;padding:4px 6px;text-align:left}
th{background:#dbe5f1} .sayi{text-align:right;white-space:nowrap} .toplam td{font-weight:bold;background:#f2f2f2}
.toplamlar{margin-left:auto;width:320px} .imza{display:flex;justify-content:space-between;margin-top:60px}
.imza div{width:40%;border-top:1px solid #333;padding-top:4px;text-align:center} .not{color:#555;font-size:11px}
@media print{body{margin:10mm} .yazdirma{display:none}}
"""


def _para(v) -> str:
    s = f"{float(v or 0):,.2f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def _tarih(t: date | None) -> str:
    return t.strftime("%d.%m.%Y") if t else ""


def _sayfa(baslik: str, govde: str) -> HTMLResponse:
    return HTMLResponse(f"""<!doctype html><html lang="tr"><head><meta charset="utf-8"><title>{escape(baslik)}</title>
<style>{STIL}</style></head><body>
<p class="yazdirma"><button onclick="print()">Yazdır / PDF olarak kaydet</button></p>
{govde}<script>addEventListener("load",()=>setTimeout(()=>print(),300))</script></body></html>""")


def _firma(s: Sirket) -> str:
    satirlar = [f"<h1>{escape(s.unvan)}</h1>"]
    if s.adres:
        satirlar.append(escape(s.adres))
    vd = " · ".join(x for x in (f"V.D.: {escape(s.vergi_dairesi)}" if s.vergi_dairesi else "",
                                 f"VKN: {escape(s.vkn)}" if s.vkn else "") if x)
    if vd:
        satirlar.append(vd)
    iletisim = " · ".join(escape(x) for x in (s.telefon, s.eposta) if x)
    if iletisim:
        satirlar.append(iletisim)
    return "<div>" + "<br>".join(satirlar) + "</div>"


def _cari(c: Cari | None, etiket: str) -> str:
    if not c:
        return f'<div class="kutu"><b>{etiket}</b><br>(cari seçilmemiş)</div>'
    ek = "<br>".join(escape(x) for x in (c.adres, f"V.D.: {c.vergi_dairesi}" if c.vergi_dairesi else None,
                                          f"VKN/TCKN: {c.vkn}" if c.vkn else None) if x)
    return f'<div class="kutu"><b>{etiket}</b><br><b>{escape(c.unvan)}</b><br>{ek}</div>'


@router.get("/fatura/{fatura_id}", response_class=HTMLResponse)
def fatura(fatura_id: int, db: Session = Depends(get_db), k: Kullanici = Depends(aktif_kullanici)):
    f = sirket_kaydi(db, Fatura, fatura_id, k)
    s = db.get(Sirket, k.sirket_id)
    satis = f.yon == "giden"
    def tevk_notu(kl):
        if not float(kl.tevkifat_orani or 0):
            return ""
        ad = kural.TEVKIFAT_KODLARI.get(kl.tevkifat_kodu or "", (None, ""))[1]
        return (f"<br><small>KDV tevkifatı {float(kl.tevkifat_orani):g}/10"
                f"{' · ' + escape(kl.tevkifat_kodu) + ' ' + escape(ad) if kl.tevkifat_kodu else ''}: "
                f"{_para(kural.tevkifat_tutari(kl.tutar, kl.kdv_orani, kl.tevkifat_orani, kl.kdv_tutari))}</small>")
    kalemler = "".join(
        f"<tr><td>{i}</td><td>{escape(kl.aciklama)}{tevk_notu(kl)}</td><td class='sayi'>{float(kl.miktar):g} {escape(kl.birim or '')}</td>"
        f"<td class='sayi'>{_para(kl.birim_fiyat)}</td>"
        f"<td class='sayi'>{'%' + format(float(kl.iskonto_orani), 'g') if float(kl.iskonto_orani or 0) else ''}</td>"
        f"<td class='sayi'>{_para(kl.iskonto_tutari) if float(kl.iskonto_tutari or 0) else ''}</td>"
        f"<td class='sayi'>%{float(kl.kdv_orani):g}</td>"
        f"<td class='sayi'>{_para(kl.kdv)}</td><td class='sayi'>{_para(kl.tutar)}</td></tr>"
        for i, kl in enumerate(f.kalemler, 1))
    toplam = [("Mal/Hizmet Toplamı (KDV hariç)", f.ara_toplam), ("Hesaplanan KDV", f.kdv_toplam)]
    if float(f.tevkifat or 0):
        toplam.append(("KDV Tevkifatı", -float(f.tevkifat)))
    if float(f.diger_vergiler or 0):
        toplam.append(("Diğer Vergiler", f.diger_vergiler))
    if float(f.yuvarlama or 0):
        toplam.append(("Yuvarlama", f.yuvarlama))
    toplam_html = "".join(f"<tr><td>{a}</td><td class='sayi'>{_para(v)} {escape(f.para_birimi)}</td></tr>" for a, v in toplam)
    banka = f"<p>IBAN: {escape(s.iban)}</p>" if satis and s.iban else ""
    govde = f"""
<div class="ust">{_firma(s) if satis else _cari(f.cari, 'SATICI')}
<div class="kutu"><b>{'SATIŞ' if satis else 'ALIŞ'} FATURASI</b><br>Fatura Tipi: {'TEVKİFAT' if float(f.tevkifat or 0) else 'SATIŞ'}<br>Fatura No: {escape(f.fatura_no or '-')}<br>
Tarih: {_tarih(f.tarih)}<br>{'Vade: ' + _tarih(f.vade) if f.vade else ''}</div></div>
{_cari(f.cari, 'SAYIN') if satis else f'<div class="kutu"><b>ALICI</b><br><b>{escape(s.unvan)}</b></div>'}
<table><thead><tr><th>Sıra No</th><th>Mal Hizmet Adı</th><th class="sayi">Miktar</th><th class="sayi">Birim Fiyat</th>
<th class="sayi">İskonto Oranı</th><th class="sayi">İskonto Tutarı</th><th class="sayi">KDV Oranı</th><th class="sayi">KDV Tutarı</th>
<th class="sayi">Mal Hizmet Tutarı</th></tr></thead><tbody>{kalemler}</tbody></table>
<table class="toplamlar">{toplam_html}<tr class="toplam"><td>ÖDENECEK TUTAR</td>
<td class="sayi">{_para(f.genel_toplam)} {escape(f.para_birimi)}</td></tr></table>
{f'<p>Açıklama: {escape(f.aciklama)}</p>' if f.aciklama else ''}{banka}
<p class="not">Bu çıktı programdaki kaydın dökümüdür. e-Fatura / e-Arşiv mükellefiyetinde yasal fatura entegratör
veya GİB portalından düzenlenir.</p>"""
    return _sayfa(f"Fatura {f.fatura_no or f.id}", govde)


def _ekstre_satirlari(db: Session, k: Kullanici, c: Cari, bas: date | None, bit: date | None):
    satirlar = sorted(cari_hareketleri(db, k.sirket_id, c.id), key=lambda s: (s["tarih"] or date.min, s["sira"]))
    devir = sum(s["borc"] - s["alacak"] for s in satirlar if bas and s["tarih"] and s["tarih"] < bas)
    secili = [s for s in satirlar if (not bas or (s["tarih"] and s["tarih"] >= bas)) and (not bit or (s["tarih"] and s["tarih"] <= bit))]
    return devir, secili


@router.get("/cari-ekstre/{cari_id}", response_class=HTMLResponse)
def cari_ekstre(cari_id: int, baslangic: date | None = None, bitis: date | None = None,
                db: Session = Depends(get_db), k: Kullanici = Depends(aktif_kullanici)):
    c = sirket_kaydi(db, Cari, cari_id, k)
    s = db.get(Sirket, k.sirket_id)
    devir, satirlar = _ekstre_satirlari(db, k, c, baslangic, bitis)
    bakiye, govde_satir = devir, []
    if baslangic:
        govde_satir.append(f"<tr><td>{_tarih(baslangic)}</td><td></td><td>Devreden bakiye</td><td></td><td></td>"
                           f"<td class='sayi'>{_para(devir)}</td></tr>")
    for x in satirlar:
        bakiye += x["borc"] - x["alacak"]
        govde_satir.append(f"<tr><td>{_tarih(x['tarih'])}</td><td>{escape(x['belge'] or '')}</td><td>{escape(x['aciklama'])}</td>"
                           f"<td class='sayi'>{_para(x['borc']) if x['borc'] else ''}</td>"
                           f"<td class='sayi'>{_para(x['alacak']) if x['alacak'] else ''}</td><td class='sayi'>{_para(bakiye)}</td></tr>")
    borc, alacak = sum(x["borc"] for x in satirlar), sum(x["alacak"] for x in satirlar)
    donem = " – ".join(_tarih(t) for t in (baslangic, bitis) if t) or "Tüm hareketler"
    govde = f"""<div class="ust">{_firma(s)}<div class="kutu"><b>CARİ HESAP EKSTRESİ</b><br>Dönem: {donem}<br>
Düzenleme: {_tarih(date.today())}</div></div>{_cari(c, 'CARİ')}
<table><thead><tr><th>Tarih</th><th>Belge No</th><th>Açıklama</th><th class="sayi">Borç</th><th class="sayi">Alacak</th>
<th class="sayi">Bakiye</th></tr></thead><tbody>{''.join(govde_satir)}</tbody>
<tr class="toplam"><td colspan="3">Toplam</td><td class="sayi">{_para(borc)}</td><td class="sayi">{_para(alacak)}</td>
<td class="sayi">{_para(bakiye)}</td></tr></table>
<p class="not">Bakiye pozitifse cari firmamıza borçlu, negatifse firmamız cariye borçludur.</p>"""
    return _sayfa(f"Ekstre {c.unvan}", govde)


@router.get("/mutabakat/{cari_id}", response_class=HTMLResponse)
def mutabakat(cari_id: int, tarih: date | None = None, db: Session = Depends(get_db), k: Kullanici = Depends(aktif_kullanici)):
    c = sirket_kaydi(db, Cari, cari_id, k)
    return _sayfa(f"Mutabakat {c.unvan}", _mutabakat_govde(db, k, c, tarih or date.today()))


@router.get("/mutabakat-toplu", response_class=HTMLResponse)
def mutabakat_toplu(idler: str, tarih: date | None = None, db: Session = Depends(get_db), k: Kullanici = Depends(aktif_kullanici)):
    """Seçilen carilerin mutabakat mektupları; her biri ayrı sayfada."""
    cariler = [sirket_kaydi(db, Cari, int(i), k) for i in idler.split(",") if i.strip().isdigit()]
    ara = '<div style="page-break-after:always"></div>'
    return _sayfa("Mutabakat mektupları", ara.join(_mutabakat_govde(db, k, c, tarih or date.today()) for c in cariler))


def _mutabakat_govde(db: Session, k: Kullanici, c: Cari, tarih: date) -> str:
    s = db.get(Sirket, k.sirket_id)
    bakiye = round(sum(x["borc"] - x["alacak"] for x in cari_hareketleri(db, k.sirket_id, c.id)
                       if x["tarih"] is None or x["tarih"] <= tarih), 2)
    if abs(bakiye) < 0.01:
        durum = "hesabınızın <b>sıfır bakiye</b> ile kapalı olduğu"
    elif bakiye > 0:
        durum = f"firmamıza <b>{_para(bakiye)} TL borçlu</b> olduğunuz"
    else:
        durum = f"firmamızın size <b>{_para(-bakiye)} TL borçlu</b> olduğu"
    govde = f"""<div class="ust">{_firma(s)}<div class="kutu"><b>CARİ HESAP MUTABAKAT MEKTUBU</b><br>
Tarih: {_tarih(date.today())}</div></div>{_cari(c, 'SAYIN')}
<p>Kayıtlarımıza göre <b>{_tarih(tarih)}</b> tarihi itibarıyla {durum} görülmektedir.</p>
<p>Kayıtlarınızın bu bilgiyle uyuşup uyuşmadığını aşağıdaki bölümü doldurup imzalayarak bize bildirmenizi rica ederiz.
Uyuşmazlık varsa hesap ekstrenizi göndermeniz mutabakatı kolaylaştıracaktır.</p>
<p>Saygılarımızla,<br><b>{escape(s.unvan)}</b></p>
<h2>Cevap</h2>
<p>☐ Mutabıkız.&nbsp;&nbsp;&nbsp; ☐ Mutabık değiliz; kayıtlarımıza göre bakiye: ................................ TL
(borç / alacak)</p>
<div class="imza"><div>{escape(s.unvan)}<br>Kaşe / İmza</div><div>{escape(c.unvan)}<br>Kaşe / İmza</div></div>"""
    return govde


@router.get("/cek-bordro", response_class=HTMLResponse)
def cek_bordro(yon: str | None = None, durum: str | None = None, cari_id: int | None = None,
               db: Session = Depends(get_db), k: Kullanici = Depends(aktif_kullanici)):
    """Çek/senet bordrosu: seçili yön ve durumdaki çekler ya da bir cariden alınan / cariye verilen-ciro edilenler."""
    from sqlalchemy import or_, select

    from ..models import CEK_DURUMLARI, Cek
    s = db.get(Sirket, k.sirket_id)
    q = select(Cek).where(Cek.sirket_id == k.sirket_id)
    if yon:
        q = q.where(Cek.yon == yon)
    if durum:
        q = q.where(Cek.durum.in_(durum.split(",")))
    c = sirket_kaydi(db, Cari, cari_id, k) if cari_id else None
    if c:
        q = q.where(or_(Cek.cari_id == c.id, Cek.ciro_cari_id == c.id))
    cekler = db.scalars(q.order_by(Cek.vade, Cek.id)).all()
    satirlar = "".join(
        f"<tr><td>{i}</td><td>{'Alınan' if x.yon == 'alinan' else 'Verilen'} {'senet' if x.tur == 'senet' else 'çek'}</td>"
        f"<td>{escape(CEK_DURUMLARI[x.yon].get(x.durum, x.durum))}</td><td>{_tarih(x.vade)}</td><td>{escape(x.cek_no or '')}</td>"
        f"<td>{escape(' / '.join(y for y in (x.banka, x.sube) if y))}</td><td>{escape(x.kesideci or '')}</td>"
        f"<td>{escape(x.cari.unvan if x.cari else '')}{(' → ' + escape(x.ciro_cari.unvan)) if x.ciro_cari else ''}</td>"
        f"<td class='sayi'>{_para(x.tutar)} {escape(x.para_birimi)}</td></tr>" for i, x in enumerate(cekler, 1))
    toplam = sum(float(x.tutar) for x in cekler)
    baslik = "ÇEK / SENET BORDROSU" + (" — " + ("ALINAN" if yon == "alinan" else "VERİLEN") if yon else "")
    govde = f"""<div class="ust">{_firma(s)}<div class="kutu"><b>{baslik}</b><br>Tarih: {_tarih(date.today())}<br>
Adet: {len(cekler)}</div></div>{_cari(c, 'CARİ') if c else ''}
<table><thead><tr><th>#</th><th>Tür</th><th>Durum</th><th>Vade</th><th>Çek No</th><th>Banka / Şube</th><th>Çeki Yazan Firma</th>
<th>Cari</th><th class="sayi">Tutar</th></tr></thead><tbody>{satirlar}</tbody>
<tr class="toplam"><td colspan="8">Toplam ({len(cekler)} adet)</td><td class="sayi">{_para(toplam)}</td></tr></table>
<div class="imza"><div>Teslim Eden<br>Ad Soyad / İmza</div><div>Teslim Alan<br>Ad Soyad / İmza</div></div>"""
    return _sayfa("Çek bordrosu", govde)
