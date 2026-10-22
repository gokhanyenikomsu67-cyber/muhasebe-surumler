"use strict";

// ---------------------------------------------------------------- yardımcılar
const $ = (s, el = document) => el.querySelector(s);
const h = (etiket, ozellik = {}, ...cocuklar) => {
  const el = document.createElement(etiket);
  for (const [k, v] of Object.entries(ozellik)) {
    if (v == null || v === false) continue;
    if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "html") el.innerHTML = v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const c of cocuklar.flat()) if (c != null && c !== false) el.append(c instanceof Node ? c : String(c));
  return el;
};
const paraBicim = new Intl.NumberFormat("tr-TR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const para = (v) => (v == null ? "" : paraBicim.format(v));
const tarih = (v) => (v ? new Date(v + "T00:00:00").toLocaleDateString("tr-TR") : "");

function bildir(mesaj, hata = false) {
  const el = h("div", { class: hata ? "hata" : "" }, mesaj);
  $("#bildirim").append(el);
  setTimeout(() => el.remove(), hata ? 6000 : 3000);
}
function durum(mesaj) { $("#durum-mesaj").textContent = mesaj; }

let TOKEN = null;
try { TOKEN = localStorage.getItem("muhasebe_token"); } catch { /* depolama kapalı */ }
let BEN = null;

async function api(yol, { metod = "GET", veri, dosya } = {}) {
  const ayar = { method: metod, headers: { Authorization: `Bearer ${TOKEN}` } };
  if (dosya) ayar.body = dosya;
  else if (veri !== undefined) { ayar.body = JSON.stringify(veri); ayar.headers["Content-Type"] = "application/json"; }
  let r;
  try { r = await fetch(yol, ayar); } catch { throw new Error("Programa ulaşılamıyor. baslat.bat penceresi açık mı? Kapandıysa yeniden açın."); }
  if (r.status === 401 && yol !== "/api/giris") { cikisYap(); throw new Error("Oturum sona erdi."); }
  if (!r.ok) {
    let detay = null;
    try { detay = (await r.json()).detail; } catch {}
    throw new Error(hataMetni(detay, r.status));
  }
  const tur = r.headers.get("content-type") || "";
  return tur.includes("json") ? r.json() : r.blob();
}

// Kullanıcıya ham teknik hata (JSON, İngilizce) gösterilmez: kısa Türkçe açıklama yazılır
const ALAN_ADLARI = { banka_hesap_id: "banka hesabı", cari_id: "cari", santiye_id: "şantiye", fatura_id: "fatura", cek_id: "çek",
  tarih: "tarih", vade: "vade", tutar: "tutar", miktar: "miktar", birim_fiyat: "birim fiyat", kdv_orani: "KDV oranı" };
function hataMetni(detay, durum) {
  if (typeof detay === "string" && detay && !/^[\[{]/.test(detay.trim())) return detay;
  if (Array.isArray(detay)) {
    const alanlar = [...new Set(detay.map((d) => (d && Array.isArray(d.loc) ? d.loc[d.loc.length - 1] : null))
      .filter((a) => typeof a === "string").map((a) => ALAN_ADLARI[a] || a.replace(/_id$/, "").replace(/_/g, " ")))];
    return alanlar.length ? `Bilgi eksik ya da hatalı: ${alanlar.join(", ")}. Kontrol edip tekrar deneyin.` : "Girilen bilgilerden biri eksik ya da hatalı.";
  }
  if (durum === 404) return "Kayıt bulunamadı; silinmiş olabilir. Ekranı yenileyin (F5).";
  if (durum === 403) return "Bu işlem için yetkiniz yok.";
  if (durum >= 500) return "Program bir hatayla karşılaştı. Tekrar deneyin; düzelmezse ekran görüntüsünü gönderin.";
  return "İşlem yapılamadı. Tekrar deneyin.";
}

async function indir(yol, ad) {
  try {
    const blob = await api(yol);
    const a = h("a", { href: URL.createObjectURL(blob), download: ad });
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  } catch (e) { bildir(e.message, true); }
}

// ---------------------------------------------------------------- simgeler
const SIMGE = {
  yeni: '<path d="M6 2h9l5 5v15H6z" fill="#fff" stroke="#2e75b6" stroke-width="1.5"/><path d="M13 11v8M9 15h8" stroke="#2e7d32" stroke-width="2.5"/>',
  degistir: '<path d="M4 20l1-5L16 4l4 4L9 19z" fill="#ffd966" stroke="#8a6100" stroke-width="1.3"/><path d="M4 20l1-5 4 4z" fill="#555"/>',
  sil: '<path d="M6 7h12l-1 14H7z" fill="#f4cccc" stroke="#c0392b" stroke-width="1.5"/><path d="M4 7h16M9 4h6" stroke="#c0392b" stroke-width="1.8"/>',
  kaydet: '<path d="M3 3h15l3 3v15H3z" fill="#2e75b6"/><path d="M7 3h9v6H7z" fill="#fff"/><path d="M6 13h12v8H6z" fill="#dbe8f5"/>',
  yenile: '<path d="M19 8a8 8 0 1 0 1 6" fill="none" stroke="#2e75b6" stroke-width="2.4"/><path d="M20 2v7h-7z" fill="#2e75b6"/>',
  yazdir: '<path d="M6 3h12v6H6z" fill="#fff" stroke="#555"/><path d="M2 9h20v9H2z" fill="#8497b0"/><path d="M6 14h12v7H6z" fill="#fff" stroke="#555"/>',
  excel: '<path d="M8 2h13v20H8z" fill="#e3f4e4" stroke="#1e7145"/><path d="M2 6h11v12H2z" fill="#1e7145"/><path d="M4.5 8.5l6 7M10.5 8.5l-6 7" stroke="#fff" stroke-width="1.8"/>',
  ai: '<rect x="3" y="3" width="18" height="18" rx="3" fill="#7e57c2"/><path d="M8 16l4-9 4 9M9.6 13h4.8" stroke="#fff" stroke-width="1.8" fill="none"/>',
  kapat: '<circle cx="12" cy="12" r="9" fill="#e06666"/><path d="M8 8l8 8M16 8l-8 8" stroke="#fff" stroke-width="2.2"/>',
};
const simge = (ad) => { const s = document.createElementNS("http://www.w3.org/2000/svg", "svg"); s.setAttribute("viewBox", "0 0 24 24"); s.innerHTML = SIMGE[ad]; return s; };

// ---------------------------------------------------------------- sekmeler
const sekmeler = [];
let aktifSekme = null;

function sekmeAc(anahtar, baslik, ekran) {
  const var_olan = sekmeler.find((s) => s.anahtar === anahtar);
  if (var_olan) { sekmeSec(var_olan); return var_olan; }
  const s = { anahtar, baslik, ekran };
  sekmeler.push(s);
  sekmeSec(s);
  return s;
}
function sekmeSec(s) {
  aktifSekme = s;
  sekmeleriCiz();
  // Her çizim kendi kabına yazar; geç biten eski bir çizim ekrana karışmaz.
  const kap = h("div");
  $("#sekme-icerik").replaceChildren(kap);
  s.ekran.ciz(kap, s);
  aracCubugunuGuncelle();
}
function sekmeKapat(s) {
  const i = sekmeler.indexOf(s);
  if (i < 0) return;
  sekmeler.splice(i, 1);
  if (aktifSekme === s) {
    const sonraki = sekmeler[i] || sekmeler[i - 1];
    if (sonraki) sekmeSec(sonraki);
    else { aktifSekme = null; sekmeleriCiz(); bosEkran(); aracCubugunuGuncelle(); }
  } else sekmeleriCiz();
}
function sekmeleriCiz() {
  $("#sekmeler").replaceChildren(...sekmeler.map((s) =>
    h("div", { class: "sekme" + (s === aktifSekme ? " aktif" : ""), onclick: () => sekmeSec(s) },
      s.baslik, h("span", { class: "kapat", title: "Kapat", onclick: (e) => { e.stopPropagation(); sekmeKapat(s); } }, "✕"))));
}
function bosEkran() {
  const kap = h("div");
  $("#sekme-icerik").replaceChildren(kap);
  gostergePaneli(kap);
}
function yenidenCiz() { if (aktifSekme) sekmeSec(aktifSekme); }

// ---------------------------------------------------------------- araç çubuğu
const ARACLAR = [
  ["yeni", "Yeni", "Ins"], ["degistir", "Değiştir", "Enter"], ["sil", "Sil", "Del"], ["kaydet", "Kaydet", "F2"], "|",
  ["yenile", "Yenile", "F5"], ["yazdir", "Yazdır", ""], ["excel", "Excel", "F9"], "|",
  ["ai", "Fatura Oku", ""], ["kapat", "Kapat", "Esc"],
];
function aracCubugunuCiz() {
  $("#arac-cubugu").replaceChildren(...ARACLAR.map((a) => a === "|" ? h("div", { class: "arac-ayrac" }) :
    h("button", { class: "arac", "data-komut": a[0], title: a[2] ? `${a[1]} (${a[2]})` : a[1], onclick: () => komut(a[0]) },
      simge(a[0]), a[1], a[2] ? h("small", {}, a[2]) : null)));
}
function komutVar(ad) {
  if (ad === "ai") return true;
  if (ad === "kapat") return !!aktifSekme;
  if (ad === "yazdir") return !!aktifSekme;
  return !!aktifSekme?.ekran[ad];
}
function aracCubugunuGuncelle() {
  for (const b of document.querySelectorAll("[data-komut]")) b.disabled = !komutVar(b.dataset.komut);
}
function komut(ad) {
  if (!komutVar(ad)) return;
  if (ad === "ai") return aiOkumaAc();
  if (ad === "kapat") return sekmeKapat(aktifSekme);
  if (ad === "yazdir") return window.print();
  aktifSekme.ekran[ad]();
}
document.addEventListener("keydown", (e) => {
  if ($("#uygulama").hidden) return;
  if (e.key === "F3" || ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k")) { e.preventDefault(); return hizliAramaAc(); }
  const yazarken = ["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement?.tagName);
  const tus = { Insert: "yeni", F2: "kaydet", F5: "yenile", F9: "excel", Escape: "kapat" }[e.key]
    || (!yazarken && e.key === "Delete" ? "sil" : null)
    || (!yazarken && e.key === "Enter" ? "degistir" : null);
  if (tus && komutVar(tus)) { e.preventDefault(); komut(tus); }
});

// ---------------------------------------------------------------- liste ekranı
/** Wolvox tarzı filtre satırlı liste. */
function listeEkrani({ baslik, kaynak, kolonlar, yeni, yeniYazi, ac, sil, silSorarak, excel, ustAlan, toplamlar, toplu }) {
  let satirlar = [];
  let secili = null;
  // toplu: [{ ad, islem(seciliSatirlar) }] verilirse satır başında onay kutusu; "tümünü seç" filtreyle görünenleri seçer
  const isaretli = new Set();
  let gorunen = [];
  const filtre = {};
  const ekran = {
    async ciz(alan) {
      const tbody = h("tbody");
      const tfoot = h("tfoot");
      const sayac = h("span", { class: "sayac" });
      const tumu = h("input", { type: "checkbox", title: "Görünenlerin tümünü seç",
        onchange: (e) => { gorunen.forEach((s) => (e.target.checked ? isaretli.add(s.id) : isaretli.delete(s.id))); doldur(); } });
      const topluAlan = toplu ? h("span", { class: "toplu-islem" }, sayac, toplu.map((t) => [t.ek || null, h("button", { class: "dugme" + (t.tehlikeli ? " tehlike" : ""),
        onclick: async () => {
          const sec = satirlar.filter((s) => isaretli.has(s.id));
          if (!sec.length) return bildir("Önce kutucuklardan kayıt seçin.", true);
          try { if (await t.islem(sec) !== false) { isaretli.clear(); yenidenCiz(); } } catch (e) { bildir(e.message, true); }
        } }, t.ad)]).flat()) : null;
      // Yeni kayıt düğmesi ekranın içinde de görünür (araç çubuğundaki "Yeni" fark edilmiyordu)
      const ust = h("div", { class: "liste-ust" }, h("h2", {}, baslik),
        yeni ? h("button", { class: "dugme ana", onclick: () => yeni() }, yeniYazi || "+ Yeni") : null,
        ustAlan ? ustAlan(() => ekran.yenile()) : null, topluAlan);
      const tablo = h("table", { class: "liste" },
        h("thead", {},
          h("tr", {}, toplu ? h("th", {}, tumu) : null, kolonlar.map((k) => h("th", { class: k.tip === "para" ? "sayi" : "" }, k.baslik))),
          h("tr", { class: "filtre" }, toplu ? h("th") : null, kolonlar.map((k) => h("th", {},
            h("input", { placeholder: "Ara…", value: filtre[k.alan] || "", oninput: (e) => { filtre[k.alan] = e.target.value; doldur(); } }))))),
        tbody, tfoot);
      alan.append(ust, h("div", { class: "tablo-kap" }, tablo));

      const hucre = (k, s) => {
        const v = k.deger ? k.deger(s) : s[k.alan];
        if (k.tip === "para") return h("td", { class: "sayi" + (v < 0 ? " negatif" : "") }, para(v));
        if (k.tip === "tarih") return h("td", {}, tarih(v));
        return h("td", {}, v instanceof Node ? v : v ?? "");
      };
      const metin = (k, s) => { const v = k.metin ? k.metin(s) : k.deger ? k.deger(s) : s[k.alan]; return k.tip === "tarih" ? tarih(v) : String(v ?? ""); };
      function doldur() {
        gorunen = satirlar.filter((s) => kolonlar.every((k) => !filtre[k.alan] ||
          metin(k, s).toLocaleLowerCase("tr").includes(filtre[k.alan].toLocaleLowerCase("tr"))));
        tbody.replaceChildren(...gorunen.map((s) => {
          const kutu = toplu ? h("td", { onclick: (e) => e.stopPropagation() }, h("input", { type: "checkbox", checked: isaretli.has(s.id),
            onchange: (e) => { e.target.checked ? isaretli.add(s.id) : isaretli.delete(s.id); sayacYaz(); } })) : null;
          const tr = h("tr", { class: s === secili ? "secili" : "",
            onclick: () => { secili = s; tbody.querySelectorAll("tr").forEach((t) => t.classList.remove("secili")); tr.classList.add("secili"); },
            ondblclick: () => ac?.(s) }, kutu, kolonlar.map((k) => hucre(k, s)));
          return tr;
        }));
        sayacYaz();
        tfoot.replaceChildren();
        if (toplamlar) {
          tfoot.append(h("tr", {}, toplu ? h("td") : null, kolonlar.map((k, i) => toplamlar.includes(k.alan)
            ? h("td", { class: "sayi" }, para(gorunen.reduce((t, s) => t + (s[k.alan] || 0), 0)))
            : h("td", {}, i === 0 ? `${gorunen.length} kayıt` : ""))));
        }
        durum(`${gorunen.length} kayıt listelendi`);
      }
      function sayacYaz() {
        if (!toplu) return;
        sayac.textContent = `${isaretli.size} seçili`;
        tumu.checked = gorunen.length > 0 && gorunen.every((s) => isaretli.has(s.id));
      }
      try { satirlar = await kaynak(); } catch (e) { bildir(e.message, true); }
      for (const id of [...isaretli]) if (!satirlar.some((s) => s.id === id)) isaretli.delete(id);
      secili = satirlar.find((s) => s.id === secili?.id) || null;
      doldur();
    },
    yenile: () => yenidenCiz(),
  };
  if (yeni) ekran.yeni = yeni;
  if (ac) ekran.degistir = () => (secili ? ac(secili) : bildir("Önce listeden bir kayıt seçin."));
  if (sil) ekran.sil = async () => {
    if (!secili) return bildir("Önce listeden bir kayıt seçin.");
    if (!confirm("Seçili kayıt silinsin mi?")) return;
    try { await sil(secili); secili = null; bildir("Kayıt silindi."); yenidenCiz(); } catch (e) { bildir(e.message, true); }
  };
  if (silSorarak) ekran.sil = async () => {  // kendi onay sorusunu soran silme (false dönerse vazgeçildi)
    if (!secili) return bildir("Önce listeden bir kayıt seçin.");
    try { if (await silSorarak(secili) !== false) { secili = null; yenidenCiz(); } } catch (e) { bildir(e.message, true); }
  };
  if (excel) ekran.excel = () => indir(excel, `${baslik}.xlsx`);
  return ekran;
}

// ---------------------------------------------------------------- form yardımcıları
function alan(etiket, ad, deger, ozellik = {}) {
  const girdi = ozellik.secenekler
    ? h("select", { name: ad }, ozellik.secenekler.map(([d, m]) => h("option", { value: d, selected: String(d) === String(deger ?? "") }, m)))
    : ozellik.cok_satir ? h("textarea", { name: ad, rows: 2 }, deger ?? "")
      : h("input", { name: ad, value: deger ?? "", type: ozellik.tip || "text", step: ozellik.tip === "number" ? "any" : null, required: ozellik.zorunlu });
  return h("label", { class: ozellik.genis ? "genis" : "" }, etiket, girdi);
}
function formVerisi(form, sayilar = []) {
  const v = Object.fromEntries(new FormData(form));
  for (const [k, d] of Object.entries(v)) {
    if (d === "") v[k] = null;
    else if (sayilar.includes(k)) v[k] = Number(d);
  }
  return v;
}

// ---------------------------------------------------------------- cariler
const CARI_TURLERI = [["tedarikci", "Tedarikçi"], ["musteri", "Müşteri"], ["her_ikisi", "Her ikisi"]];

function cariListesiAc() {
  sekmeAc("cariler", "Cari Listesi", listeEkrani({
    baslik: "Cari Listesi",
    kaynak: () => api("/api/cariler"),
    kolonlar: [
      { alan: "unvan", baslik: "Ünvan" },
      { alan: "tur", baslik: "Tür", deger: (s) => Object.fromEntries(CARI_TURLERI)[s.tur] },
      { alan: "vkn", baslik: "VKN/TCKN" }, { alan: "vergi_dairesi", baslik: "Vergi Dairesi" },
      { alan: "telefon", baslik: "Telefon" }, { alan: "eposta", baslik: "E-posta" }, { alan: "iban", baslik: "IBAN" },
    ],
    yeni: () => cariFormAc(),
    ac: (c) => cariFormAc(c),
    sil: (c) => api(`/api/cariler/${c.id}`, { metod: "DELETE" }),
    toplu: [{ ad: "Seçilenleri sil", tehlikeli: true, islem: (sec) => topluSil(sec, "cari", (c) => c.unvan, (c) => `/api/cariler/${c.id}`) }],
    excel: "/api/excel/cariler",
  }));
}

function cariFormAc(cari = null) {
  const s = sekmeAc(cari ? `cari-${cari.id}` : `cari-yeni-${Date.now()}`, cari ? cari.unvan : "Yeni Cari", {
    ciz(el) {
      const form = h("form", { class: "form-pencere", onsubmit: (e) => { e.preventDefault(); this.kaydet(); } },
        h("h2", {}, cari ? "Cari Kartı" : "Yeni Cari Kartı"),
        h("fieldset", {}, h("legend", {}, "Genel Bilgiler"), h("div", { class: "alanlar" },
          alan("Ünvan", "unvan", cari?.unvan, { zorunlu: true, genis: true }),
          alan("Tür", "tur", cari?.tur, { secenekler: CARI_TURLERI }),
          alan("VKN/TCKN", "vkn", cari?.vkn), alan("Vergi Dairesi", "vergi_dairesi", cari?.vergi_dairesi),
          alan("Vade (gün) — faturada vade yoksa", "vade_gun", cari?.vade_gun, { tip: "number" }))),
        h("fieldset", {}, h("legend", {}, "İletişim ve Banka"), h("div", { class: "alanlar" },
          alan("Telefon", "telefon", cari?.telefon), alan("E-posta", "eposta", cari?.eposta),
          alan("IBAN", "iban", cari?.iban), alan("Adres", "adres", cari?.adres, { cok_satir: true, genis: true }))),
        h("div", { class: "dugmeler" }, h("button", { class: "dugme ana" }, "Kaydet (F2)"),
          cari ? h("button", { type: "button", class: "dugme", onclick: () => cariEkstreAc(cari) }, "Cari Ekstre") : null,
          cari ? h("button", { type: "button", class: "dugme", onclick: () => yazdirAc(`/api/yazdir/mutabakat/${cari.id}`) }, "Mutabakat mektubu") : null,
          cari ? h("button", { type: "button", class: "dugme", onclick: () => yazdirAc(`/api/yazdir/cek-bordro?cari_id=${cari.id}`) }, "Çek bordrosu") : null,
          cari ? h("button", { type: "button", class: "dugme", onclick: () => cariHizliHareket(cari.id, "giris") }, "Tahsilat al") : null,
          cari ? h("button", { type: "button", class: "dugme", onclick: () => cariHizliHareket(cari.id, "cikis") }, "Ödeme yap") : null));
      el.append(form);
      this.form = form;
      $("input", form).focus();
    },
    async kaydet() {
      if (!this.form.reportValidity()) return;
      try {
        const v = formVerisi(this.form, ["vade_gun"]);
        if (!cari) {  // aynı VKN'li ya da benzer adlı cari varsa önce sorulur
          const benzer = await benzerCariKontrol(v.unvan, v.vkn);
          if (!benzer) return;
          if (benzer !== "yeni") {
            sekmeKapat(s);
            return cariFormAc((await api("/api/cariler").catch(() => [])).find((x) => x.id === benzer.id) || benzer);
          }
        }
        const kayit = cari ? await api(`/api/cariler/${cari.id}`, { metod: "PUT", veri: v }) : await api("/api/cariler", { metod: "POST", veri: v });
        bildir("Cari kaydedildi.");
        sekmeKapat(s);
        listeyiTazele("cariler");
        return kayit;
      } catch (e) { bildir(e.message, true); }
    },
  });
}

function listeyiTazele(anahtar) {
  const s = sekmeler.find((x) => x.anahtar === anahtar);
  if (s && s === aktifSekme) yenidenCiz();
}

// ---------------------------------------------------------------- şantiyeler
function santiyeListesiAc() {
  sekmeAc("santiyeler", "Şantiyeler", listeEkrani({
    baslik: "Şantiyeler",
    kaynak: () => api("/api/santiyeler"),
    kolonlar: [
      { alan: "ad", baslik: "Şantiye" }, { alan: "durum", baslik: "Durum", deger: (s) => (s.durum === "aktif" ? "Aktif" : "Tamamlandı") },
      { alan: "baslangic", baslik: "Başlangıç", tip: "tarih" }, { alan: "bitis", baslik: "Bitiş", tip: "tarih" },
      { alan: "butce", baslik: "Bütçe", tip: "para" }, { alan: "adres", baslik: "Adres" },
    ],
    yeni: () => santiyeFormAc(), yeniYazi: "+ Yeni şantiye",
    ac: (x) => santiyeFormAc(x),
    sil: (x) => api(`/api/santiyeler/${x.id}`, { metod: "DELETE" }),
    toplu: [{ ad: "Seçilenleri sil", tehlikeli: true, islem: (sec) => topluSil(sec, "şantiye", (x) => x.ad, (x) => `/api/santiyeler/${x.id}`) }],
  }));
}

function santiyeFormAc(st = null) {
  const s = sekmeAc(st ? `santiye-${st.id}` : `santiye-yeni-${Date.now()}`, st ? st.ad : "Yeni Şantiye", {
    ciz(el) {
      const form = h("form", { class: "form-pencere", onsubmit: (e) => { e.preventDefault(); this.kaydet(); } },
        h("h2", {}, "Şantiye Kartı"),
        h("fieldset", {}, h("legend", {}, "Bilgiler"), h("div", { class: "alanlar" },
          alan("Şantiye adı", "ad", st?.ad, { zorunlu: true }),
          alan("Durum", "durum", st?.durum, { secenekler: [["aktif", "Aktif"], ["tamamlandi", "Tamamlandı"]] }),
          alan("Başlangıç", "baslangic", st?.baslangic, { tip: "date" }), alan("Bitiş", "bitis", st?.bitis, { tip: "date" }),
          alan("Bütçe (TL)", "butce", st?.butce, { tip: "number" }),
          alan("Adres", "adres", st?.adres, { cok_satir: true, genis: true }))),
        h("div", { class: "dugmeler" }, h("button", { class: "dugme ana" }, "Kaydet (F2)")));
      el.append(form);
      this.form = form;
    },
    async kaydet() {
      if (!this.form.reportValidity()) return;
      try {
        const v = formVerisi(this.form, ["butce"]);
        if (st) await api(`/api/santiyeler/${st.id}`, { metod: "PUT", veri: v });
        else await api("/api/santiyeler", { metod: "POST", veri: v });
        bildir("Şantiye kaydedildi.");
        sekmeKapat(s);
        listeyiTazele("santiyeler");
      } catch (e) { bildir(e.message, true); }
    },
  });
}

// ---------------------------------------------------------------- faturalar
function faturaListesiAc(yon) {
  const ad = yon === "gelen" ? "Alış Faturaları" : "Satış Faturaları";
  let durumFiltre = "";
  // Toplu atama (onaylı faturalar da): şantiye (yazınca yoksa açılır) ve gider türü
  const santiyeK = santiyeSecici();
  const giderS = h("select", {}, [["", "— Gider türü seçin —"], ...BEN.gider_turleri.map((g) => [g, g])].map(([d, m]) => h("option", { value: d }, m)));
  sekmeAc(`faturalar-${yon}`, ad, listeEkrani({
    baslik: ad,
    kaynak: () => api(`/api/faturalar?yon=${yon}${durumFiltre ? `&durum=${durumFiltre}` : ""}`),
    ustAlan: (yenile) => h("span", { style: "display:flex;gap:6px" },
      h("select", { onchange: (e) => { durumFiltre = e.target.value; yenile(); } },
        [["", "Tüm faturalar"], ["taslak", "Onay bekleyenler"], ["onayli", "Onaylılar"], ["iptal", "İptal edilenler"]].map(([d, m]) => h("option", { value: d, selected: d === durumFiltre }, m))),
      h("button", { class: "dugme", onclick: async () => {
        try {
          const taslaklar = await api(`/api/faturalar?yon=${yon}&durum=taslak`);
          if (!taslaklar.length) return bildir("Onay bekleyen fatura yok.");
          if (!confirm(`Onay bekleyen ${taslaklar.length} faturanın hepsi kontrol edilmeden onaylansın mı?`)) return;
          const r = await api("/api/faturalar/toplu-onayla", { metod: "POST", veri: { idler: taslaklar.map((f) => f.id) } });
          bildir(`${r.onaylanan} fatura onaylandı${r.hatalar.length ? `, ${r.hatalar.length} fatura onaylanamadı: ${r.hatalar[0]}` : ""}.`, !!r.hatalar.length);
          yenile();
        } catch (e) { bildir(e.message, true); }
      } }, "Bekleyenlerin hepsini onayla")),
    kolonlar: [
      { alan: "durum", baslik: "Durum", deger: (f) => h("span", { class: `etiket ${f.durum}` }, DURUM_ADI[f.durum] || f.durum), metin: (f) => DURUM_ADI[f.durum] || f.durum },
      { alan: "tarih", baslik: "Tarih", tip: "tarih" }, { alan: "fatura_no", baslik: "Fatura No" },
      { alan: "cari_unvan", baslik: "Cari", metin: (f) => f.cari_unvan || f.ai_okuma?.[yon === "gelen" ? "satici" : "alici"]?.unvan || "" ,
        deger: (f) => f.cari_unvan || (f.ai_okuma ? `(yeni) ${f.ai_okuma[yon === "gelen" ? "satici" : "alici"]?.unvan || ""}` : "") },
      { alan: "santiye_ad", baslik: "Şantiye" }, { alan: "gider_turu", baslik: "Gider Türü" },
      { alan: "ara_toplam", baslik: "Ara Toplam", tip: "para" }, { alan: "kdv_toplam", baslik: "KDV", tip: "para" },
      { alan: "genel_toplam", baslik: "Genel Toplam", tip: "para" },
    ],
    toplamlar: ["ara_toplam", "kdv_toplam", "genel_toplam"],
    yeni: () => faturaFormAc(null, yon),
    ac: (f) => faturaFormAc(f, yon),
    silSorarak: (f) => faturalariSil([f]),
    toplu: [{ ad: "Seçilenlere ata", ek: h("span", { style: "display:inline-flex;gap:6px" }, santiyeK, giderS), islem: async (sec) => {
        const veri = { idler: sec.map((f) => f.id), santiye_id: Number(santiyeK.secim.value) || null, gider_turu: giderS.value || null };
        if (!veri.santiye_id && !veri.gider_turu) { bildir("Şantiye ya da gider türü seçin.", true); return false; }
        const r = await api("/api/faturalar/toplu-guncelle", { metod: "POST", veri });
        bildir(`${r.guncellenen} faturaya${veri.santiye_id ? " ve tüm kalemlerine" : ""} atandı.`);
      } },
      { ad: "Seçilenleri sil", tehlikeli: true, islem: (sec) => faturalariSil(sec) }],
    excel: "/api/excel/faturalar",
  }));
}

/** Seçilen faturaları siler. Onaylı fatura varsa cari bakiyesinden, şantiye/KDV/tevkifat raporlarından düşeceği
 * söylenir ve yanlışlıkla silmeye karşı "SİL" yazılması istenir. */
async function faturalariSil(sec) {
  const onayli = sec.filter((f) => f.durum === "onayli");
  const toplam = sec.reduce((t, f) => t + (f.genel_toplam || 0), 0);
  let soru = `Seçilen ${sec.length} fatura (toplam ${para(toplam)} TL) silinsin mi?`;
  if (onayli.length) {
    soru += `\n\n${onayli.length} tanesi ONAYLI. Silinince cari bakiyelerinden, şantiye, KDV ve tevkifat raporlarından düşer. ` +
      "Bu işlem geri alınamaz.\n\nOnaylamak için SİL yazın:";
    const cevap = prompt(soru);
    if (cevap == null) return false;
    if (cevap.trim().toLocaleUpperCase("tr") !== "SİL") { bildir("Silinmedi: onay için SİL yazılmadı.", true); return false; }
  } else if (!confirm(soru)) return false;
  const r = await api("/api/faturalar/toplu-sil", { metod: "POST", veri: { idler: sec.map((f) => f.id), onaylilar_dahil: onayli.length > 0 } });
  bildir(`${r.silinen} fatura silindi.`);
  listeyiTazele("cariler");
}

// Seçilenleri tek tek siler; bağlı kaydı olan (faturası, hareketi var) sunucuda silinmez, nedeni listelenir.
async function topluSil(sec, tur, ad, yol) {
  if (!confirm(`Seçilen ${sec.length} ${tur} silinsin mi? Bu işlem geri alınamaz.\n\nFaturası, çeki ya da hareketi olanlar silinmez.`)) return false;
  let silinen = 0;
  const kalan = [];
  for (const x of sec) {
    try { await api(yol(x), { metod: "DELETE" }); silinen++; } catch (e) { kalan.push(`${ad(x)}: ${e.message}`); }
  }
  bildir(`${silinen} ${tur} silindi.` + (kalan.length ? ` ${kalan.length} tanesi silinmedi.` : ""), kalan.length > 0);
  if (kalan.length) alert(`Silinmeyenler:\n\n${kalan.slice(0, 15).join("\n")}${kalan.length > 15 ? `\n… ve ${kalan.length - 15} kayıt daha` : ""}`);
  for (const l of ["cariler", "santiyeler", "banka-hesaplari", "kasa"]) listeyiTazele(l);
}

async function hareketleriSil(sec) {
  if (!confirm(`Seçilen ${sec.length} hareket silinsin mi?` + (sec.length > 1 ? "\n\nSilmeden önce otomatik yedek alınır." : ""))) return false;
  try {
    const r = await api("/api/hareketler/toplu-sil", { metod: "POST", veri: { idler: sec.map((x) => x.id) } });
    bildir(`${r.silinen} hareket silindi.` + (r.silinmeyen.length ? ` ${r.silinmeyen.length} çek hareketi silinmedi.` : ""));
  } catch (e) { bildir(e.message, true); return false; }
  for (const l of ["cariler", "banka-hesaplari", "kasa"]) listeyiTazele(l);
}

// Türkçe karakter/büyük harf farkı gözetmeden arama anahtarı ("İnşaat" -> "insaat")
const aramaAnahtari = (m) => String(m ?? "").toLocaleLowerCase("tr").replace(/[ıçğöşü]/g, (c) => "icgosu"["ıçğöşü".indexOf(c)])
  .normalize("NFKD").replace(/[^a-z0-9 ]/g, " ").replace(/\s+/g, " ").trim();

// Seçenekli sorulu pencere: secenekler [[deger, yazi, ana?]]; seçilen değer, kapatılırsa null döner.
function secimSor(baslik, icerik, secenekler) {
  return new Promise((coz) => {
    const d = h("dialog", { class: "secim-penceresi" }, h("h3", {}, baslik), h("div", {}, icerik),
      h("div", { class: "dugmeler" }, secenekler.map(([deger, yazi, ana]) =>
        h("button", { type: "button", class: `dugme${ana ? " ana" : ""}`, onclick: () => { d.close(); coz(deger); } }, yazi))));
    d.addEventListener("cancel", () => coz(null));
    d.addEventListener("close", () => setTimeout(() => d.remove(), 0));
    document.body.append(d);
    d.showModal();
  });
}

// Yeni cari açılmadan önce aynı VKN'li ya da benzer adlı cari var mı? Seçilen var olan cari, "yeni" ya da null (vazgeç).
async function benzerCariKontrol(unvan, vkn = "") {
  let benzerler = [];
  try { benzerler = await api(`/api/cariler/benzer?unvan=${encodeURIComponent(unvan)}&vkn=${encodeURIComponent(vkn || "")}`); } catch { /* kontrol yapılamazsa açılır */ }
  if (!benzerler.length) return "yeni";
  const yazi = (c) => `${c.unvan}${c.vkn ? ` (VKN ${c.vkn})` : ""}`;
  const ayniVkn = benzerler.find((c) => c.ayni_vkn);
  if (ayniVkn) {
    await secimSor("Bu VKN ile cari zaten var", `${yazi(ayniVkn)} seçilecek; aynı VKN ile ikinci cari açılmaz.`, [["tamam", "Tamam", true]]);
    return ayniVkn;
  }
  const tek = benzerler.length === 1;
  const sec = await secimSor("Benzer cari var",
    tek ? `Benzer cari var: ${yazi(benzerler[0])}. Onu mu seçmek istersiniz?`
      : h("div", {}, "Benzer cariler var. Birini mi seçmek istersiniz?", h("ul", {}, benzerler.map((c) => h("li", {}, yazi(c))))),
    [...benzerler.map((c, i) => [i, tek ? "Onu seç" : `Seç: ${c.unvan}`, i === 0]), ["yeni", `Yine de yeni aç: ${unvan}`], [null, "Vazgeç"]]);
  return sec === "yeni" ? "yeni" : sec == null ? null : benzerler[sec];
}

// Açılır listeyi yazarak aranan kutuya çevirir: yazdıkça seçenekler süzülür; listede yoksa en altta
// "yeni aç" satırı çıkar. Değer gizli <select>'te kalır (form aynı çalışır). sel.tazele() görünen yazıyı günceller.
function aramaliSec(sel, { yeniYazi, yeniAc, bosYazi = "", yeniIpucu } = {}) {
  const kutu = h("input", { type: "text", class: "arama-kutu", autocomplete: "off", placeholder: "Yazarak arayın…" });
  const liste = h("div", { class: "arama-liste", hidden: true });
  const sarici = h("span", { class: "arama-sec" }, kutu, liste);
  sel.hidden = true;
  sel.after(sarici);
  const gercek = () => [...sel.options].filter((o) => o.value && !o.value.startsWith("__"));
  const tazele = () => { const o = sel.selectedOptions[0]; kutu.value = o && o.value && !o.value.startsWith("__") ? o.textContent : ""; kutu.placeholder = (o && !o.value && o.textContent) || bosYazi || "Yazarak arayın…"; };
  sel.tazele = tazele;
  sel.addEventListener("change", tazele);
  let satirlar = [], imlec = 0;
  const sec = (deger) => { sel.value = String(deger); sel.dispatchEvent(new Event("change", { bubbles: true })); liste.hidden = true; tazele(); };
  const ciz = () => {
    const aranan = aramaAnahtari(kutu.value);
    const kelimeler = aranan.split(" ").filter(Boolean);
    const uyan = gercek().filter((o) => { const a = aramaAnahtari(o.textContent); return kelimeler.every((k) => a.includes(k)); });
    satirlar = uyan.slice(0, 50).map((o) => ({ yazi: o.textContent, islem: () => sec(o.value) }));
    const ad = kutu.value.trim();
    if (ad && yeniAc && !uyan.some((o) => aramaAnahtari(o.textContent.split(" · ")[0]) === aranan)) {
      satirlar.push({ yazi: yeniYazi(ad), yeni: true, islem: async () => {
        liste.hidden = true;
        const id = await yeniAc(ad);
        if (id != null) sec(id); else tazele();
      } });
    }
    imlec = Math.min(imlec, Math.max(satirlar.length - 1, 0));
    // Kutu boşken yeni kaydın nasıl açılacağı da görünsün
    const ipucu = !ad && yeniAc ? [h("div", { class: "bos" }, yeniIpucu || "Yeni kayıt için adını yazın")] : [];
    liste.replaceChildren(...(satirlar.length ? satirlar.map((x, i) => h("div", { class: `${x.yeni ? "yeni" : ""}${i === imlec ? " secili" : ""}`,
      onmousedown: (e) => { e.preventDefault(); x.islem(); } }, x.yazi)) : ipucu.length ? [] : [h("div", { class: "bos" }, "Eşleşen kayıt yok")]), ...ipucu);
    liste.hidden = false;
    liste.querySelector(".secili")?.scrollIntoView({ block: "nearest" });
  };
  kutu.addEventListener("focus", () => { kutu.select(); imlec = 0; ciz(); });
  kutu.addEventListener("input", () => { imlec = 0; ciz(); });
  kutu.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); imlec = Math.max(0, Math.min(satirlar.length - 1, imlec + (e.key === "ArrowDown" ? 1 : -1))); ciz(); }
    else if (e.key === "Enter") { e.preventDefault(); if (!liste.hidden && satirlar[imlec]) satirlar[imlec].islem(); }
    else if (e.key === "Escape" && !liste.hidden) { e.preventDefault(); e.stopPropagation(); liste.hidden = true; tazele(); }
  });
  kutu.addEventListener("blur", () => {
    liste.hidden = true;
    if (!kutu.value.trim() && sel.value) sec("");
    else tazele();
  });
  tazele();
  return kutu;
}

// Toplu atama için şantiye seçici: yazarak aranır, yoksa yazılan adla şantiye açılıp seçilir. Değer kap.secim.value
function santiyeSecici(santiyeler, bosYazi = "— Şantiye seçin —") {
  const sel = h("select", {}, h("option", { value: "" }, bosYazi));
  const kap = h("span", { class: "santiye-secici" }, sel);
  kap.secim = sel;
  const doldur = (liste) => { for (const x of liste) sel.append(h("option", { value: x.id }, x.ad)); sel.tazele?.(); };
  aramaliSec(sel, { yeniYazi: (ad) => `+ "${ad}" adıyla yeni şantiye aç`, bosYazi, yeniIpucu: "Yeni şantiye için adını yazın",
    yeniAc: async (ad) => {
      try {
        const st = await api("/api/santiyeler", { metod: "POST", veri: { ad } });
        const vardi = [...sel.options].some((o) => o.value === String(st.id));
        if (!vardi) sel.append(h("option", { value: st.id }, st.ad));
        listeyiTazele("santiyeler");
        bildir(vardi ? `'${st.ad}' şantiyesi zaten vardı, o seçildi.` : `'${st.ad}' şantiyesi açıldı ve seçildi.`);
        return st.id;
      } catch (e) { bildir(e.message, true); return null; }
    } });
  if (santiyeler) doldur(santiyeler); else api("/api/santiyeler").then(doldur).catch(() => {});
  return kap;
}

/** Formlarda şantiye alanı: listeden seçilir, yazarak aranır, yoksa yazılan adla açılır (fatura ekranıyla aynı). */
function santiyeAlani(etiket, deger, santiyeler, bosYazi = "— Şantiye yok —") {
  const kap = santiyeSecici(santiyeler, bosYazi);
  kap.secim.name = "santiye_id";
  kap.secim.value = deger ?? "";
  kap.secim.tazele?.();
  return h("label", {}, etiket, kap);
}

async function secenekleriGetir() {
  const [cariler, santiyeler] = await Promise.all([api("/api/cariler"), api("/api/santiyeler")]);
  return { cariler, santiyeler };
}

// e-Fatura tipleri; İade faturası raporlarda karşı tarafı azaltır (müşteriden gelen iade satışı, bizim kestiğimiz alışı)
const FATURA_TIPLERI = [["", "—"], ["SATIS", "Satış (normal)"], ["IADE", "İade"], ["TEVKIFAT", "Tevkifat"], ["ISTISNA", "İstisna"],
  ["IHRACKAYITLI", "İhraç kayıtlı"], ["OZELMATRAH", "Özel matrah"]];

// Okunan faturada yazan KDV / ödenecek tutar kayıttaki (kalemlerden hesaplanan) tutarı tutmuyor mu?
const toplamTutmuyor = (f) => {
  const o = f.ai_okuma || {};
  return (o.kdv_toplam != null && Math.abs(f.kdv_toplam - o.kdv_toplam) > 0.05)
    || (o.genel_toplam != null && Math.abs(f.genel_toplam - o.genel_toplam) > 0.05);
};

const DURUM_ADI = { taslak: "Taslak", onayli: "Onaylı", iptal: "İptal" };

/** Kayıtlı fatura/hareket: sil yerine "İptal et" (bakiyeden düşer, kaydı kalır), "İptali geri al" ve "Geçmiş". */
function kayitDugmeleri(tur, x, ad, yenile) {
  if (!x.id) return [];
  const yol = `/api/${tur === "fatura" ? "faturalar" : "hareketler"}/${x.id}`;
  const calistir = async (ek, veri, mesaj) => {
    try { await api(`${yol}/${ek}`, { metod: "POST", veri }); bildir(mesaj); kapatVeYenile(); yenile(); } catch (e) { bildir(e.message, true); }
  };
  return [
    x.durum === "onayli" ? h("button", { type: "button", class: "dugme", title: "Silmeden iptal: bakiyeden ve raporlardan düşer, kaydı ve geçmişi kalır", onclick: () => {
      const neden = prompt(`${ad} iptal edilecek. Bakiyeden ve raporlardan düşer, kaydı ve geçmişi kalır.\n\nİptal nedeni:`)?.trim();
      if (neden) calistir("iptal", { neden }, `${ad} iptal edildi.`);
    } }, "İptal et") : null,
    x.durum === "iptal" ? h("button", { type: "button", class: "dugme", onclick: () => calistir("iptal-geri", undefined, "İptal geri alındı.") }, "İptali geri al") : null,
    h("button", { type: "button", class: "dugme", onclick: () => gecmisAc(tur, x.id, ad) }, "Geçmiş"),
  ];
}
function kapatVeYenile() { if (aktifSekme) sekmeKapat(aktifSekme); }

function gecmisAc(tablo, kayitId, ad) {
  const q = new URLSearchParams();
  if (tablo) q.set("tablo", tablo);
  if (kayitId) q.set("kayit_id", kayitId);
  sekmeAc(`gecmis-${tablo || ""}-${kayitId || ""}`, ad ? `Geçmiş: ${ad}` : "Değişiklik Geçmişi", listeEkrani({
    baslik: ad ? `Geçmiş: ${ad}` : "Değişiklik Geçmişi",
    kaynak: () => api(`/api/gecmis?${q}`),
    kolonlar: [
      { alan: "zaman", baslik: "Zaman", deger: (x) => new Date(x.zaman).toLocaleString("tr-TR"), metin: (x) => new Date(x.zaman).toLocaleString("tr-TR") },
      { alan: "kullanici", baslik: "Kim" },
      { alan: "tablo", baslik: "Kayıt", deger: (x) => GECMIS_TABLO[x.tablo] || x.tablo, metin: (x) => GECMIS_TABLO[x.tablo] || x.tablo },
      { alan: "islem", baslik: "İşlem", deger: (x) => GECMIS_ISLEM[x.islem] || x.islem, metin: (x) => GECMIS_ISLEM[x.islem] || x.islem },
      { alan: "ozet", baslik: "Ne değişti" },
    ],
    ac: (x) => (x.islem !== "silindi" && x.tablo === "fatura" ? faturaFormAc({ id: x.kayit_id }, null) : null),
  }));
}
const GECMIS_TABLO = { fatura: "Fatura", hareket: "Para hareketi", cek: "Çek/Senet", cari: "Cari", banka_hesabi: "Banka hesabı" };
const GECMIS_ISLEM = { eklendi: "Eklendi", degisti: "Değişti", onaylandi: "Onaylandı", iptal: "İptal edildi", iptal_geri: "İptal geri alındı", silindi: "Silindi" };

function faturaFormAc(fatura, yon) {
  const baslik = fatura ? `Fatura ${fatura.fatura_no || "#" + fatura.id}` : yon === "gelen" ? "Yeni Alış Faturası" : "Yeni Satış Faturası";
  const s = sekmeAc(fatura ? `fatura-${fatura.id}` : `fatura-yeni-${Date.now()}`, baslik, {
    async ciz(el) {
      if (fatura) { try { fatura = await api(`/api/faturalar/${fatura.id}`); } catch (e) { return bildir(e.message, true); } }
      const { cariler, santiyeler } = await secenekleriGetir();
      const f = fatura || { yon, kalemler: [], tevkifat: 0, stopaj: 0, para_birimi: "TRY" };
      if (!fatura && yon === "giden") {  // yeni satış faturasına sıradaki numarayı öner
        try { f.fatura_no = (await api("/api/faturalar/sonraki-no?yon=giden")).fatura_no; } catch { /* öneri yoksa boş kalır */ }
      }
      const okuyan = f.ai_okuma?.okuma_yontemi ? `Fatura ${f.ai_okuma.okuma_yontemi} üzerinden yapay zekasız okundu` : "Yapay zeka bu faturayı okudu";
      const karsi = f.ai_okuma?.[f.yon === "gelen" ? "satici" : "alici"];
      const form = h("form", { class: "form-pencere", onsubmit: (e) => { e.preventDefault(); this.kaydet(); } });

      const uyarilar = (f.ai_okuma?.uyarilar || []).filter((u) => u && !(u.startsWith("Firmanın adı") && !/^VKN \d+$/.test(f.cari_unvan || "")));
      if (f.durum === "taslak" && f.ai_okuma) {
        form.append(h("div", { class: "uyari-kutu" }, h("b", {}, `${okuyan}. Kontrol edip onaylayın.`),
          uyarilar.length ? h("ul", {}, uyarilar.map((u) => h("li", {}, u))) : null));
      }
      const cariSecenek = [["", karsi?.unvan ? `(Yeni cari açılacak: ${karsi.unvan})` : "— Cari seçin —"], ...cariler.map((c) => [c.id, `${c.unvan}${c.vkn ? " · " + c.vkn : ""}`])];
      form.append(
        h("h2", {}, f.yon === "gelen" ? "Alış Faturası" : "Satış Faturası", f.durum ? " · " : "", f.durum ? h("span", { class: `etiket ${f.durum}` }, DURUM_ADI[f.durum] || f.durum) : null),
        f.durum === "iptal" ? h("div", { class: "uyari-satiri hata" }, `İptal edildi: ${f.iptal_nedeni || ""}. Bakiyede ve raporlarda yer almaz; değiştirmek için önce iptali geri alın.`) : "",
        h("fieldset", {}, h("legend", {}, "Fatura Bilgileri"), h("div", { class: "alanlar" },
          alan("Cari", "cari_id", f.cari_id, { secenekler: cariSecenek, genis: true }),
          alan("Fatura No", "fatura_no", f.fatura_no), alan("Tarih", "tarih", f.tarih, { tip: "date" }),
          alan("Vade", "vade", f.vade, { tip: "date" }),
          alan("Şantiye", "santiye_id", f.santiye_id, { secenekler: [["", "— Şantiye yok —"], ...santiyeler.map((x) => [x.id, x.ad]), ["__yeni_santiye", "+ Yeni şantiye…"]] }),
          alan("Gider Türü", "gider_turu", f.gider_turu, { secenekler: [["", "—"], ...BEN.gider_turleri.map((g) => [g, g])] }),
          alan("Para Birimi", "para_birimi", f.para_birimi),
          alan("Kur (dövizli faturada 1 birim kaç TL)", "kur", f.kur, { tip: "number" }),
          alan("Fatura Tipi", "fatura_tipi", f.fatura_tipi, { secenekler: FATURA_TIPLERI.some(([d]) => d === (f.fatura_tipi || "")) ? FATURA_TIPLERI
            : [...FATURA_TIPLERI, [f.fatura_tipi, f.fatura_tipi]] }),
          alan("Tevkifat", "tevkifat", f.tevkifat, { tip: "number" }),
          alan("Stopaj (gelir/kurumlar vergisi)", "stopaj", f.stopaj || 0, { tip: "number" }),
          alan("Diğer vergiler (konaklama, ÖTV…)", "diger_vergiler", f.diger_vergiler || 0, { tip: "number" }),
          alan("Yuvarlama farkı (faturadaki)", "yuvarlama", f.yuvarlama || 0, { tip: "number" }),
          alan("Açıklama", "aciklama", f.aciklama, { genis: true }))));

      // Döviz faturası: kur faturada yazmıyorsa fatura tarihindeki TCMB döviz alış kuru getirilir (internet yoksa elle girilir)
      const kurAlani = form.elements.kur, kurNotu = h("small", { class: "kur-notu" });
      const kurDugmesi = h("button", { type: "button", class: "dugme kucuk", onclick: () => tcmbKuru(false) }, "TCMB kurunu getir");
      kurAlani.closest("label").append(h("span", { class: "kur-satiri" }, kurDugmesi, kurNotu));
      const dovizMi = () => !["TRY", "TL", ""].includes((form.elements.para_birimi.value || "").trim().toUpperCase());
      const kurGorunum = () => { kurDugmesi.hidden = !dovizMi(); if (!dovizMi()) kurNotu.textContent = ""; };
      const tcmbKuru = async (sessiz) => {
        const tarih = form.elements.tarih.value;
        if (!tarih) { if (!sessiz) bildir("Önce fatura tarihini girin.", true); return; }
        kurNotu.textContent = "TCMB kuru getiriliyor…";
        try {
          const r = await api(`/api/faturalar/tcmb-kuru?para=${encodeURIComponent(form.elements.para_birimi.value.trim())}&tarih=${tarih}`);
          kurAlani.value = r.kur; kurNotu.textContent = r.aciklama;
          kurAlani.dispatchEvent(new Event("input"));
        } catch (e) { kurNotu.textContent = sessiz ? "Kuru girin." : e.message; }
      };
      if (f.ai_okuma?.kur && !f.kur) kurAlani.value = f.ai_okuma.kur;  // okunan kur alana yazılmamış eski kayıt
      if (f.ai_okuma?.kur && Number(kurAlani.value) === Number(f.ai_okuma.kur)) kurNotu.textContent = "Faturada yazan kur";
      form.elements.para_birimi.addEventListener("input", kurGorunum);
      kurGorunum();
      if (dovizMi() && !Number(kurAlani.value) && f.durum !== "onayli") tcmbKuru(true);

      // Cari fatura ekranından düzeltilir ya da açılır; Cari Listesi'ndeki aynı kayıt güncellenir (kopya oluşmaz).
      const cariS = form.elements.cari_id;
      const cariSecenegiYaz = (kayit) => {
        const i = cariler.findIndex((x) => x.id === kayit.id);
        if (i >= 0) cariler[i] = kayit; else cariler.push(kayit);
        const secenek = [...cariS.options].find((o) => o.value === String(kayit.id)) || cariS.appendChild(h("option", { value: kayit.id }));
        secenek.textContent = `${kayit.unvan}${kayit.vkn ? " · " + kayit.vkn : ""}`;
        cariS.value = String(kayit.id);
        cariS.tazele?.();
        listeyiTazele("cariler");
      };
      // Yeni cari: önce aynı VKN'li / benzer adlı cari aranır, kullanıcı onu seçebilir ya da yine de yeni açar.
      const yeniCariAc = async (unvan, bilgi = {}) => {
        const benzer = await benzerCariKontrol(unvan, bilgi.vkn);
        if (!benzer) return null;
        try {
          if (benzer !== "yeni") {
            cariSecenegiYaz(cariler.find((x) => x.id === benzer.id) || benzer);
            bildir(`'${benzer.unvan}' carisi seçildi.`);
            return benzer.id;
          }
          const kayit = await api("/api/cariler", { metod: "POST", veri: { ...bilgi, unvan, tur: f.yon === "gelen" ? "tedarikci" : "musteri" } });
          const vardi = cariler.some((x) => x.id === kayit.id);
          cariSecenegiYaz(kayit);
          bildir(vardi ? `'${kayit.unvan}' carisi zaten vardı, o seçildi.` : `'${kayit.unvan}' carisi açıldı ve faturaya seçildi. VKN ve adresini "Cariyi düzenle"den ekleyebilirsiniz.`);
          return kayit.id;
        } catch (e) { bildir(e.message, true); return null; }
      };
      aramaliSec(cariS, { yeniYazi: (ad) => `+ "${ad}" adıyla yeni cari aç`, yeniAc: yeniCariAc, yeniIpucu: "Yeni cari için adını yazın" });
      // Vade boşsa fatura tarihi + carinin vade günüyle doldurulur
      const vadeDoldur = () => {
        const c = cariler.find((x) => String(x.id) === cariS.value), { tarih: t, vade } = form.elements;
        if (!c?.vade_gun || !t.value || vade.value) return;
        const g = new Date(t.value + "T00:00:00"); g.setDate(g.getDate() + Number(c.vade_gun));
        vade.value = `${g.getFullYear()}-${String(g.getMonth() + 1).padStart(2, "0")}-${String(g.getDate()).padStart(2, "0")}`;
      };
      cariS.addEventListener("change", vadeDoldur);
      form.elements.tarih.addEventListener("change", vadeDoldur);
      if (f.durum !== "onayli") vadeDoldur();
      const cariPanel = h("fieldset", { hidden: true });
      const cariPaneliAc = (c) => {
        const g = (etiket, deger, genis) => {
          const i = h("input", { value: deger ?? "" });
          return [i, h("label", { class: genis ? "genis" : "" }, etiket, i)];
        };
        const [unvanI, unvanL] = g("Ünvan", c ? c.unvan : karsi?.unvan, true);
        const [vknI, vknL] = g("VKN/TCKN", c ? c.vkn : karsi?.vkn);
        const [vdI, vdL] = g("Vergi Dairesi", c?.vergi_dairesi);
        const [adresI, adresL] = g("Adres", c?.adres, true);
        const kaydet = async () => {
          if (!unvanI.value.trim()) return bildir("Ünvan boş olamaz.", true);
          const v = { unvan: unvanI.value.trim(), vkn: vknI.value.trim() || null, vergi_dairesi: vdI.value.trim() || null,
            adres: adresI.value.trim() || null };
          if (!c) {
            const kayit = await yeniCariAc(v.unvan, v);
            if (kayit != null) cariPanel.hidden = true;
            return;
          }
          try {
            cariSecenegiYaz(await api(`/api/cariler/${c.id}`, { metod: "PUT", veri: { ...c, ...v } }));
            cariPanel.hidden = true;
            bildir("Cari güncellendi; tüm faturalarında yeni bilgiler görünür.");
          } catch (e) { bildir(e.message, true); }
        };
        cariPanel.replaceChildren(h("legend", {}, c ? "Cariyi düzenle" : "Yeni cari"), h("div", { class: "alanlar" }, unvanL, vknL, vdL, adresL),
          h("div", { class: "dugmeler" }, h("button", { type: "button", class: "dugme ana", onclick: kaydet }, "Cariyi kaydet"),
            h("button", { type: "button", class: "dugme", onclick: () => (cariPanel.hidden = true) }, "Vazgeç")));
        cariPanel.hidden = false;
        unvanI.focus();
      };
      // Yeni şantiye: ad yazılır, Şantiyeler'e kaydedilir ve faturaya seçilir (aynı adlı varsa o seçilir)
      const santiyePanel = h("fieldset", { class: "cari-panel", hidden: true });
      const santiyePaneliAc = () => {
        const adI = h("input", { placeholder: "Şantiye adı" });
        const kaydet = async () => {
          const ad = adI.value.trim();
          if (!ad) return bildir("Şantiye adını yazın.", true);
          const id = await santiyeAc(ad);
          if (id == null) return;
          form.elements.santiye_id.value = String(id);
          form.elements.santiye_id.dispatchEvent(new Event("change", { bubbles: true }));
          form.elements.santiye_id.tazele?.();
          santiyePanel.hidden = true;
        };
        adI.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); kaydet(); } });
        santiyePanel.replaceChildren(h("legend", {}, "Yeni şantiye"), h("div", { class: "alanlar" }, h("label", { class: "genis" }, "Şantiye adı", adI)),
          h("div", { class: "liste-ust" }, h("button", { type: "button", class: "dugme ana", onclick: kaydet }, "Şantiyeyi kaydet ve seç"),
            h("button", { type: "button", class: "dugme", onclick: () => (santiyePanel.hidden = true) }, "Vazgeç")));
        santiyePanel.hidden = false;
        adI.focus();
      };
      form.append(h("div", { class: "liste-ust", style: "margin:-4px 0 8px" },
        h("button", { type: "button", class: "dugme", title: "Seçili carinin adını, VKN'sini, adresini düzeltin",
          onclick: () => cariPaneliAc(cariler.find((x) => String(x.id) === cariS.value) || null) }, "✎ Cariyi düzenle"),
        h("button", { type: "button", class: "dugme", onclick: () => cariPaneliAc(null) }, "+ Yeni cari"),
        h("span", { class: "arac-ayrac", style: "align-self:stretch" }),
        h("button", { type: "button", class: "dugme", title: "Yeni şantiye açar ve bu faturaya seçer", onclick: () => santiyePaneliAc() }, "+ Yeni şantiye")),
      cariPanel, santiyePanel);

      const kalemGovde = h("tbody");
      const toplamAlan = h("div", { class: "toplamlar" });
      const farkKutu = h("div", { class: "hata-kutu", hidden: true });
      const kalemSantiye = [["", "— Fatura şantiyesi —"], ...santiyeler.map((x) => [x.id, x.ad]), ["__yeni_santiye", "+ Yeni şantiye…"]];
      // "+ Yeni şantiye…" seçilince ad sorulur, şantiye Şantiyeler'e kaydedilir ve tüm şantiye listelerine eklenip seçilir.
      // Aynı adlı şantiye varsa sunucu onu döndürür: ikinci kez eklenmez, var olan seçilir
      const santiyeAc = async (ad) => {
        try {
          const st = await api("/api/santiyeler", { metod: "POST", veri: { ad } });
          const vardi = kalemSantiye.some(([id]) => id === st.id);
          if (!vardi) {
            kalemSantiye.splice(kalemSantiye.length - 1, 0, [st.id, st.ad]);
            for (const x of form.querySelectorAll("select[name=santiye_id], select[data-a=santiye_id]")) {
              x.insertBefore(h("option", { value: st.id }, st.ad), [...x.options].find((o) => o.value === "__yeni_santiye"));
            }
          }
          listeyiTazele("santiyeler");
          bildir(vardi ? `'${st.ad}' şantiyesi zaten vardı, o seçildi.` : `'${st.ad}' şantiyesi açıldı ve seçildi.`);
          return st.id;
        } catch (err) { bildir(err.message, true); return null; }
      };
      aramaliSec(form.elements.santiye_id, { yeniYazi: (ad) => `+ "${ad}" adıyla yeni şantiye aç`, yeniAc: santiyeAc, bosYazi: "— Şantiye yok —", yeniIpucu: "Yeni şantiye için adını yazın" });
      form.addEventListener("change", async (e) => {
        const sec = e.target;
        if (sec.tagName !== "SELECT" || sec.value !== "__yeni_santiye") return;
        const onceki = sec.dataset.onceki ?? "";
        const ad = prompt("Yeni şantiyenin adı:")?.trim();
        const id = ad ? await santiyeAc(ad) : null;
        sec.value = id != null ? String(id) : onceki;
      });
      form.addEventListener("focusin", (e) => { if (e.target.tagName === "SELECT") e.target.dataset.onceki = e.target.value; });
      // Tevkifat: oran (onda kaç) ve KDVGUT kodu; değer "kod|oran" ("624|2"). Tutar = kalem KDV'si x oran.
      const tevkifatSecenekleri = [["", "Yok"],
        ...(BEN.tevkifat_kodlari || []).filter((t) => t.oran).sort((a, b) => a.oran - b.oran || a.kod.localeCompare(b.kod))
          .map((t) => [`${t.kod}|${t.oran}`, `${t.oran}/10 · ${t.kod} ${t.aciklama}`]),
        ...[2, 3, 4, 5, 7, 9, 10].map((o) => [`650|${o}`, `${o}/10 · 650 Diğerleri`])];
      const tevkifatSecimi = (k) => {
        const deger = Number(k.tevkifat_orani) ? `${k.tevkifat_kodu || ""}|${Number(k.tevkifat_orani)}` : "";
        const secenekler = tevkifatSecenekleri.some(([d]) => d === deger) ? tevkifatSecenekleri
          : [...tevkifatSecenekleri, [deger, `${Number(k.tevkifat_orani)}/10${k.tevkifat_kodu ? " · " + k.tevkifat_kodu : " (kodsuz)"}`]];
        return h("select", { "data-a": "tevkifat", style: "max-width:120px" }, secenekler.map(([d, m]) => h("option", { value: d, selected: d === deger }, m)));
      };
      // Standart kalem sütunları (her faturada aynı): Sıra No, Mal Hizmet Adı, Miktar, Birim, Birim Fiyat (liste),
      // İskonto Oranı, İskonto Tutarı, KDV Oranı, KDV Tutarı, Tevkifat, Mal Hizmet Tutarı (= miktar x fiyat - iskonto), Şantiye.
      const sayiAlan = (a, deger, ek = {}) => h("input", { "data-a": a, type: "number", step: "any", value: deger ?? "", ...ek });
      // Kayıtlı kalemin Mal Hizmet Tutarı faturadaki gibi korunur (miktar x fiyat kuruş tutmasa da);
      // miktar, fiyat ya da iskonto değiştirilirse tutar yeniden hesaplanır.
      const ILK_ALANLAR = ["miktar", "birim_fiyat", "iskonto_orani", "iskonto_tutari"];
      const kalemSatiri = (k = { aciklama: "", miktar: 1, birim: "", birim_fiyat: 0, kdv_orani: 20 }) => {
        const tr = h("tr", { "data-son": Number(k.iskonto_tutari) ? "tutar" : "oran" },
          h("td", { class: "sayi sira" }),
          h("td", {}, h("input", { "data-a": "aciklama", value: k.aciklama, style: "min-width:220px" })),
          h("td", {}, sayiAlan("miktar", k.miktar)),
          h("td", {}, h("input", { "data-a": "birim", value: k.birim ?? "", style: "width:60px" })),
          h("td", {}, sayiAlan("birim_fiyat", k.birim_fiyat, { title: "İskontosuz liste fiyatı" })),
          h("td", {}, sayiAlan("iskonto_orani", Number(k.iskonto_orani) || "", { style: "width:60px",
            oninput: () => { tr.dataset.son = "oran"; } })),
          h("td", {}, sayiAlan("iskonto_tutari", Number(k.iskonto_tutari) || "", { oninput: () => { tr.dataset.son = "tutar"; } })),
          h("td", {}, sayiAlan("kdv_orani", k.kdv_orani, { style: "width:55px" })),
          h("td", {}, sayiAlan("kdv_tutari", k.kdv_tutari, { "data-elle": k.kdv_tutari != null ? "1" : "",
            title: "Faturada yazan KDV tutarı farklıysa düzeltin; boş bırakılırsa oran x tutar",
            oninput: (e) => { e.target.dataset.elle = e.target.value === "" ? "" : "1"; } })),
          h("td", {}, tevkifatSecimi(k)),
          h("td", {}, sayiAlan("stopaj_orani", Number(k.stopaj_orani) || "", { style: "width:55px", title: "Gelir/kurumlar vergisi stopajı yüzdesi (ör. 5); tutar = KDV hariç tutar x oran" })),
          h("td", { class: "sayi tutar" }),
          h("td", {}, h("select", { "data-a": "santiye_id", title: "Fatura birden fazla şantiyeye aitse kalemin şantiyesini seçin" },
            kalemSantiye.map(([d, m]) => h("option", { value: d, selected: String(d) === String(k.santiye_id ?? "") }, m)))),
          h("td", {}, h("button", { type: "button", class: "dugme tehlike", title: "Satırı sil", onclick: () => { tr.remove(); hesapla(); } }, "✕")));
        tr.addEventListener("input", hesapla);
        if (k.tutar != null) tr.kayitliTutar = Number(k.tutar);
        kalemGovde.append(tr);
      };
      const yuvarla = (x) => Math.round(x * 100) / 100;
      const kalemleriOku = () => [...kalemGovde.rows].map((tr) => {
        const d = (a) => $(`[data-a=${a}]`, tr).value;
        const [tkod, tpay] = d("tevkifat").split("|");
        const miktar = Number(d("miktar")) || 0, birim_fiyat = Number(d("birim_fiyat")) || 0, brut = yuvarla(miktar * birim_fiyat);
        let iskonto_orani = Number(d("iskonto_orani")) || 0, iskonto_tutari = Number(d("iskonto_tutari")) || 0;
        if (tr.dataset.son === "tutar") iskonto_orani = brut && iskonto_tutari ? yuvarla(iskonto_tutari / brut * 100) : 0;
        else iskonto_tutari = yuvarla(brut * iskonto_orani / 100);
        const degismedi = tr.kayitliTutar != null && ILK_ALANLAR.map(d).join("|") === tr.ilkDegerler;
        return { aciklama: d("aciklama") || "-", miktar, birim: d("birim") || null, birim_fiyat, iskonto_orani, iskonto_tutari,
          tutar: degismedi ? tr.kayitliTutar : null,
          kdv_orani: Number(d("kdv_orani")) || 0, santiye_id: Number(d("santiye_id")) || null,
          tevkifat_orani: Number(tpay) || 0, tevkifat_kodu: tkod || null, stopaj_orani: Number(d("stopaj_orani")) || 0,
          kdv_tutari: $("[data-a=kdv_tutari]", tr).dataset.elle ? Number(d("kdv_tutari")) || 0 : null };
      });
      function hesapla() {
        let ara = 0, kdv = 0, satirTevk = 0, oranli = false, satirStop = 0, stopajli = false;
        const okunan = kalemleriOku();
        [...kalemGovde.rows].forEach((tr, i) => {
          const k = okunan[i];
          const tutar = k.tutar ?? yuvarla(yuvarla(k.miktar * k.birim_fiyat) - k.iskonto_tutari);
          // İskontonun oran ya da tutarından hangisi yazıldıysa öteki hesaplanır
          const diger = $(tr.dataset.son === "tutar" ? "[data-a=iskonto_orani]" : "[data-a=iskonto_tutari]", tr);
          if (document.activeElement !== diger) diger.value = (tr.dataset.son === "tutar" ? k.iskonto_orani : k.iskonto_tutari) || "";
          const kdvAlan = $("[data-a=kdv_tutari]", tr);
          const satirKdv = k.kdv_tutari ?? Math.round(tutar * k.kdv_orani) / 100;
          if (!kdvAlan.dataset.elle) kdvAlan.value = satirKdv;
          kdvAlan.classList.toggle("negatif", k.kdv_tutari != null && Math.abs(k.kdv_tutari - tutar * k.kdv_orani / 100) > 0.05);
          const tv = yuvarla(satirKdv * k.tevkifat_orani / 10);
          $("td.sira", tr).textContent = i + 1;
          $("td.tutar", tr).textContent = para(tutar);
          $("[data-a=tevkifat]", tr).title = k.tevkifat_orani ? `Tevkifat: ${para(tv)}` : "KDV tevkifatı yok";
          ara += tutar; kdv += satirKdv;
          if (k.tevkifat_orani) { oranli = true; satirTevk += tv; }
          const st = yuvarla(tutar * k.stopaj_orani / 100);
          $("[data-a=stopaj_orani]", tr).title = k.stopaj_orani ? `Stopaj: ${para(st)}` : "Stopaj yok (yüzde yazın, ör. 5)";
          if (k.stopaj_orani) { stopajli = true; satirStop += st; }
        });
        // Kalemlerde tevkifat seçildiyse faturanın tevkifatı satırların toplamıdır, elle yazılmaz.
        form.elements.tevkifat.readOnly = oranli;
        if (oranli) form.elements.tevkifat.value = Math.round(satirTevk * 100) / 100;
        const tevk = Number(form.elements.tevkifat.value) || 0;
        // Stopaj da öyle: kalemde oran yazıldıysa satırların toplamı; ödenecekten düşülür
        form.elements.stopaj.readOnly = stopajli;
        if (stopajli) form.elements.stopaj.value = Math.round(satirStop * 100) / 100;
        const stop = Number(form.elements.stopaj.value) || 0;
        // Yuvarlama: satıcının kendi kuruş farkı, diğer vergiler gibi genel toplama eklenir
        const diger = (Number(form.elements.diger_vergiler.value) || 0) + (Number(form.elements.yuvarlama.value) || 0);
        const yuv = Number(form.elements.yuvarlama.value) || 0;
        const pb = (form.elements.para_birimi.value || "TRY").trim().toUpperCase(), kur = Number(form.elements.kur.value) || 0;
        const doviz = pb !== "TRY" && pb !== "TL";
        toplamAlan.replaceChildren(h("span", {}, "Ara Toplam"), h("span", {}, para(ara)), h("span", {}, "KDV"), h("span", {}, para(kdv)),
          h("span", {}, "Tevkifat"), h("span", {}, para(tevk)), ...(stop ? [h("span", {}, "Stopaj"), h("span", {}, para(stop))] : []), ...(diger - yuv ? [h("span", {}, "Diğer vergiler"), h("span", {}, para(diger - yuv))] : []),
          ...(yuv ? [h("span", {}, "Yuvarlama"), h("span", {}, para(yuv))] : []),
          h("span", { class: "genel" }, `Genel Toplam${doviz ? ` (${pb})` : ""}`), h("span", { class: "genel" }, para(ara + kdv - tevk - stop + diger)),
          ...(doviz ? (kur ? [h("span", { class: "tl-karsiligi" }, `TL karşılığı (kur ${kur.toLocaleString("tr-TR", { maximumFractionDigits: 6 })})`), h("span", {}, ""),
            h("span", {}, "Ara Toplam (TL)"), h("span", {}, para(ara * kur)), h("span", {}, "KDV (TL)"), h("span", {}, para(kdv * kur)),
            ...(tevk ? [h("span", {}, "Tevkifat (TL)"), h("span", {}, para(tevk * kur))] : []),
            h("span", { class: "genel" }, "Genel Toplam (TL)"), h("span", { class: "genel" }, para((ara + kdv - tevk - stop + diger) * kur)),
            ...(f.ai_okuma?.tl_toplam && Math.abs((ara + kdv - tevk - stop + diger) * kur - f.ai_okuma.tl_toplam) > 1
              ? [h("span", { class: "negatif" }, "Faturada yazan TL"), h("span", { class: "negatif" }, para(f.ai_okuma.tl_toplam))] : [])]
            : [h("span", {}, "TL karşılığı"), h("span", { class: "negatif" }, "Kuru girin")]) : []));
        // Okunan faturanın KDV'si ve ödenecek tutarı kalemlerden hesaplananı tutmuyorsa kırmızı uyarı
        const o = f.ai_okuma || {};
        const farklar = [];
        if (o.kdv_toplam != null && Math.abs(kdv - o.kdv_toplam) > 0.05) farklar.push(`KDV ${para(kdv)} (faturada ${para(o.kdv_toplam)})`);
        if (o.genel_toplam != null && Math.abs(ara + kdv - tevk - stop + diger - o.genel_toplam) > 0.05)
          farklar.push(`ödenecek ${para(ara + kdv - tevk - stop + diger)} (faturada ${para(o.genel_toplam)})`);
        farkKutu.hidden = !farklar.length;
        farkKutu.textContent = `Hesaplanan tutarlar faturayı tutmuyor: ${farklar.join(", ")}. Kalemlerin KDV tutarlarını faturadaki gibi düzeltin.`;
      }
      for (const k of f.kalemler) kalemSatiri(k);
      if (!f.kalemler.length) kalemSatiri();
      form.elements.tevkifat.addEventListener("input", hesapla);
      form.elements.stopaj.addEventListener("input", hesapla);
      kalemGovde.addEventListener("change", hesapla);
      form.elements.diger_vergiler.addEventListener("input", hesapla);
      form.elements.yuvarlama.addEventListener("input", hesapla);
      form.elements.para_birimi.addEventListener("input", hesapla);
      form.elements.kur.addEventListener("input", hesapla);

      form.append(h("fieldset", {}, h("legend", {}, "Kalemler"),
        h("div", { class: "tablo-kap" }, h("table", { class: "liste kalemler" },
          h("thead", {}, h("tr", {}, ["Sıra No", "Mal Hizmet Adı", "Miktar", "Birim", "Birim Fiyat", "İskonto Oranı %", "İskonto Tutarı", "KDV Oranı %", "KDV Tutarı",
            "Tevkifat", "Stopaj %", "Mal Hizmet Tutarı", "Şantiye", ""].map((b) => h("th", {}, b)))), kalemGovde)),
        h("div", { class: "dugmeler" }, h("button", { type: "button", class: "dugme", onclick: () => { kalemSatiri(); hesapla(); } }, "+ Satır ekle")),
        farkKutu, toplamAlan));
      form.append(h("div", { class: "dugmeler" },
        h("button", { class: "dugme", disabled: f.durum === "iptal" }, "Kaydet (F2)"),
        f.id ? h("button", { type: "button", class: "dugme", onclick: () => yazdirAc(`/api/yazdir/fatura/${f.id}`) }, "Yazdır") : null,
        ...kayitDugmeleri("fatura", f, `Fatura ${f.fatura_no || ""}`.trim(), () => faturaFormAc({ id: f.id }, null)),
        f.id ? h("button", { type: "button", class: "dugme", title: "Aynı cari ve kalemlerle bugün tarihli yeni taslak", onclick: async () => {
          try { const kopya = await api(`/api/faturalar/${f.id}/kopyala`, { metod: "POST" }); bildir("Kopya taslak açıldı; tarih bugün, kontrol edip kaydedin."); faturaFormAc(kopya, null); }
          catch (e) { bildir(e.message, true); }
        } }, "Kopyala (yeni fatura)") : null,
        f.xml_dosya ? h("button", { type: "button", class: "dugme", onclick: () => indir(`/api/faturalar/${f.id}/belge?tur=xml`, `${f.fatura_no || f.id}.xml`) }, "XML'i indir") : null,
        f.id && f.durum === "taslak" ? h("button", { type: "button", class: "dugme ana", onclick: () => this.onayla() }, "Kaydet ve Onayla") : null));
      hesapla();
      // İlk hesaplamada iskontonun öteki alanı doldurulur; kalemin "değişmedi" sayılacağı değerler ondan sonra alınır.
      for (const tr of kalemGovde.rows) if (tr.kayitliTutar != null) tr.ilkDegerler = ILK_ALANLAR.map((a) => $(`[data-a=${a}]`, tr).value).join("|");
      hesapla();
      this.form = form;
      this.kalemleriOku = kalemleriOku;

      if (f.kaynak_dosya) {
        const onizleme = h("div", { class: "onizleme" });
        el.append(h("div", { class: "inceleme" }, onizleme, form));
        try {
          const blob = await api(`/api/faturalar/${f.id}/belge`);
          const url = URL.createObjectURL(blob);
          // e-Fatura HTML görüntüsü firmadan gelir; betik çalıştıramasın diye korumalı çerçevede açılır.
          onizleme.append(blob.type.startsWith("image/") ? h("img", { src: url, alt: "Fatura görseli" })
            : blob.type.includes("html") ? h("iframe", { src: url, title: "Fatura belgesi", sandbox: "", style: "background:#fff" })
            : h("iframe", { src: url, title: "Fatura belgesi" }));
        } catch { onizleme.append(h("p", { style: "color:#fff;padding:12px" }, "Belge açılamadı.")); }
      } else el.append(form);
    },
    async kaydet(sessiz = false) {
      if (!this.form?.reportValidity()) return;
      const v = formVerisi(this.form, ["cari_id", "santiye_id", "tevkifat", "stopaj", "diger_vergiler", "yuvarlama", "kur"]);
      v.tevkifat = v.tevkifat || 0;
      v.stopaj = v.stopaj || 0;
      v.diger_vergiler = v.diger_vergiler || 0;
      v.yuvarlama = v.yuvarlama || 0;
      v.para_birimi = v.para_birimi || "TRY";
      v.yon = fatura?.yon || yon;
      v.kalemler = this.kalemleriOku();
      try {
        fatura = fatura ? await api(`/api/faturalar/${fatura.id}`, { metod: "PUT", veri: v }) : await api("/api/faturalar", { metod: "POST", veri: v });
        if (!sessiz) { bildir("Fatura kaydedildi."); s.baslik = `Fatura ${fatura.fatura_no || "#" + fatura.id}`; yenidenCiz(); }
        return fatura;
      } catch (e) { bildir(e.message, true); }
    },
    async onayla() {
      if (!(await this.kaydet(true))) return;
      try {
        await api(`/api/faturalar/${fatura.id}/onayla`, { metod: "POST" });
        bildir("Fatura onaylandı ve deftere işlendi.");
        sekmeKapat(s);
        listeyiTazele(`faturalar-${fatura.yon}`);
        listeyiTazele("ai-okuma");
      } catch (e) { bildir(e.message, true); yenidenCiz(); }
    },
  });
}

// ---------------------------------------------------------------- belgeden okuma
// Okuma yöntemi: otomatik (önce yapay zekasız, olmazsa ve anahtar varsa yapay zeka), kural (yalnız yapay zekasız), ai.
let OKUMA_YONTEMI = "otomatik";
function yontemSecimi() {
  const secenekler = [["otomatik", "Otomatik (önce yapay zekasız)"], ["kural", "Yapay zekasız"]];
  if (BEN.ai_var) secenekler.push(["ai", "Yapay zeka ile"]);
  if (!BEN.ai_var && OKUMA_YONTEMI === "ai") OKUMA_YONTEMI = "otomatik";
  return h("label", { style: "display:flex;gap:6px;align-items:center" }, "Okuma yöntemi:",
    h("select", { onchange: (e) => (OKUMA_YONTEMI = e.target.value) },
      secenekler.map(([d, m]) => h("option", { value: d, selected: d === OKUMA_YONTEMI }, m))));
}
const okunuyorYazisi = () => (OKUMA_YONTEMI === "ai" ? "Yapay zeka okuyor…" : "Okunuyor…");

// Toplu okumanın durumu sekmeden bağımsız tutulur: başka sekmeye geçip dönünce, sekme kapanıp açılınca ya da
// sayfa yenilenince dosyaların sonucu kaybolmaz (biten dosyalar bu tarayıcıda saklanır).
const OKUMA = { yon: "gelen", yuklemeler: [], secili: new Set(), bekleyen: 0, kuyruk: [], calisan: 0, ayrinti: false, redler: [],
  cizZamani: 0, kayitZamani: 0, gorunum: null };
const OKUMA_ANAHTARI = () => `okuma-yuklemeleri-${BEN?.eposta || ""}`;
function okumaDurumunuYukle() {
  if (OKUMA.yuklendi) return;
  OKUMA.yuklendi = true;
  try {
    const eski = JSON.parse(localStorage.getItem(OKUMA_ANAHTARI()) || "[]");
    for (const y of eski) {
      if (!y.bitti) { y.bitti = true; y.durum = "Yarıda kaldı (sayfa kapandı); bu dosyayı yeniden yükleyin"; y.yarim = true; }
      OKUMA.yuklemeler.push(y);
    }
  } catch { /* saklanan liste okunamazsa boş başlar */ }
}
function okumaDurumunuSakla(hemen = false) {
  if (!hemen && Date.now() - OKUMA.kayitZamani < 2000) return;
  OKUMA.kayitZamani = Date.now();
  try { localStorage.setItem(OKUMA_ANAHTARI(), JSON.stringify(OKUMA.yuklemeler.slice(0, 5000))); } catch { /* yer yoksa saklanmaz */ }
}
addEventListener("beforeunload", () => okumaDurumunuSakla(true));
function okumaSiradaki() {
  while (OKUMA.calisan < 4 && OKUMA.kuyruk.length) {
    OKUMA.calisan++;
    OKUMA.kuyruk.shift()().finally(() => { OKUMA.calisan--; okumaSiradaki(); });
  }
}

function aiOkumaAc() {
  okumaDurumunuYukle();
  const yuklemeler = OKUMA.yuklemeler;
  const secili = OKUMA.secili;
  sekmeAc("ai-okuma", "Belgeden Fatura Oku", {
    ciz(el) {
      let yon = OKUMA.yon;
      const girdi = h("input", { type: "file", multiple: true, accept: ".xml,.zip,application/pdf,image/*,.heic,.heif,.tif,.tiff", hidden: true,
        onchange: (e) => { yukle([...e.target.files]); e.target.value = ""; } });
      // Klasör seçilirse içindeki (alt klasörler dahil) fatura dosyaları yüklenir
      const klasorGirdi = h("input", { type: "file", multiple: true, webkitdirectory: true, hidden: true,
        onchange: (e) => { yukle([...e.target.files]); e.target.value = ""; } });
      klasorGirdi.webkitdirectory = true;
      const klasorOku = async (giris) => {
        if (giris.isFile) return [await new Promise((tamam, hata) => giris.file(tamam, hata))];
        const okuyucu = giris.createReader(), dosyalar = [];
        for (;;) {
          const parca = await new Promise((tamam, hata) => okuyucu.readEntries(tamam, hata));
          if (!parca.length) return dosyalar;
          for (const g of parca) dosyalar.push(...(await klasorOku(g)));
        }
      };
      const alanEl = h("div", { class: "birak-alani", onclick: () => girdi.click(),
        ondragover: (e) => { e.preventDefault(); alanEl.classList.add("uzerinde"); },
        ondragleave: () => alanEl.classList.remove("uzerinde"),
        ondrop: async (e) => {
          e.preventDefault(); alanEl.classList.remove("uzerinde");
          const girisler = [...e.dataTransfer.items].map((i) => i.webkitGetAsEntry?.()).filter(Boolean);
          if (!girisler.some((g) => g.isDirectory)) return yukle([...e.dataTransfer.files]);
          const dosyalar = [];
          for (const g of girisler) dosyalar.push(...(await klasorOku(g)));
          yukle(dosyalar);
        } },
        h("b", {}, "Fatura dosyalarını ya da klasörü buraya sürükleyin"),
        "ya da tıklayıp seçin. Yüzlerce dosya bir seferde yüklenebilir; aynı fatura ikinci kez eklenmez. e-Fatura XML veya ZIP (en doğru sonuç; içindeki PDF/HTML görüntü olarak eklenir), PDF",
        BEN.ocr_var || BEN.ai_var ? ", fotoğraf ya da taranmış fatura (JPG, PNG, HEIC, TIFF)" : "", ".");
      const klasorDugme = h("button", { type: "button", class: "dugme", onclick: () => klasorGirdi.click() }, "Klasör seç (alt klasörler dahil)");
      // Karşı tarafın reddettiği faturalar (portaldan indirilen PDF/XML): kaydedilmez, listeye girer; kayıtlıysa iptal önerilir
      const redGirdi = h("input", { type: "file", multiple: true, accept: ".xml,.zip,application/pdf,image/*", hidden: true,
        onchange: (e) => { yukle([...e.target.files], true); e.target.value = ""; } });
      const redDugme = h("button", { type: "button", class: "dugme", title: "Reddedilmiş ya da iptal edilmiş faturaları seçin: kaydedilmez, sonra yüklense de atlanır; programda kayıtlıysa iptal etmeniz önerilir",
        onclick: () => redGirdi.click() }, "Reddedilen faturaları yükle");
      const redKutu = h("div", { class: "yukleme-ozet red-kutu", hidden: true });
      const redListeKutu = h("div", { class: "yukleme-ozet red-kutu", hidden: true });
      const redIptal = async (idler) => {
        if (!confirm(`${idler.length} fatura reddedildiği için iptal edilsin mi? (Silinmez; bakiyeden ve raporlardan düşer.)`)) return;
        try {
          const r = await api("/api/reddedilen-faturalar/iptal-et", { metod: "POST", veri: { idler } });
          bildir(`${r.iptal_edilen} fatura iptal edildi.`);
          OKUMA.redler.forEach((x) => { if (idler.includes(x.kayitli_id)) { x.kayitli_id = null; x.iptal_edilmis = true; } });
          redCiz();
          if (!redListeKutu.hidden) redListesi();
          listeyiTazele(`faturalar-${yon}`);
        } catch (e) { bildir(e.message, true); }
      };
      const redTablo = (satirlar, islem) => h("div", { class: "tablo-kap" }, h("table", { class: "liste" },
        h("thead", {}, h("tr", {}, ["Fatura No", "Tarih", "Cari", "Tutar", "Durum", ""].map((b, i) => h("th", { class: i === 3 ? "sayi" : "" }, b)))),
        h("tbody", {}, satirlar.map((r) => h("tr", {}, h("td", {}, r.fatura_no || ""), h("td", {}, tarih(r.tarih)),
          h("td", { style: "white-space:normal" }, r.cari_unvan || ""), h("td", { class: "sayi" }, para(r.genel_toplam)),
          h("td", {}, r.durum || (r.kayitli_id ? "Programda kayıtlı" : r.iptal_edilmis ? "İptal edildi" : r.taslak_silindi ? "Onay listesinden çıkarıldı" : "Kaydedilmedi")),
          h("td", {}, r.kayitli_id ? h("button", { class: "dugme tehlike", onclick: () => redIptal([r.kayitli_id]) }, "İptal et") : "", islem ? islem(r) : ""))))));
      function redCiz() {
        const r = OKUMA.redler;
        redKutu.hidden = !r.length;
        if (!r.length) return redKutu.replaceChildren();
        const kayitli = r.filter((x) => x.kayitli_id).map((x) => x.kayitli_id);
        redKutu.replaceChildren(
          h("b", {}, `${r.length} fatura reddedilmiş olduğu için yüklenmedi.`),
          kayitli.length ? h("span", {}, ` ${kayitli.length} tanesi programda kayıtlı; iptal etmeniz önerilir. `) : "",
          kayitli.length > 1 ? h("button", { class: "dugme tehlike", onclick: () => redIptal(kayitli) }, `Kayıtlı olanların hepsini iptal et (${kayitli.length})`) : "",
          h("button", { class: "dugme", onclick: () => { OKUMA.redler = []; redCiz(); } }, "Kapat"),
          redTablo(r));
      }
      async function redListesi() {
        let r;
        try { r = await api("/api/reddedilen-faturalar"); } catch (e) { return bildir(e.message, true); }
        redListeKutu.hidden = false;
        redListeKutu.replaceChildren(h("b", {}, `Reddedilen faturalar listesi (${r.length})`),
          h("button", { class: "dugme", onclick: () => { redListeKutu.hidden = true; } }, "Kapat"),
          r.length ? redTablo(r, (x) => h("button", { class: "dugme", title: "Yanlışlıkla listeye girdiyse çıkarın; sonra normal yüklenir",
            onclick: async () => { if (!confirm(`${x.fatura_no} reddedilenler listesinden çıkarılsın mı?`)) return;
              await api(`/api/reddedilen-faturalar/${x.id}`, { metod: "DELETE" }); redListesi(); } }, "Listeden çıkar"))
            : h("p", {}, "Listede fatura yok."));
      }
      const redListeDugme = h("button", { type: "button", class: "dugme", onclick: () => (redListeKutu.hidden ? redListesi() : (redListeKutu.hidden = true)) }, "Reddedilenler listesi");
      // Toplu yükleme bitince: kaç fatura sorunsuz, kaçı hangi nedenle sorunlu
      const raporKutu = h("div", { class: "yukleme-ozet", hidden: true });
      async function raporOzeti() {
        let o;
        try { o = await api("/api/faturalar/okuma-raporu/ozet"); } catch { return; }
        raporKutu.hidden = !o.toplam && !o.okunamayan_dosya;
        const eski = JSON.stringify(OKUMA.sorunlar || {});
        OKUMA.sorunlar = o.sorunlar || {};
        // Sayılar tıklanır: liste yalnız o sorunlulara süzülür
        const suz = (filtre) => { OKUMA.filtre = filtre; raporOzeti(); tabloyuCiz(); };
        const baglanti = (filtre, metin) => h("a", { href: "#", class: OKUMA.filtre === filtre ? "secili-suzgec" : "",
          onclick: (e) => { e.preventDefault(); suz(OKUMA.filtre === filtre ? "hepsi" : filtre); } }, metin);
        const nedenler = o.kategoriler.flatMap((k, i) => [i ? ", " : "", baglanti(k.kategori, `${k.sayi} ${k.ad.toLowerCase()}`)]);
        raporKutu.replaceChildren(
          h("b", {}, `Onay bekleyen ${o.toplam} fatura: `, baglanti("sorunsuz", `${o.sorunsuz} sorunsuz`), ", ",
            baglanti("sorunlu", `${o.hatali} sorunlu`), ...(nedenler.length ? [" (", ...nedenler, ")"] : []),
            `${o.okunamayan_dosya ? `. Okunamayan dosya: ${o.okunamayan_dosya}` : ""}.`),
          o.hatali || o.okunamayan_dosya ? h("button", { class: "dugme ana", title: "Sorunlu faturaların belgeleri, nedenleri ve PDF dökümü tek ZIP; olduğu gibi Claude'a gönderin",
            onclick: () => indir("/api/faturalar/okuma-raporu", "okuma-hata-raporu.zip") }, "Okuma Hata Raporu (ZIP)") : "",
          o.okunamayan_dosya ? h("button", { class: "dugme", title: "Okunamayan dosyalar listesini boşaltır (faturalar etkilenmez)",
            onclick: async () => { if (!confirm("Okunamayan dosyalar listesi temizlensin mi?")) return;
              await api("/api/faturalar/okuma-raporu/okunamayanlar", { metod: "DELETE" }); raporOzeti(); } }, "Okunamayanlar listesini temizle") : "");
        if (eski !== JSON.stringify(OKUMA.sorunlar)) tabloyuCiz();  // sorunlu faturalar üste alınır
      }
      const liste = h("div", { class: "yukleme-listesi" });
      // Çok dosyada liste tabloyu aşağı itmesin: özet satırı, yalnız hatalılar ve okunmakta olanlar görünür.
      const cizYuklemeler = () => {
        const satir = (y) => h("div", { class: y.durum.startsWith("Hata") ? "negatif" : "" }, h("span", {}, y.ad), h("span", { class: "durum" }, y.durum));
        const hatali = yuklemeler.filter((y) => y.durum.startsWith("Hata"));
        const bekleyen = OKUMA.bekleyen, ayrinti = OKUMA.ayrinti;
        const biten = yuklemeler.length - bekleyen;
        // Dosyaların sonucu: kaç yeni fatura geldi, kaç dosya zaten kayıtlıydı (atlandı)
        const yeni = yuklemeler.reduce((t, y) => t + (y.yeni || 0), 0);
        const zaten = yuklemeler.filter((y) => y.zaten).length;
        const yarim = yuklemeler.filter((y) => y.yarim).length;
        const gorunen = ayrinti || yuklemeler.length <= 10 ? yuklemeler : yuklemeler.filter((y) => y.bitti !== true || y.durum.startsWith("Hata"));
        liste.replaceChildren(
          yuklemeler.length > 1 ? h("div", { class: "yukleme-ozet" },
            h("b", {}, `${yuklemeler.length} dosya: ${biten} bitti${bekleyen ? `, ${bekleyen} okunuyor` : ""}${hatali.length ? `, ${hatali.length} okunamadı` : ""}`
              + ` · ${yeni} yeni fatura eklendi${zaten ? `, ${zaten} dosya zaten kayıtlıydı (atlandı)` : ""}${yarim ? `, ${yarim} dosya yarıda kaldı` : ""}`),
            yuklemeler.length > 10 ? h("button", { class: "dugme", onclick: () => { OKUMA.ayrinti = !OKUMA.ayrinti; cizYuklemeler(); } }, ayrinti ? "Ayrıntıyı gizle" : "Tüm dosyaları göster") : null,
            !bekleyen ? h("button", { class: "dugme", title: "Yalnız bu dosya listesini boşaltır; faturalar etkilenmez", onclick: () => {
              yuklemeler.length = 0; okumaDurumunuSakla(true); cizYuklemeler(); } }, "Dosya listesini temizle") : null) : null,
          // Dosya listesi inceleme tablosunun altında, kendi içinde kayan kutuda: binlerce dosya tabloyu aşağı itmez.
          h("div", { class: "yukleme-satirlari" }, ...gorunen.slice(0, ayrinti ? undefined : 20).map(satir)));
      };
      const tablo = h("div");
      // Aynı anda en çok 4 dosya okunur (okumaSiradaki); yüzlerce dosyada sunucu ve tarayıcı tıkanmaz.
      async function yukle(dosyalar, red = false) {
        dosyalar = dosyalar.filter((d) => /\.(pdf|xml|zip|jpe?g|png|webp|heic|heif|tiff?|bmp)$/i.test(d.name));
        if (!dosyalar.length) return bildir("Seçilenlerde fatura dosyası (PDF, XML, ZIP) yok.", true);
        for (const d of dosyalar) {
          const y = { ad: d.webkitRelativePath || d.name, durum: "Sırada" };
          yuklemeler.unshift(y);
          OKUMA.bekleyen++;
          OKUMA.kuyruk.push(() => oku(d, y, yon, red));
        }
        cizYuklemeler();
        okumaSiradaki();
      }
      // Okuma bitince o an ekrandaki görünüm güncellenir (sekme değişmiş ya da yeniden açılmış olabilir).
      function oku(d, y, yon, red = false) {
          y.durum = okunuyorYazisi();
          const fd = new FormData();
          fd.append("dosya", d);
          return api(`/api/faturalar/oku?yon=${yon}&yontem=${OKUMA_YONTEMI}${red ? "&reddedilen=true" : ""}`, { metod: "POST", dosya: fd })
            .then((sonuc) => {
              // Reddedilmiş faturalar kaydedilmedi: yükleme sonunda ayrı listede gösterilir
              const redler = sonuc.filter((f) => f.reddedildi);
              const faturalar = sonuc.filter((f) => !f.reddedildi);
              for (const r of redler) {
                const i = OKUMA.redler.findIndex((x) => x.fatura_no === r.fatura_no && x.cari_unvan === r.cari_unvan);
                i >= 0 ? (OKUMA.redler[i] = r) : OKUMA.redler.push(r);
              }
              if (!faturalar.length) {
                y.durum = red ? "Reddedilenler listesine eklendi, kaydedilmedi" : "Reddedilmiş fatura, yüklenmedi";
                y.yeni = 0;
                return;
              }
              const u = faturalar.reduce((t, f) => t + (f.ai_okuma?.uyarilar?.filter((x) => x && !/okundu\.?$|yeni cari açıldı/.test(x)).length || 0), 0);
              const varolan = faturalar.filter((f) => f.zaten_var).length;
              const guncellenen = faturalar.filter((f) => !f.zaten_var && f.ai_okuma?.bilgi?.some((x) => x.includes("XML'iyle güncellendi"))).length;
              const digerYon = faturalar.filter((f) => f.yon !== yon).length;
              y.durum = varolan === faturalar.length ? "Bu fatura zaten eklenmiş, atlandı"
                : `${faturalar.length > 1 ? faturalar.length + " fatura okundu" : "Okundu"}${varolan ? `, ${varolan} zaten vardı` : ""}`
                  + `${guncellenen ? `, ${guncellenen} PDF taslağı XML ile düzeltildi` : ""}${u ? `, ${u} uyarı` : ""}`
                  + `${digerYon ? `, ${digerYon} fatura ${yon === "gelen" ? "satış" : "alış"} faturalarına eklendi` : ""}`;
              y.yeni = faturalar.length - varolan;
              y.zaten = varolan === faturalar.length;
              // Uyarılı okunan fatura kendiliğinden seçilmez: toplu onaya sorunlu fatura karışmasın
              faturalar.filter((f) => !f.zaten_var && !f.ai_okuma?.uyarilar?.some((x) => x && !/okundu\.?$|yeni cari açıldı|cinsinden \(kur/.test(x)))
                .forEach((f) => secili.add(f.id));
            })
            .catch((e) => { y.durum = "Hata: " + e.message; })
            .finally(() => {
              y.bitti = true;
              OKUMA.bekleyen--;
              const g = OKUMA.gorunum;
              okumaDurumunuSakla(!OKUMA.bekleyen);
              if (!g) return;
              g.cizYuklemeler();
              // Yüzlerce dosyada tabloyu her dosyada değil, arada bir ve en sonda yenile.
              if (!OKUMA.bekleyen || Date.now() - OKUMA.cizZamani > 10000) { OKUMA.cizZamani = Date.now(); g.tabloyuCiz(); }
              if (!OKUMA.bekleyen) { g.raporOzeti(); g.redCiz(); }
            });
      }

      // Aynı anda tek çizim: binlerce faturada yanıt büyük; üst üste istek birikmez, bitince bir kez daha çizilir.
      async function tabloyuCiz() {
        if (OKUMA.ciziliyor) { OKUMA.tekrarCiz = true; return; }
        OKUMA.ciziliyor = true;
        try { await tabloyuCizAsil(); } finally {
          OKUMA.ciziliyor = false;
          if (OKUMA.tekrarCiz) { OKUMA.tekrarCiz = false; OKUMA.gorunum?.tabloyuCiz(); }
        }
      }
      async function tabloyuCizAsil() {
        let faturalar, santiyeler;
        try {
          [faturalar, santiyeler] = await Promise.all([api(`/api/faturalar?yon=${yon}&durum=taslak`), api("/api/santiyeler")]);
        } catch (e) { return bildir(e.message, true); }
        if (!OKUMA.bekleyen) for (const id of [...secili]) if (!faturalar.some((f) => f.id === id)) secili.delete(id);
        const karsi = (f) => f.cari_unvan || (f.ai_okuma?.[f.yon === "gelen" ? "satici" : "alici"]?.unvan ? `(yeni cari) ${f.ai_okuma[f.yon === "gelen" ? "satici" : "alici"].unvan}` : "— cari yok —");
        // Eski sürümün bilgi notlarını ("okundu", "yeni cari açıldı") uyarı sayma.
        // Bilgi notları sorun sayılmaz: döviz cinsi (kur girilmişse), 1 TL'ye kadar yuvarlama, fatura tutarıyla kayıt
        const bilgiNotu = (u, f) => /okundu\.?$|yeni cari açıldı|karekodundan doğrulandı|fatura tutarıyla kaydedildi/.test(u)
          || (/^Fatura [A-Z]{3} cinsinden/.test(u) && !/kuru girin/.test(u) && Number(f.kur) > 0)
          || (/^Faturada ([\d.,]+) TL yuvarlama farkı/.test(u) && Number(u.match(/^Faturada ([\d.,]+)/)[1].replace(/\./g, "").replace(",", ".")) <= 1);
        const uyarilar = (f) => (f.ai_okuma?.uyarilar || []).filter((u) => u && !bilgiNotu(u, f)
          && !(u.startsWith("Firmanın adı") && !/^VKN \d+$/.test(f.cari_unvan || "")));
        const tumu = h("input", { type: "checkbox", title: "Tümünü seç", checked: faturalar.length > 0 && secili.size === faturalar.length,
          onchange: (e) => { faturalar.forEach((f) => (e.target.checked ? secili.add(f.id) : secili.delete(f.id))); tabloyuCiz(); } });
        const sayac = h("span", {});
        const sayacYaz = () => (sayac.textContent = `${secili.size} / ${tumFaturalar.length} seçili`);
        const santiyeK = santiyeSecici(santiyeler);
        const santiyeS = santiyeK.secim;
        const giderS = h("select", {}, [["", "— Gider türü seçin —"], ...BEN.gider_turleri.map((g) => [g, g])].map(([d, m]) => h("option", { value: d }, m)));
        const seciliIdler = () => (secili.size ? [...secili] : (bildir("Önce fatura seçin.", true), null));
        const toplu = async (islem) => {
          const idler = seciliIdler();
          if (!idler) return;
          try {
            if (islem === "onayla") {
              const r = await api("/api/faturalar/toplu-onayla", { metod: "POST", veri: { idler } });
              bildir(`${r.onaylanan} fatura onaylandı ve deftere işlendi${r.hatalar.length ? `. ${r.hatalar.length} fatura onaylanamadı: ${r.hatalar[0]}` : "."}`, !!r.hatalar.length);
              listeyiTazele(`faturalar-${yon}`);
            } else if (islem === "sil") {
              if (!confirm(`Seçilen ${idler.length} fatura silinsin mi?`)) return;
              const r = await api("/api/faturalar/toplu-sil", { metod: "POST", veri: { idler } });
              bildir(`${r.silinen} fatura silindi.`);
            } else {
              const veri = { idler, santiye_id: Number(santiyeS.value) || null, gider_turu: giderS.value || null };
              if (!veri.santiye_id && !veri.gider_turu) return bildir("Şantiye ya da gider türü seçin.", true);
              const r = await api("/api/faturalar/toplu-guncelle", { metod: "POST", veri });
              bildir(`${r.guncellenen} faturaya${veri.santiye_id ? " ve tüm kalemlerine" : ""} atandı.`);
            }
            tabloyuCiz();
          } catch (e) { bildir(e.message, true); }
        };
        const sorunu = (f) => (!f.cari_id && !f.ai_okuma?.[f.yon === "gelen" ? "satici" : "alici"]?.unvan ? "Firma okunamadı; İncele'den cariyi seçin."
          : !f.kalemler.length || f.ai_okuma?.kalemler_okunamadi ? "Kalemler tek tek okunamadı; İncele'den faturadaki kalemleri girin."
          : !f.genel_toplam ? "Tutar okunamadı."
          : !["TRY", "TL"].includes(f.para_birimi || "TRY") && !f.kur ? `Fatura ${f.para_birimi} cinsinden; İncele'den kuru girin.`
          : toplamTutmuyor(f) ? "Hesaplanan KDV ya da ödenecek tutar faturayı tutmuyor; İncele'den kalemleri düzeltin."
          : f.ai_okuma?.resimden?.belirsiz?.length ? `Resimde net seçilemeyen tutarlar var (${f.ai_okuma.resimden.belirsiz.slice(0, 4).join(", ")}); İncele'den belgeyle karşılaştırın.`
          : f.ai_okuma?.resimden && f.ai_okuma.resimden.guven < 60 ? "Resim bulanık okundu; İncele'den bütün alanları belgeyle karşılaştırın." : null);
        // Sorunlu faturalar (kırmızı: işlenemedi, sarı: Okuma Hata Raporu'nda sorunlu) listenin en üstünde
        const sorunlar = OKUMA.sorunlar || {};
        const derece = (f) => (sorunu(f) ? 0 : sorunlar[f.id] ? 1 : 2);
        const filtre = OKUMA.filtre || "hepsi";
        const tumFaturalar = faturalar;
        faturalar = faturalar.map((f, i) => [f, i]).sort((a, b) => derece(a[0]) - derece(b[0]) || a[1] - b[1]).map(([f]) => f)
          .filter((f) => filtre === "hepsi" ? true : filtre === "sorunsuz" ? derece(f) === 2 : filtre === "sorunlu" ? derece(f) < 2
            : (sorunlar[f.id] || []).some((x) => x.kategori === filtre));
        const islenemeyen = tumFaturalar.filter(sorunu).length;
        const sorunluSayisi = tumFaturalar.filter((f) => derece(f) < 2).length;
        const suzgec = h("select", { onchange: (e) => { OKUMA.filtre = e.target.value; raporOzeti(); tabloyuCiz(); } },
          [["hepsi", "Hepsi (sorunlular üstte)"], ["sorunlu", "Yalnız sorunlular"], ["sorunsuz", "Yalnız sorunsuzlar"],
            ...(!["hepsi", "sorunlu", "sorunsuz"].includes(filtre) ? [[filtre, "Seçilen sorun türü"]] : [])]
            .map(([d, m]) => h("option", { value: d, selected: d === filtre }, m)));
        const dovizMi = (f) => !["TRY", "TL"].includes(f.para_birimi || "TRY");
        const tutarPb = (f, x) => (dovizMi(f) ? `${para(x)} ${f.para_birimi}` : para(x));
        const satirlar = faturalar.map((f) => {
          const sr = sorunu(f);
          const ou = uyarilar(f);
          const u = [...ou, ...(sr ? [] : (sorunlar[f.id] || []).map((x) => x.neden)
            .filter((x) => !(x.startsWith("Cari: adı faturada yazmıyor") && ou.some((y) => y.startsWith("Firmanın adı")))))]
            .filter((x, i, d) => d.indexOf(x) === i);
          return h("tr", { class: sr ? "islenemedi" : u.length ? "secili" : "", title: [sr, ...u].filter(Boolean).join("\n") },
            h("td", {}, h("input", { type: "checkbox", checked: secili.has(f.id), onchange: (e) => { e.target.checked ? secili.add(f.id) : secili.delete(f.id); sayacYaz(); } })),
            h("td", {}, tarih(f.tarih)), h("td", {}, f.fatura_no || ""), h("td", { style: "white-space:normal;min-width:200px" }, karsi(f)),
            h("td", {}, f.santiye_ad || ""), h("td", {}, f.gider_turu || ""),
            h("td", { class: "sayi" }, String(f.kalemler.length)),
            h("td", { class: "sayi" }, tutarPb(f, f.ara_toplam)), h("td", { class: "sayi" }, tutarPb(f, f.kdv_toplam)),
            h("td", { class: "sayi", title: dovizMi(f) && f.kur ? `TL karşılığı: ${para(f.genel_toplam * f.kur)} TL` : "" }, tutarPb(f, f.genel_toplam)),
            h("td", { style: "white-space:normal;min-width:260px;font-size:12px" },
              dovizMi(f) ? h("span", { class: "doviz-etiketi" }, f.kur ? `${f.para_birimi} · kur ${Number(f.kur).toLocaleString("tr-TR", { maximumFractionDigits: 4 })} · ${para(f.genel_toplam * f.kur)} TL` : `${f.para_birimi} · kur yok`) : "",
              sr || (u.length ? h("ul", { class: "uyari-listesi" }, u.map((x) => h("li", {}, x))) : "")),
            h("td", {}, h("button", { class: "dugme", onclick: () => faturaFormAc(f, f.yon) }, "İncele")));
        });
        // Seçilenlerin toplamı TL: dövizli fatura kuruyla çevrilir
        const toplam = (a) => para(faturalar.filter((f) => secili.has(f.id)).reduce((t, f) => t + (f[a] || 0) * (dovizMi(f) ? Number(f.kur) || 0 : 1), 0));
        tablo.replaceChildren(
          h("h2", { style: "margin-top:14px" }, `Onay Bekleyen ${yon === "gelen" ? "Alış" : "Satış"} Faturaları`),
          faturalar.length ? h("div", {},
            islenemeyen ? h("div", { class: "hata-kutu" }, `${islenemeyen} fatura işlenemedi (kırmızı satırlar, listenin en üstünde). Nedeni satırın sonunda yazıyor; İncele ile düzeltin.`) : "",
            h("div", { class: "liste-ust" }, "Göster:", suzgec,
              sorunluSayisi ? h("button", { class: "dugme", title: "Sorunlu faturaların seçimini kaldırır; sorunsuzlar toplu onaylanabilir",
                onclick: () => { tumFaturalar.forEach((f) => (derece(f) < 2 ? secili.delete(f.id) : secili.add(f.id))); tabloyuCiz(); } },
              `Yalnız sorunsuzları seç (${tumFaturalar.length - sorunluSayisi})`) : ""),
            h("div", { class: "liste-ust" },
              h("button", { class: "dugme ana", onclick: () => toplu("onayla") }, "Seçilenleri onayla"),
              h("button", { class: "dugme tehlike", onclick: () => toplu("sil") }, "Seçilenleri sil"),
              h("span", { class: "arac-ayrac", style: "align-self:stretch" }),
              santiyeK, giderS, h("button", { class: "dugme", onclick: () => toplu("ata") }, "Seçilenlere ata"),
              sayac, h("span", { class: "arac-ayrac", style: "align-self:stretch" }),
              h("button", { class: "dugme", onclick: () => indir(`/api/excel/fatura-uyarilari?yon=${yon}`, "fatura-uyari-raporu.xlsx") }, "Uyarı raporu (Excel)"),
              h("button", { class: "dugme", title: "Sorunlu faturaların ve okunamayan dosyaların belgeleri, nedenleri ve PDF dökümü tek ZIP",
                onclick: () => indir("/api/faturalar/okuma-raporu", "okuma-hata-raporu.zip") }, "Okuma Hata Raporu (ZIP)")),
            h("div", { class: "tablo-kap" }, h("table", { class: "liste kalemler-secim" },
              h("thead", {}, h("tr", {}, h("th", {}, tumu), ["Tarih", "Fatura No", "Cari", "Şantiye", "Gider Türü", "Kalem", "Ara Toplam", "KDV", "Genel Toplam", "Uyarı", ""]
                .map((b, i) => h("th", { class: i >= 5 && i <= 8 ? "sayi" : "" }, b)))),
              h("tbody", {}, satirlar),
              h("tfoot", {}, h("tr", {}, h("td", { colspan: 7 }, "Seçilenlerin toplamı (TL)"), h("td", { class: "sayi" }, toplam("ara_toplam")),
                h("td", { class: "sayi" }, toplam("kdv_toplam")), h("td", { class: "sayi" }, toplam("genel_toplam")), h("td", { colspan: 2 }))))),
            h("p", { style: "margin:6px 0 0;color:#4a5866" }, "Kırmızı satırlar işlenemedi, sarı satırlarda uyarı var; uyarılar satırın sonunda yazar. Onaylamadan önce İncele ile bakın. Tüm uyarıları \"Uyarı raporu (Excel)\" ile indirebilirsiniz. Cari yoksa onayda faturadaki ünvan ve VKN ile açılır."))
            : h("p", {}, OKUMA.bekleyen ? "Faturalar okunuyor…" : "Onay bekleyen fatura yok. Dosyaları yukarıya bırakın."));
        sayacYaz();
        durum(`${faturalar.length} fatura onay bekliyor`);
      }

      el.append(h("div", { class: "form-pencere", style: "max-width:none" },
        h("h2", {}, "Belgeden Fatura Oku"),
        h("div", { class: "liste-ust" }, "Fatura türü:",
          h("select", { onchange: (e) => { yon = OKUMA.yon = e.target.value; secili.clear(); tabloyuCiz(); } }, h("option", { value: "gelen", selected: yon === "gelen" }, "Alış (gelen) faturası"),
            h("option", { value: "giden", selected: yon === "giden" }, "Satış (giden) faturası")),
          yontemSecimi()),
        h("p", { style: "margin:0 0 8px;color:#4a5866" }, BEN.ocr_var
          ? "XML ve metinli PDF'ler yapay zekasız okunur. Taranmış PDF ve fotoğraflar bu bilgisayarda metin tanımayla (yine yapay zekasız) okunur; net okunamayan tutarlar kırmızı gösterilir."
          : BEN.ai_var
          ? "XML ve metinli PDF'ler yapay zekasız okunur. Resim okuma programı kurulu değil; taranmış PDF ve fotoğraflar yapay zeka ile okunur."
          : "XML ve metinli PDF'ler yapay zekasız okunur. Resim okuma programı kurulu değil (baslat.bat ilk açılışta kurar); o zamana kadar fotoğraf ve taranmış PDF okunamaz."),
        alanEl, girdi, klasorGirdi, redGirdi, h("div", { class: "liste-ust", style: "margin-top:6px" }, klasorDugme, redDugme, redListeDugme),
        redKutu, redListeKutu, raporKutu, tablo, liste));
      OKUMA.gorunum = { cizYuklemeler, tabloyuCiz, raporOzeti, redCiz };
      redCiz();
      cizYuklemeler();
      tabloyuCiz();
      raporOzeti();
    },
    yenile: () => yenidenCiz(),
  });
}

// ---------------------------------------------------------------- raporlar
function santiyeOzetAc() {
  sekmeAc("rapor-santiye", "Şantiye Maliyet Raporu", {
    async ciz(el) {
      const veri = await api("/api/raporlar/santiye-ozet").catch((e) => (bildir(e.message, true), []));
      el.append(h("div", { class: "liste-ust" }, h("h2", {}, "Şantiye Maliyet Raporu"), h("span", {}, "Sadece onaylı faturalar dahildir.")));
      if (!veri.length) el.append(h("p", {}, "Henüz şantiye yok."));
      el.append(h("div", { class: "kart-satiri" }, veri.map((s) => {
        const oran = s.butce ? Math.min(100, (s.gider / s.butce) * 100) : 0;
        return h("div", { class: "ozet-kart" }, h("h3", {}, s.ad),
          h("dl", {}, h("dt", {}, "Bütçe"), h("dd", {}, s.butce != null ? para(s.butce) : "—"),
            h("dt", {}, "Gider"), h("dd", {}, para(s.gider)), h("dt", {}, "Gelir"), h("dd", {}, para(s.gelir)),
            h("dt", {}, "Kâr"), h("dd", { class: s.kar < 0 ? "negatif" : "" }, para(s.kar)),
            s.butce != null ? [h("dt", {}, "Bütçeden kalan"), h("dd", { class: s.butce_kalan < 0 ? "negatif" : "" }, para(s.butce_kalan))] : null),
          s.butce ? h("div", { class: "cubuk", title: `Bütçenin %${oran.toFixed(0)}'i harcandı` }, h("div", { class: s.gider > s.butce ? "asim" : "", style: `width:${oran}%` })) : null,
          Object.keys(s.gider_turleri).length ? h("dl", {}, Object.entries(s.gider_turleri).flatMap(([t, v]) => [h("dt", {}, t), h("dd", {}, para(v))])) : null);
      })));
    },
    yenile: () => yenidenCiz(),
    excel: () => indir("/api/excel/santiye-ozet", "santiye-ozet.xlsx"),
  });
}

function santiyeFaturalariAc() {
  // Varsayılan: alış faturaları, tüm aylar, tüm şantiyeler. Şantiye listeden seçilir, "Ara" ile o şantiyenin bütün harcamaları gelir
  const filtre = { yon: "gelen", ay: "", secili: new Set() };
  let bekleyen = "";
  const sorgu = () => {
    const q = new URLSearchParams();
    if (filtre.yon) q.set("yon", filtre.yon);
    if (filtre.ay) {
      const [y, a] = filtre.ay.split("-").map(Number);
      q.set("baslangic", `${filtre.ay}-01`);
      q.set("bitis", `${filtre.ay}-${String(new Date(y, a, 0).getDate()).padStart(2, "0")}`);
    }
    if (filtre.secili.size) q.set("santiye_ids", [...filtre.secili].join(","));
    return q.toString();
  };
  sekmeAc("rapor-santiye-fatura", "Şantiye Bazlı Faturalar", {
    async ciz(el) {
      let santiyeler, satirlar;
      try { [santiyeler, satirlar] = await Promise.all([api("/api/santiyeler"), api(`/api/raporlar/santiye-faturalari?${sorgu()}`)]); }
      catch (e) { return bildir(e.message, true); }
      const ara = () => { filtre.secili = new Set(bekleyen ? [Number(bekleyen)] : []); yenidenCiz(); };
      bekleyen = filtre.secili.size ? String([...filtre.secili][0]) : "";
      const secimS = h("select", { style: "min-width:260px", onchange: (e) => (bekleyen = e.target.value) },
        [["", "— Tüm şantiyeler —"], ...santiyeler.map((st) => [String(st.id), st.ad])].map(([d, m]) => h("option", { value: d, selected: d === bekleyen }, m)));
      const top = (dizi, a) => dizi.reduce((t, r) => t + r[a], 0);
      // Her satır bir kalem (bütün harcamalar); kalemsiz fatura tek satır
      const kalemleri = (r) => (r.kalem_detay?.length ? r.kalem_detay
        : [{ aciklama: r.kalemler, miktar: null, birim: null, tutar: r.ara_toplam, kdv: r.kdv, toplam: r.genel_toplam }]);
      const grup = new Map();
      for (const r of satirlar) { if (!grup.has(r.santiye)) grup.set(r.santiye, []); grup.get(r.santiye).push(r); }
      const govde = [];
      let kalemSayisi = 0;
      for (const [ad, dizi] of grup) {
        for (const r of dizi) {
          for (const d of kalemleri(r)) {
            kalemSayisi++;
            govde.push(h("tr", { title: "Çift tıklayınca fatura açılır", ondblclick: () => faturaFormAc({ id: r.fatura_id }, null) },
              h("td", {}, r.santiye), h("td", {}, tarih(r.tarih)), h("td", {}, r.fatura_no || ""), h("td", {}, r.tur), h("td", {}, r.cari || ""),
              h("td", {}, r.gider_turu || ""), h("td", { style: "white-space:normal;min-width:220px" }, d.aciklama || ""),
              h("td", { class: "sayi" }, d.miktar != null ? `${Number(d.miktar).toLocaleString("tr-TR")} ${d.birim || ""}` : ""),
              h("td", { class: "sayi" }, para(d.tutar)), h("td", { class: "sayi" }, para(d.kdv)), h("td", { class: "sayi" }, para(d.toplam))));
          }
        }
        govde.push(h("tr", { class: "ara-toplam" }, h("td", { colspan: 8 }, `${ad} toplamı (${dizi.length} fatura)`),
          ...["ara_toplam", "kdv", "genel_toplam"].map((a) => h("td", { class: "sayi" }, para(top(dizi, a))))));
      }
      // Gider türüne göre özet
      const turler = new Map();
      for (const r of satirlar) turler.set(r.gider_turu || "Belirtilmemiş", (turler.get(r.gider_turu || "Belirtilmemiş") || 0) + r.genel_toplam);
      const seciliAd = filtre.secili.size ? santiyeler.find((st) => filtre.secili.has(st.id))?.ad : null;
      el.append(h("div", { class: "liste-ust" }, h("h2", {}, "Şantiye Bazlı Faturalar"),
          h("select", { onchange: (e) => { filtre.yon = e.target.value; yenidenCiz(); } },
            [["gelen", "Alış faturaları"], ["giden", "Satış faturaları"], ["", "Alış ve satış"]].map(([d, m]) => h("option", { value: d, selected: d === filtre.yon }, m))),
          "Ay:", h("input", { type: "month", value: filtre.ay, onchange: (e) => { filtre.ay = e.target.value; yenidenCiz(); } }),
          h("button", { class: "dugme", onclick: () => { filtre.ay = ""; yenidenCiz(); } }, "Tüm aylar"),
          h("button", { class: "dugme ana", onclick: () => this.excel() }, "Excel'e aktar (F9)")),
        h("div", { class: "liste-ust" }, "Şantiye:", santiyeler.length ? secimS : "Henüz şantiye yok.",
          h("button", { class: "dugme ana", onclick: ara }, "Ara")),
        h("h3", { style: "margin:6px 0" }, `${seciliAd || "Tüm şantiyeler"}: ${satirlar.length} fatura, ${kalemSayisi} kalem, toplam ${para(top(satirlar, "genel_toplam"))} TL`),
        turler.size ? h("div", { class: "liste-ust", style: "flex-wrap:wrap;font-size:13px" }, "Gider türüne göre:",
          [...turler].sort((x, y) => y[1] - x[1]).map(([t, v]) => h("span", { class: "etiket" }, `${t}: ${para(v)}`))) : "",
        satirlar.length ? h("div", { class: "tablo-kap" }, h("table", { class: "liste" },
          h("thead", {}, h("tr", {}, ["Şantiye", "Tarih", "Fatura No", "Tür", "Cari", "Gider Türü", "Mal Hizmet Adı", "Miktar", "Tutar (KDV hariç)", "KDV", "Toplam"]
            .map((b, i) => h("th", { class: i >= 7 ? "sayi" : "" }, b)))),
          h("tbody", {}, govde),
          h("tfoot", {}, h("tr", {}, h("td", { colspan: 8 }, "Genel toplam"),
            ...["ara_toplam", "kdv", "genel_toplam"].map((a) => h("td", { class: "sayi" }, para(top(satirlar, a))))))))
          : h("p", {}, "Bu seçime uyan onaylı fatura yok."),
        h("p", { style: "color:#4a5866" }, "Yalnız onaylı faturalar listelenir. Bir fatura birden fazla şantiyeye aitse her şantiyeye kendi kalemleri yazılır. Satıra çift tıklayınca fatura açılır."));
      durum(`${satirlar.length} fatura, ${kalemSayisi} kalem listelendi`);
    },
    yenile: () => yenidenCiz(),
    excel: () => indir(`/api/excel/santiye-faturalari?${sorgu()}`, `santiye-harcamalari${filtre.ay ? "-" + filtre.ay : ""}.xlsx`),
  });
}

function cariBakiyeAc() {
  sekmeAc("rapor-cari", "Cari Bakiye Raporu", listeEkrani({
    baslik: "Cari Bakiye Raporu",
    kaynak: () => api("/api/raporlar/cari-bakiye"),
    kolonlar: [{ alan: "unvan", baslik: "Ünvan" }, { alan: "vkn", baslik: "VKN" },
      { alan: "borc", baslik: "Borç", tip: "para" }, { alan: "alacak", baslik: "Alacak", tip: "para" }, { alan: "bakiye", baslik: "Bakiye", tip: "para" }],
    toplamlar: ["borc", "alacak", "bakiye"],
    ac: (c) => cariEkstreAc(c),
    excel: "/api/excel/cari-bakiye",
  }));
}

function cariEkstreAc(cari) {
  sekmeAc(`ekstre-${cari.id}`, `Ekstre: ${cari.unvan}`, listeEkrani({
    baslik: `Cari Ekstre: ${cari.unvan}`,
    kaynak: async () => (await api(`/api/raporlar/cari-ekstre/${cari.id}`)).satirlar,
    kolonlar: [{ alan: "tarih", baslik: "Tarih", tip: "tarih" }, { alan: "belge", baslik: "Belge No" }, { alan: "aciklama", baslik: "Açıklama" },
      { alan: "borc", baslik: "Borç", tip: "para" }, { alan: "alacak", baslik: "Alacak", tip: "para" }, { alan: "bakiye", baslik: "Bakiye", tip: "para" }],
    toplamlar: ["borc", "alacak"],
    ac: (s) => (s.fatura_id ? faturaFormAc({ id: s.fatura_id }, null) : bildir("Bu satır bir para hareketidir.")),
    ustAlan: () => h("span", { class: "dugmeler", style: "margin:0" },
      h("button", { class: "dugme", onclick: () => yazdirAc(`/api/yazdir/cari-ekstre/${cari.id}`) }, "Ekstreyi yazdır"),
      h("button", { class: "dugme", onclick: () => yazdirAc(`/api/yazdir/mutabakat/${cari.id}`) }, "Mutabakat mektubu"),
      h("button", { class: "dugme", onclick: () => cariHizliHareket(cari.id, "giris") }, "Tahsilat al"),
      h("button", { class: "dugme", onclick: () => cariHizliHareket(cari.id, "cikis") }, "Ödeme yap"),
      h("button", { class: "dugme", onclick: () => cariHatirlat(cari.id, "whatsapp") }, "WhatsApp ile hatırlat"),
      h("button", { class: "dugme", onclick: () => cariHatirlat(cari.id, "eposta") }, "E-posta ile hatırlat")),
  }));
}

// ---------------------------------------------------------------- Excel ve yedek
function excelIslemleriAc() {
  sekmeAc("excel", "Excel İşlemleri", {
    ciz(el) {
      const yukleGirdi = h("input", { type: "file", accept: ".xlsx", hidden: true, onchange: async (e) => {
        const fd = new FormData(); fd.append("dosya", e.target.files[0]); e.target.value = "";
        try { const r = await api("/api/excel/cariler/yukle", { metod: "POST", dosya: fd }); bildir(`${r.eklenen} cari eklendi, ${r.atlanan} satır atlandı.`); }
        catch (err) { bildir(err.message, true); }
      } });
      const yukleyici = (yol, mesaj) => h("input", { type: "file", accept: ".xlsx", hidden: true, onchange: async (e) => {
        const fd = new FormData(); fd.append("dosya", e.target.files[0]); e.target.value = "";
        try { bildir(mesaj(await api(typeof yol === "function" ? yol() : yol, { metod: "POST", dosya: fd }))); }
        catch (err) { bildir(err.message, true); }
      } });
      const ekler = (r) => [r.atlanan ? `${r.atlanan} fatura daha önce girildiği için atlandı` : "",
        r.yeni_cari ? `${r.yeni_cari} yeni cari` : "", r.yeni_santiye ? `${r.yeni_santiye} yeni şantiye açıldı` : ""].filter(Boolean).join(", ");
      const faturaYonS = h("select", {}, h("option", { value: "gelen" }, "Alış faturası listesi"), h("option", { value: "giden" }, "Satış faturası listesi"));
      const faturaGirdi = yukleyici(() => `/api/excel/faturalar/yukle?yon=${faturaYonS.value}`,
        (r) => `${r.eklenen} fatura onay bekleyenlere eklendi${ekler(r) ? ". " + ekler(r) : ""}.`);
      const cekGirdi = yukleyici("/api/excel/cekler/yukle", (r) => `${r.eklenen} çek eklendi${ekler(r) ? ". " + ekler(r) : ""}.`);
      const satir = (baslik, aciklama, ...dugmeler) => h("fieldset", {}, h("legend", {}, baslik), h("p", { style: "margin:0 0 6px" }, aciklama), h("div", { class: "dugmeler" }, dugmeler));
      const d = (m, yol, ad) => h("button", { class: "dugme", onclick: () => indir(yol, ad) }, m);
      el.append(h("div", { class: "form-pencere" }, h("h2", {}, "Excel İşlemleri"),
        satir("Toplu cari yükleme", "Şablonu indirin, carilerinizi doldurun ve yükleyin. Aynı VKN'ye sahip cariler atlanır.",
          d("Şablonu indir", "/api/excel/cari-sablon", "cari-sablonu.xlsx"), h("button", { class: "dugme ana", onclick: () => yukleGirdi.click() }, "Excel'den cari yükle"), yukleGirdi),
        satir("Toplu fatura yükleme", "Programın şablonunu ya da kendi fatura listenizi (Tarihi, Fatura No, Ticari Unvanı, Stok Adı, Grubu, Miktarı, Tutarı, Tutarı (KDV Dahil) sütunlu) yükleyebilirsiniz. Her satır bir kalemdir; aynı fatura numaralı satırlar tek fatura olur. \"Grubu\" sütunu şantiye sayılır. Cari ve şantiye yoksa açılır, daha önce girilmiş faturalar atlanır. Dosyada hata varsa hiçbir şey eklenmez ve hatalı satır söylenir.",
          faturaYonS, d("Şablonu indir", "/api/excel/fatura-sablon", "fatura-sablonu.xlsx"), h("button", { class: "dugme ana", onclick: () => faturaGirdi.click() }, "Excel'den fatura yükle"), faturaGirdi),
        satir("Toplu çek yükleme", "Alınan ve verilen çek/senetleri tek dosyada girin. Çekler doğrudan portföye (verilenler ödenecekler listesine) eklenir.",
          d("Şablonu indir", "/api/excel/cek-sablon", "cek-sablonu.xlsx"), h("button", { class: "dugme ana", onclick: () => cekGirdi.click() }, "Excel'den çek yükle"), cekGirdi),
        satir("Listeleri indir", "Tüm kayıtları Excel olarak indirin.",
          d("Cariler", "/api/excel/cariler", "cariler.xlsx"), d("Faturalar", "/api/excel/faturalar", "faturalar.xlsx"),
          d("Şantiye özeti", "/api/excel/santiye-ozet", "santiye-ozet.xlsx"), h("button", { class: "dugme", onclick: santiyeFaturalariAc }, "Şantiye bazlı faturalar (aylık)…"), d("Cari bakiyeler", "/api/excel/cari-bakiye", "cari-bakiye.xlsx"),
          d("Çekler", "/api/excel/cekler", "cekler.xlsx"), d("Tahsilat/ödeme hareketleri", "/api/excel/hareketler", "hareketler.xlsx")),
        satir("Wolvox'a aktarım", "Onaylı faturaların satır bazında listesi. Wolvox şablon sütunları netleşince birebir uyumlu hale getirilecek.",
          d("Fatura kalemleri (Wolvox)", "/api/excel/fatura-kalemleri", "wolvox-fatura-kalemleri.xlsx"))));
    },
  });
}

function yedeklerAc() {
  sekmeAc("yedekler", "Yedekler", listeEkrani({
    baslik: "Yedekler",
    kaynak: async () => (await api("/api/yedekler")).map((y) => ({ ...y, id: `${y.klasor}/${y.dosya}` })),
    kolonlar: [{ alan: "tarih", baslik: "Tarih", deger: (y) => new Date(y.tarih).toLocaleString("tr-TR") }, { alan: "dosya", baslik: "Dosya" },
      { alan: "klasor", baslik: "Klasör" }, { alan: "boyut", baslik: "Boyut", deger: (y) => `${(y.boyut / 1024).toFixed(0)} KB` }],
    ustAlan: () => h("span", { class: "dugmeler", style: "margin:0" },
      h("button", { class: "dugme", onclick: async () => {
        try {
          const r = await api("/api/yedekler/dene", { metod: "POST" });
          bildir(r.ok ? `Son yedek (${r.dosya}) açılıp denendi: sorunsuz.` : `Son yedek açılamadı: ${r.hata}`, !r.ok);
        } catch (e) { bildir(e.message, true); }
      } }, "Son yedeği dene"),
      h("span", { class: "ipucu" }, "Bir yedeğe dönmek için satırı seçip \"Bu yedeğe dön\" deyin. En yeni 10 yedek ve her ayın son yedeği saklanır, eskiler kendiliğinden silinir.")),
    toplu: BEN.rol === "sahip" ? [{ ad: "Bu yedeğe dön", tehlikeli: true, islem: async (sec) => {
      if (sec.length !== 1) { bildir("Dönülecek tek bir yedek seçin.", true); return false; }
      const y = sec[0];
      const cevap = prompt(`${new Date(y.tarih).toLocaleString("tr-TR")} tarihli yedeğe dönülecek. O tarihten sonra girilen kayıtlar bu ekrandan kalkar.\n\n`
        + "Önce bugünkü verinizin yedeği alınır; yanlış yedeğe dönerseniz o yedekle geri gelebilirsiniz. Yedek açılıp denenmeden hiçbir şey değişmez.\n\nOnaylamak için DÖN yazın:");
      if (cevap == null) return false;
      if (cevap.trim().toLocaleUpperCase("tr") !== "DÖN") { bildir("Onay için DÖN yazılmadı; hiçbir şey değişmedi.", true); return false; }
      try {
        const r = await api("/api/yedekler/geri-yukle", { metod: "POST", veri: { klasor: y.klasor, dosya: y.dosya } });
        alert(`Yedeğe dönüldü (${r.geri_yuklenen}). Dönmeden önceki veriniz ${r.onceki_yedek} adıyla yedeklendi.\n\nProgram yeniden yüklenecek.`);
        location.reload();
      } catch (e) { bildir(e.message, true); return false; }
    } }, { ad: "Seçilenleri sil", tehlikeli: true, islem: async (sec) => {
      const klasorler = [...new Set(sec.map((y) => y.klasor))];
      if (!confirm(`${sec.length} yedek dosyası silinecek (${klasorler.join(", ")}).\n\nSilinen yedeğe geri dönülemez. En son yedek silinmez. Devam edilsin mi?`)) return false;
      // Aynı yedek birden çok klasöre (ör. Google Drive) yazılır: öteki kopyalar için ayrıca sorulur
      const diger = (await api("/api/yedekler")).some((y) => sec.some((s) => s.dosya === y.dosya && s.klasor !== y.klasor)
        && !sec.some((s) => s.dosya === y.dosya && s.klasor === y.klasor));
      const digerKopyalar = diger && confirm("Bu yedeklerin öteki klasörlerdeki (ör. Google Drive) kopyaları da silinsin mi?\n\nTamam: hepsi silinir.  İptal: yalnız seçilenler silinir, öteki kopyalar kalır.");
      try {
        const r = await api("/api/yedekler/sil", { metod: "POST", veri: { secilenler: sec.map((y) => ({ klasor: y.klasor, dosya: y.dosya })), diger_kopyalar: digerKopyalar } });
        bildir(`${r.silinen} yedek dosyası silindi.`);
      } catch (e) { bildir(e.message, true); return false; }
    } }] : [],
    yeni: async () => {
      try {
        const r = await api("/api/yedekler", { metod: "POST" });
        const hatali = r.hedefler.filter((x) => !x.ok);
        bildir(hatali.length ? `Yedek alındı ama ${hatali.length} klasöre yazılamadı.` : "Yedek alındı.", !!hatali.length);
        yenidenCiz();
      } catch (e) { bildir(e.message, true); }
    },
  }));
}

// Genel Durum'da kurulum ve yedek durumu: sorun varsa tek satır, yoksa hiçbir şey
function sistemSatirlari(s) {
  if (!s) return "";
  const satirlar = [];
  if (!s.ocr_var) {
    const kur = s.kurulabilir && BEN.rol === "sahip" ? h("button", { class: "dugme kucuk", onclick: async (e) => {
      e.target.disabled = true;
      try {
        await api("/api/sistem/tesseract-kur", { metod: "POST" });
        bildir("Resim okuma programı kuruluyor. Windows izin sorarsa Evet deyin; bitince Genel Durum'u yenileyin (F5).");
      } catch (err) { bildir(err.message, true); e.target.disabled = false; }
    } }, "Kur") : "";
    const k = s.ocr_kurulum || {};
    satirlar.push(h("div", { class: "uyari-satiri" }, k.durum === "kuruluyor" ? "Resim okuma programı kuruluyor…"
      : k.durum === "hata" ? `Resim okuma programı kurulamadı: ${k.hata} ` : "Resim okuma programı (fotoğraf ve taranmış belge okuma) kurulu değil. ", k.durum === "kuruluyor" ? "" : kur));
  }
  const ek = s.ek_paketler || {}, ekk = s.ek_kurulum || {};
  const ekEksik = [!ek.karekod && "karekod okuma", !ek.el_yazisi && "çekte el yazısı okuma"].filter(Boolean);
  if (s.ek_paketler && ekEksik.length) {
    const satir = h("div", { class: "uyari-satiri" });
    // Kur'a basınca ne olduğu satırda yazar; program içinden kuruluyorsa bitene kadar izlenir
    const yaz = (d) => {
      const kur = BEN.rol === "sahip" && !["kuruluyor", "yeniden_baslatiliyor", "bitti"].includes(d.durum) ? h("button", { class: "dugme kucuk", onclick: async (e) => {
        e.target.disabled = true;
        try { yaz(await api("/api/sistem/ek-paket-kur", { metod: "POST" })); izle(); } catch (err) { bildir(err.message, true); e.target.disabled = false; }
      } }, d.durum === "hata" ? "Tekrar dene" : "Kur") : "";
      satir.replaceChildren(
        d.durum === "yeniden_baslatiliyor" ? "Kurulum için program yeniden açılıyor. Siyah pencerede kurulum yazılarını göreceksiniz (internet gerekir, birkaç dakika sürebilir); bitince program kendiliğinden açılır."
          : d.durum === "kuruluyor" ? "Paketler kuruluyor, birkaç dakika sürebilir…"
            : d.durum === "bitti" ? "Paketler kuruldu; çek okuma artık tam çalışıyor."
              : d.durum === "hata" ? `${d.hata} `
                : `${(ekEksik.join(" ve ")).replace(/^./, (c) => c.toLocaleUpperCase("tr"))} paketi kurulu değil (çek okuma bunlarla tam çalışır). `, kur);
    };
    const izle = () => {
      const t = setInterval(async () => {
        if (!satir.isConnected) return clearInterval(t);
        try {
          const sd = await api("/api/sistem-durumu");
          const d = sd.ek_kurulum || {};
          if (sd.ek_paketler?.karekod && sd.ek_paketler?.el_yazisi) { clearInterval(t); yaz({ durum: "bitti" }); }
          else if (!["kuruluyor", "yeniden_baslatiliyor"].includes(d.durum)) { clearInterval(t); yaz(d); }
        } catch { /* program yeniden açılıyor olabilir */ }
      }, 5000);
    };
    yaz(ekk);
    if (["kuruluyor", "yeniden_baslatiliyor"].includes(ekk.durum)) izle();
    satirlar.push(satir);
  }
  if (s.ek_paket_hatasi) satirlar.push(h("div", { class: "uyari-satiri" }, `${s.ek_paket_hatasi} İnternet varken programı yeniden açınca tekrar denenir.`));
  const g = s.guncelleme || {};
  if (g.sonuc) satirlar.push(h("div", { class: /yapılamadı|açılamadı/.test(g.sonuc) ? "uyari-satiri hata" : "bilgi-satiri" },
    `Güncelleme: ${g.sonuc} `, h("a", { href: "#", onclick: async (e) => { e.preventDefault(); await api("/api/sistem/guncelleme/sonucu-okundu", { metod: "POST" }).catch(() => {}); e.target.parentElement.remove(); } }, "Tamam")));
  if (g.son_denetim?.var || ["hazirlaniyor", "yeniden_baslatiliyor", "hata"].includes(g.durum)) satirlar.push(guncellemeSatiri(g));
  const y = s.son_yedek, d = s.son_deneme;
  if (y && !y.ok) satirlar.push(h("div", { class: "uyari-satiri hata" }, `Son yedek alınamadı: ${y.hata} `, h("a", { href: "#", onclick: (e) => { e.preventDefault(); yedeklerAc(); } }, "Yedekler")));
  else if (y && y.hata) satirlar.push(h("div", { class: "uyari-satiri" }, `Yedek bazı klasörlere yazılamadı: ${y.hata}`));
  if (d && !d.ok) satirlar.push(h("div", { class: "uyari-satiri hata" }, `Son yedek denendi ama açılamadı: ${d.hata} Yeni yedek alın.`));
  else if (d && d.ok) satirlar.push(h("div", { class: "bilgi-satiri" }, `Son yedek ${new Date(d.zaman).toLocaleDateString("tr-TR")} tarihinde denendi, sorunsuz açılıyor.`));
  return satirlar.length ? h("div", {}, satirlar) : "";
}

// Yeni sürüm: "Güncelle" ile program kendini günceller (önce yedek; veri ve ayarlar değişmez)
function guncellemeSatiri(g) {
  const satir = h("div", { class: "uyari-satiri" });
  const yaz = (d) => {
    const dugme = BEN.rol === "sahip" && !["hazirlaniyor", "yeniden_baslatiliyor"].includes(d.durum) ? h("button", { class: "dugme kucuk", onclick: async (e) => {
      if (!confirm(`Yeni sürüm (${g.son_denetim?.yeni || ""}) yüklensin mi?\n\nÖnce verilerinizin yedeği alınır. Verileriniz ve ayarlarınız değişmez. Program kapanıp yeni sürümle kendiliğinden açılır; yeni sürüm açılamazsa eski sürüme dönülür.`)) return;
      e.target.disabled = true;
      try { yaz(await api("/api/sistem/guncelle", { metod: "POST" })); izle(); } catch (err) { bildir(err.message, true); e.target.disabled = false; }
    } }, d.durum === "hata" ? "Tekrar dene" : "Güncelle") : "";
    satir.replaceChildren(d.durum === "hazirlaniyor" ? "Yeni sürüm indiriliyor ve verileriniz yedekleniyor…"
      : d.durum === "yeniden_baslatiliyor" ? "Program yeni sürümle yeniden açılıyor. Siyah pencere açılıp kapanacak; sayfa kendiliğinden yenilenir."
        : d.durum === "hata" ? `${d.hata} ` : `Yeni sürüm var (${g.son_denetim?.yeni}). `, dugme);
  };
  const izle = () => {
    let kapandi = false;
    const t = setInterval(async () => {
      if (!satir.isConnected) return clearInterval(t);
      try {
        const sd = await api("/api/sistem-durumu");
        const d = sd.guncelleme || {};
        if (kapandi || (!d.durum && !d.son_denetim?.var)) { clearInterval(t); location.reload(); }
        else if (!["hazirlaniyor", "yeniden_baslatiliyor"].includes(d.durum)) { clearInterval(t); yaz(d); }
      } catch { kapandi = true; /* program yeniden açılıyor */ }
    }, 4000);
  };
  yaz(g);
  if (["hazirlaniyor", "yeniden_baslatiliyor"].includes(g.durum)) izle();
  return satir;
}

async function guncellemeleriDenetle() {
  durum("Yeni sürüm denetleniyor…");
  try {
    const d = await api("/api/sistem/guncelleme/denetle", { metod: "POST" });
    durum("Hazır");
    if (d.var) {
      if (BEN.rol !== "sahip") return alert(`Yeni sürüm var (${d.yeni}). Güncellemeyi şirket sahibi yapabilir.`);
      $("#sekme-icerik").prepend(guncellemeSatiri({ son_denetim: d }));  // "Güncelle" düğmesiyle ekranın üstünde
    } else alert(d.hata || `Program güncel (${d.simdiki}).`);
  } catch (e) { durum("Hazır"); bildir(e.message, true); }
}

// ---------------------------------------------------------------- gösterge paneli
async function gostergePaneli(el) {
  let o, y;
  try { [o, y] = await Promise.all([api("/api/raporlar/ozet"), api("/api/raporlar/yaslandirma")]); } catch (e) { return bildir(e.message, true); }
  const gecen = (tur) => y.acik_faturalar.filter((x) => x.tur === tur && x.gecen_gun > 0).reduce((t, x) => t + x.acik_tutar, 0);
  const kart = (baslik, satirlar, dugme) => h("div", { class: "ozet-kart" }, h("h3", {}, baslik),
    h("dl", {}, satirlar.flatMap(([a, v, sinif]) => [h("dt", {}, a), h("dd", { class: sinif || "" }, v)])),
    dugme ? h("div", { style: "padding:0 10px 10px" }, dugme) : null);
  let takvim = null;
  try { takvim = (await api("/api/raporlar/nakit-akisi?gun=30")).ozet; } catch { /* kart gösterilmez */ }
  let kontrol = { sorunlu: [], sorunlu_faturalar: [], otomatik_duzeltilen: 0, tutari_degisen: 0 };
  try { kontrol = await api("/api/cariler/kontrol"); } catch { /* kontrol listesi gösterilmez */ }
  let sistem = null;
  try { sistem = await api("/api/sistem-durumu"); } catch { /* sistem satırı gösterilmez */ }
  let vadeli = [];
  try { vadeli = await api(`/api/cekler/vadesi-gelen?gun=${vadeOncedenGun()}`); } catch { /* liste gösterilmez */ }
  // Kısa özet satırı; "Göster" ile sade tablo açılır, satıra tıklayınca kayıt açılır
  const sorunKutusu = (ozet, basliklar, satirlar) => {
    const tablo = h("div", { class: "tablo-kap sorun-tablo", hidden: true }, h("table", { class: "liste" },
      h("thead", {}, h("tr", {}, basliklar.map(([b, sinif]) => h("th", { class: sinif || "" }, b)))),
      h("tbody", {}, satirlar.map(([hucreler, ac]) => h("tr", { class: "tiklanir", onclick: ac },
        hucreler.map(([v, sinif]) => h("td", { class: sinif || "" }, v)))))));
    const dugme = h("button", { class: "dugme", onclick: () => { tablo.hidden = !tablo.hidden; dugme.textContent = tablo.hidden ? "Göster" : "Gizle"; } }, "Göster");
    return h("div", { class: "hata-kutu sorun-kutu" }, h("div", { class: "sorun-ozet" }, h("b", {}, ozet), dugme), tablo);
  };
  const sf = kontrol.sorunlu_faturalar || [];
  el.append(h("div", { class: "liste-ust" }, h("h2", {}, "Genel Durum"), h("span", {}, new Date().toLocaleDateString("tr-TR"))),
    vadeli.length ? sorunKutusu(`${vadeli.length} çekin vadesi geldi`, [["Vade"], ["Ne yapılacak"], ["Çek No"], ["Cari"], ["Tutar", "sayi"]],
      vadeli.map((c) => [[[vadeHucresi(c)], [c.yon === "alinan" ? "Tahsil edilecek" : "Ödenecek"], [c.cek_no || ""], [c.cari_unvan || c.kesideci || ""],
        [para(c.tutar), "sayi"]], () => cekFormAc(c, c.yon)])) : "",
    sf.length ? sorunKutusu(`${sf.length} faturada sorun var`, [["Fatura No"], ["Cari"], ["Tutar", "sayi"], ["Sorun"]],
      sf.map((f) => [[[f.fatura_no], [f.cari], [para(f.genel_toplam) + (f.para_birimi && f.para_birimi !== "TRY" ? " " + f.para_birimi : ""), "sayi"], [f.sorun, "sorun-metni"]],
        () => faturaFormAc({ id: f.id }, null)])) : "",
    kontrol.sorunlu.length ? sorunKutusu(`${kontrol.sorunlu.length} carinin bilgisi düzeltilmeli`, [["Cari"], ["VKN"], ["Sorun"]],
      kontrol.sorunlu.map((c) => [[[c.unvan], [c.vkn || ""], [c.neden.charAt(0).toUpperCase() + c.neden.slice(1) + ".", "sorun-metni"]], () => cariFormAc(c)])) : "",
    sistemSatirlari(sistem),
    // Eski sürümden kalan kayıtların kendiliğinden düzeltilmesi teknik ayrıntıdır; yalnız tutarı değişen fatura varsa söylenir
    kontrol.tutari_degisen ? h("div", { class: "bilgi-satiri" }, `${kontrol.tutari_degisen} faturanın tutarı, faturada yazan tutara göre düzeltildi.`) : "",
    h("div", { class: "kart-satiri" },
      kart("Banka / Kasa", [["Banka toplam bakiye", para(o.banka_toplam), o.banka_toplam < 0 ? "negatif" : ""],
        ["Nakit kasa", para(o.kasa_bakiye), o.kasa_bakiye < 0 ? "negatif" : ""],
        ...(o.kart_borcu ? [["Kredi kartı borcu", para(o.kart_borcu), "negatif"]] : [])],
        h("div", { class: "dugmeler", style: "margin:0" }, h("button", { class: "dugme", onclick: bankaHesaplariAc }, "Hesaplar"),
          h("button", { class: "dugme", onclick: kasaAc }, "Kasa"))),
      kart("Çekler", [["Portföydeki alınan", para(o.portfoy_cek)], ["Ödenecek verilen", para(o.odenecek_cek)],
        ["7 gün içinde vadesi gelen alınan", `${o.yaklasan_alinan} adet`],
        ["7 gün içinde ödenecek", `${o.yaklasan_verilen} adet · ${para(o.yaklasan_verilen_tutar)}`, o.yaklasan_verilen ? "negatif" : ""]],
        h("button", { class: "dugme", onclick: vadeTakvimiAc }, "Vade takvimi")),
      kart("Cariler", [["Toplam alacağımız", para(o.alacak_toplam)], ["Toplam borcumuz", para(o.borc_toplam)],
        ["Vadesi geçmiş alacak", para(gecen("alacak")), gecen("alacak") ? "negatif" : ""],
        ["Vadesi geçmiş borç", para(gecen("borc")), gecen("borc") ? "negatif" : ""]],
        h("div", { class: "dugmeler", style: "margin:0" }, h("button", { class: "dugme", onclick: cariBakiyeAc }, "Cari bakiyeler"),
          h("button", { class: "dugme", onclick: yaslandirmaAc }, "Yaşlandırma"))),
      takvim ? kart("Ödeme takvimi", [["7 gün içinde tahsil edilecek", para(takvim.hafta_giris)],
        ["7 gün içinde ödenecek", para(takvim.hafta_cikis), takvim.hafta_cikis ? "negatif" : ""],
        ["Vadesi geçmiş ödenmemiş", para(takvim.gecikmis_cikis), takvim.gecikmis_cikis ? "negatif" : ""],
        ["30 günde en düşük bakiye", para(takvim.en_dusuk_bakiye), takvim.en_dusuk_bakiye < 0 ? "negatif" : ""]],
        h("div", { class: "dugmeler", style: "margin:0" }, h("button", { class: "dugme", onclick: odemeTakvimiAc }, "Ödeme takvimi"),
          h("button", { class: "dugme", onclick: duzenliOdemelerAc }, "Düzenli ödemeler"))) : "",
      kart("Onay bekleyenler", [["Fatura", `${o.taslak_fatura} adet`], ["Banka hareketi", `${o.taslak_hareket} adet`]],
        h("div", { class: "dugmeler", style: "margin:0" },
          h("button", { class: "dugme", onclick: () => faturaListesiAc("gelen") }, "Faturalar"),
          h("button", { class: "dugme", onclick: taslakHareketlerAc }, "Hareketler")))),
    h("div", { class: "dugmeler", style: "margin-top:14px" },
      h("button", { class: "dugme ana", onclick: aiOkumaAc }, "Belgeden fatura oku"),
      h("button", { class: "dugme ana", onclick: () => ekstreYukleAc() }, "Banka ekstresi yükle"),
      h("button", { class: "dugme", onclick: () => ekstreYukleAc("kart") }, "Kart ekstresi yükle"),
      h("button", { class: "dugme", onclick: () => cekFormAc(null, "alinan") }, "Çek al"),
      h("button", { class: "dugme", onclick: () => cekFormAc(null, "verilen") }, "Çek ver")));
}

// ---------------------------------------------------------------- ortak seçenekler
let HAREKET_TURLERI = {};
const secenekListesi = (dizi, alanAd, bos) => [["", bos], ...dizi.map((x) => [x.id, x[alanAd]])];
async function tumSecenekler() {
  const [cariler, santiyeler, hesaplar] = await Promise.all([api("/api/cariler"), api("/api/santiyeler"), api("/api/banka-hesaplari")]);
  return { cariler, santiyeler, hesaplar };
}
function kalanGun(vade) {
  const bugun = new Date(); bugun.setHours(0, 0, 0, 0);
  return Math.round((new Date(vade + "T00:00:00") - bugun) / 86400000);
}
function vadeHucresi(c) {
  const g = kalanGun(c.vade);
  const kapali = !["portfoyde", "tahsilde", "teminatta", "verildi"].includes(c.durum);
  return h("span", { class: !kapali && g < 0 ? "negatif" : "", style: !kapali && g >= 0 && g <= 7 ? "font-weight:600;color:#8a6100" : "" },
    tarih(c.vade), !kapali ? ` (${g < 0 ? -g + " gün geçti" : g === 0 ? "bugün" : g + " gün"})` : "");
}

// ---------------------------------------------------------------- çekler
// Çekin akıbeti (Wolvox'taki evrak durumu): alınan çek portföyde kalır, ciro edilir (cariye), takasa/teminata verilir
// (banka hesabına), tahsil edilir (banka ya da kasa). Verilen çek: ödenmedi, bankadan/kasadan ödendi, iade alındı.
const CEK_AKIBETLERI = {
  alinan: [["", "Portföyde"], ["ciro", "Ciro edildi", "cari"], ["tahsile_ver", "Takasa verildi", "banka"], ["teminata_ver", "Teminata verildi", "banka"],
    ["tahsil", "Tahsil edildi (bankaya)", "banka"], ["tahsil_kasa", "Tahsil edildi (kasaya)"], ["portfoye_al", "Portföye geri alındı"],
    ["karsiliksiz", "Karşılıksız / protesto"], ["iade", "İade edildi"]],
  verilen: [["", "Ödenmedi"], ["ode", "Bankadan ödendi", "banka"], ["ode_kasa", "Kasadan ödendi"], ["iade", "İade alındı"]],
};
// Hangi durumdayken hangi akıbet seçilebilir (sunucudaki kuralla aynı)
const CEK_IZINLI = {
  portfoyde: ["ciro", "tahsile_ver", "teminata_ver", "tahsil", "tahsil_kasa", "karsiliksiz", "iade"],
  tahsilde: ["tahsil", "tahsil_kasa", "portfoye_al", "karsiliksiz"],
  teminatta: ["tahsile_ver", "tahsil", "tahsil_kasa", "portfoye_al", "karsiliksiz"],
  ciro_edildi: ["karsiliksiz"],
  verildi: ["ode", "ode_kasa", "iade"],
};
/** Seçicideki değeri sunucunun beklediği işleme çevirir ("tahsil_kasa" -> tahsil + kasa). */
function akibetVerisi(a, tarih) {
  if (!a?.islem) return null;
  const kasa = a.islem.endsWith("_kasa");
  return { islem: kasa ? a.islem.replace("_kasa", "") : a.islem, kasa, tarih,
    cari_id: a.islem === "ciro" ? a.cari_id || null : null, banka_hesap_id: kasa ? null : a.banka_hesap_id || null };
}
/** Akıbet seçici: işlem + gerekiyorsa ciro edilen cari (yazarak aranır) ya da banka hesabı.
 * a: { islem, cari_id, banka_hesap_id } nesnesi yerinde değiştirilir; degisti() her değişiklikte çağrılır. */
function akibetSecici(yon, a, { cariler, hesaplar }, degisti = () => {}, durum = null) {
  // durum: null = giriş ekranı (portföyde/ödenmedi dahil), "*" = toplu işlem (tüm işlemler), yoksa o durumda yapılabilenler
  const izinli = durum === "*" ? CEK_AKIBETLERI[yon].map(([d]) => d).filter(Boolean) : durum ? CEK_IZINLI[durum] || [] : null;
  const secenekler = CEK_AKIBETLERI[yon].filter(([d]) => (izinli ? d && izinli.includes(d) : d !== "portfoye_al"));
  const islemS = h("select", { class: "akibet-islem" }, (izinli ? [["", "— İşlem seçin —"], ...secenekler] : secenekler)
    .map(([d, m]) => h("option", { value: d, selected: d === (a.islem || "") }, m)));
  const cariS = h("select", {}, [["", "— Ciro edilen cari —"], ...cariler.map((c) => [String(c.id), c.unvan])]
    .map(([d, m]) => h("option", { value: d, selected: d === String(a.cari_id ?? "") }, m)));
  const bankaS = h("select", {}, [["", "— Banka hesabı —"], ...hesaplar.filter((b) => b.tur !== "kredi_karti").map((b) => [String(b.id), b.ad])]
    .map(([d, m]) => h("option", { value: d, selected: d === String(a.banka_hesap_id ?? "") }, m)));
  const cariKap = h("span", { class: "akibet-cari" }, cariS);
  const kap = h("span", { class: "akibet-secici" }, islemS, cariKap, bankaS);
  aramaliSec(cariS, { bosYazi: "— Ciro edilen cari —", yeniIpucu: "Yeni cari için adını yazın", yeniYazi: (ad) => `+ "${ad}" adıyla yeni cari aç`,
    yeniAc: async (ad) => {
      const b = await benzerCariKontrol(ad);
      if (b == null) return null;
      let c = b;
      if (b === "yeni") {
        try { c = await api("/api/cariler", { metod: "POST", veri: { unvan: ad } }); } catch (e) { bildir(e.message, true); return null; }
        bildir(`'${c.unvan}' carisi açıldı.`); listeyiTazele("cariler");
      }
      if (!cariler.some((y) => y.id === c.id)) cariler.push(c);
      if (![...cariS.options].some((o) => o.value === String(c.id))) cariS.append(h("option", { value: c.id }, c.unvan));
      return c.id;
    } });
  const goster = () => {
    const ne = CEK_AKIBETLERI[yon].find(([d]) => d === islemS.value)?.[2];
    cariKap.hidden = ne !== "cari"; bankaS.hidden = ne !== "banka";
  };
  islemS.addEventListener("change", () => { a.islem = islemS.value || null; goster(); degisti(); });
  cariS.addEventListener("change", () => { a.cari_id = Number(cariS.value) || null; degisti(); });
  bankaS.addEventListener("change", () => { a.banka_hesap_id = Number(bankaS.value) || null; degisti(); });
  goster();
  kap.ayarla = (yeni) => { Object.assign(a, yeni); islemS.value = a.islem || ""; cariS.value = String(a.cari_id ?? ""); cariS.tazele?.(); bankaS.value = String(a.banka_hesap_id ?? ""); goster(); };
  return kap;
}
/** Seçilen çeklere aynı işlem: ödendi (banka/kasa), tahsil, ciro, takas, teminat... Yapılamayanların nedeni söylenir. */
function cekTopluIslemAraci(yon) {
  const a = {};
  const tarihG = h("input", { type: "date", value: new Date().toISOString().slice(0, 10), title: "İşlem tarihi" });
  const kap = h("span", { style: "display:inline-flex;gap:6px;align-items:center" }, tarihG);
  tumSecenekler().then((sec) => kap.prepend(akibetSecici(yon, a, sec, () => {}, "*"))).catch(() => {});
  return { ad: "Seçilenlere uygula", ek: kap,
    islem: async (sec) => {
      const v = akibetVerisi(a, tarihG.value);
      if (!v) { bildir("Yapılacak işlemi seçin.", true); return false; }
      const r = await api("/api/cekler/toplu-islem", { metod: "POST", veri: { ...v, idler: sec.map((c) => c.id) } });
      bildir(`${r.yapilan} çeke işlendi.` + (r.hatalar.length ? ` ${r.hatalar.length} çeke yapılamadı.` : ""), r.hatalar.length > 0);
      if (r.hatalar.length) alert(`Yapılamayanlar:\n\n${r.hatalar.join("\n")}`);
      cekEkranlariniTazele();
    } };
}
function cekEkranlariniTazele() {
  for (const l of ["cekler-alinan", "cekler-verilen", "vade-takvimi", "cek-raporu", "kasa", "banka-hesaplari", "cariler"]) listeyiTazele(l);
  vadeBildirimiKontrol(false);
}

// Wolvox'taki gibi vade günü (alıştan vadeye) ve kalan vade (eksi = geçti)
const CEK_GUN_KOLONLARI = [
  { alan: "vade_gunu", baslik: "Vade Günü", deger: (c) => c.vade_gunu ?? "" },
  { alan: "kalan_gun", baslik: "Kalan Gün", deger: (c) => (c.kalan_gun == null ? "" : h("span", { class: c.kalan_gun < 0 ? "negatif" : "" }, c.kalan_gun)), metin: (c) => c.kalan_gun ?? "" },
  { alan: "islem_tarihi", baslik: "İşlem / Ödendiği Tarih", tip: "tarih" },
];

function cekListesiAc(yon) {
  const ad = yon === "alinan" ? "Alınan Çekler" : "Verilen Çekler";
  let durumFiltre = yon === "alinan" ? "portfoyde,tahsilde,teminatta" : "verildi";
  sekmeAc(`cekler-${yon}`, ad, listeEkrani({
    baslik: ad,
    kaynak: () => api(`/api/cekler?yon=${yon}${durumFiltre ? `&durum=${durumFiltre}` : ""}`),
    ustAlan: (yenile) => h("span", { class: "dugmeler", style: "margin:0" }, h("select", { onchange: (e) => { durumFiltre = e.target.value; yenile(); } },
      (yon === "alinan"
        ? [["portfoyde,tahsilde,teminatta", "Elimizdekiler"], ["portfoyde", "Portföyde"], ["tahsilde", "Takasta"], ["teminatta", "Teminatta"],
          ["ciro_edildi", "Ciro edilenler"], ["tahsil_edildi", "Tahsil edilenler"], ["karsiliksiz", "Karşılıksız / protesto"], ["iade", "İade edilenler"], ["", "Tümü"]]
        : [["verildi", "Ödenmedi"], ["odendi", "Ödenenler"], ["iade", "İade alınanlar"], ["", "Tümü"]])
        .map(([d, m]) => h("option", { value: d, selected: d === durumFiltre }, m))),
      h("button", { class: "dugme", onclick: () => yazdirAc(`/api/yazdir/cek-bordro?yon=${yon}&durum=${durumFiltre}`) }, "Bordro yazdır"),
      h("button", { class: "dugme", onclick: () => topluCekAc(yon) }, "Toplu giriş / fotoğraftan oku")),
    kolonlar: [
      { alan: "durum_adi", baslik: "Durum" },
      { alan: "vade", baslik: "Vade", deger: vadeHucresi, metin: (c) => tarih(c.vade) },
      { alan: "cek_no", baslik: "Çek No" }, { alan: "banka", baslik: "Banka" }, { alan: "kesideci", baslik: "Çeki Yazan Firma" },
      { alan: "lehtar", baslik: "Lehtar (çekin yazıldığı firma)" },
      { alan: "cari_unvan", baslik: yon === "alinan" ? "Kimden Alındı" : "Kime Verildi" },
      ...(yon === "alinan" ? [{ alan: "ciro_cari_unvan", baslik: "Ciro Edilen" }] : []),
      { alan: "banka_hesap_ad", baslik: yon === "alinan" ? "Takas / Teminat Bankası" : "Ödenen Hesap" },
      ...CEK_GUN_KOLONLARI,
      { alan: "tutar", baslik: "Tutar", tip: "para" },
    ],
    toplamlar: ["tutar"],
    yeni: () => cekFormAc(null, yon),
    ac: (c) => cekFormAc(c, yon),
    sil: (c) => api(`/api/cekler/${c.id}`, { metod: "DELETE" }),
    toplu: [cekTopluIslemAraci(yon),
      { ad: "Seçilenleri sil", tehlikeli: true, islem: (sec) => topluSil(sec, "çek", (c) => `Çek ${c.cek_no || c.id}`, (c) => `/api/cekler/${c.id}`) }],
    excel: `/api/excel/cekler?yon=${yon}`,
  }));
}

function vadeTakvimiAc() {
  sekmeAc("vade-takvimi", "Vade Takvimi", listeEkrani({
    baslik: "Çek Vade Takvimi",
    kaynak: () => api("/api/cekler?durum=portfoyde,tahsilde,teminatta,verildi"),
    kolonlar: [
      { alan: "vade", baslik: "Vade", deger: vadeHucresi, metin: (c) => tarih(c.vade) },
      { alan: "yon", baslik: "Yön", deger: (c) => (c.yon === "alinan" ? "Alınan" : "Verilen") },
      { alan: "durum_adi", baslik: "Durum" }, { alan: "cek_no", baslik: "Çek No" }, { alan: "banka", baslik: "Banka" },
      { alan: "cari_unvan", baslik: "Cari" },
      { alan: "giris", baslik: "Tahsil Edilecek", tip: "para", deger: (c) => (c.yon === "alinan" ? c.tutar : null) },
      { alan: "cikis", baslik: "Ödenecek", tip: "para", deger: (c) => (c.yon === "verilen" ? c.tutar : null) },
    ],
    ac: (c) => cekFormAc(c, c.yon),
    excel: "/api/excel/cekler",
  }));
}

function cekFormAc(cek, yon) {
  yon = cek?.yon || yon;
  const s = sekmeAc(cek ? `cek-${cek.id}` : `cek-yeni-${Date.now()}`, cek ? `Çek ${cek.cek_no || "#" + cek.id}` : yon === "alinan" ? "Yeni Alınan Çek" : "Yeni Verilen Çek", {
    async ciz(el) {
      if (cek) { try { cek = await api(`/api/cekler/${cek.id}`); } catch (e) { return bildir(e.message, true); } }
      const { cariler, santiyeler, hesaplar } = await tumSecenekler();
      const c = cek || { yon, tur: "cek", para_birimi: "TRY", alis_tarihi: new Date().toISOString().slice(0, 10) };
      const kilitli = cek && !["portfoyde", "verildi"].includes(cek.durum);
      const form = h("form", { class: "form-pencere", onsubmit: (e) => { e.preventDefault(); this.kaydet(); } });
      const onizleme = h("div");
      const okuGirdi = h("input", { type: "file", accept: "image/*,application/pdf,.heic,.heif", hidden: true, onchange: async (e) => {
        const fd = new FormData(); fd.append("dosya", e.target.files[0]); e.target.value = "";
        durum("Çek okunuyor…");
        try {
          const r = await api("/api/cekler/oku", { metod: "POST", dosya: fd });
          for (const x of form.querySelectorAll(".belirsiz")) x.classList.remove("belirsiz");
          for (const a of ["tur", "cek_no", "banka", "sube", "hesap_no", "kesideci", "kesideci_vkn", "lehtar", "tutar", "para_birimi", "vade", "kaynak_dosya"]) {
            if (r[a] != null && form.elements[a]) form.elements[a].value = r[a];
          }
          for (const a of r.belirsiz || []) form.elements[a]?.classList.add("belirsiz");
          const uyarilar = [r.belge_cek_mi === false ? "Yüklenen belge çek gibi görünmüyor." : null, r.sorun || null, r.notlar || null,
            r.belirsiz?.length ? "Kırmızı alanlar net okunamadı; çekteki ile karşılaştırın." : null].filter(Boolean);
          onizleme.replaceChildren(h("div", { class: "uyari-kutu" }, h("b", {}, "Çek okundu. Bilgileri kontrol edip kaydedin."),
            uyarilar.length ? h("ul", {}, uyarilar.map((u) => h("li", {}, u))) : null));
          durum("Çek okundu");
        } catch (err) { bildir(err.message, true); durum("Hazır"); }
      } });
      form.append(...[
        h("h2", {}, yon === "alinan" ? "Alınan Çek / Senet" : "Verilen Çek / Senet", cek ? ` · ${cek.durum_adi}` : ""),
        !cek ? h("div", { class: "dugmeler", style: "margin:0 0 8px" },
          h("button", { type: "button", class: "dugme", onclick: () => okuGirdi.click() }, "Çek fotoğrafından oku"), okuGirdi,
          h("button", { type: "button", class: "dugme", onclick: () => topluCekAc(yon) }, "Birden çok çek: toplu giriş")) : null,
        onizleme,
        h("input", { type: "hidden", name: "kaynak_dosya", value: c.kaynak_dosya || "" }),
        h("fieldset", {}, h("legend", {}, "Çek Bilgileri"), h("div", { class: "alanlar" },
          alan("Tür", "tur", c.tur, { secenekler: [["cek", "Çek"], ["senet", "Senet"]] }),
          alan("Çek / Senet No", "cek_no", c.cek_no), alan("Vade", "vade", c.vade, { tip: "date", zorunlu: true }),
          alan("Tutar", "tutar", c.tutar, { tip: "number", zorunlu: true }), alan("Para Birimi", "para_birimi", c.para_birimi),
          alan("Banka", "banka", c.banka), alan("Şube", "sube", c.sube), alan("Hesap No", "hesap_no", c.hesap_no),
          alan("Çeki yazan firma", "kesideci", c.kesideci), alan("Çeki yazan firma VKN / TCKN", "kesideci_vkn", c.kesideci_vkn),
          alan("Lehtar (çekin yazıldığı firma)", "lehtar", c.lehtar))),
        h("fieldset", {}, h("legend", {}, "Cari ve Şantiye"), h("div", { class: "alanlar" },
          alan(yon === "alinan" ? "Kimden alındı" : "Kime verildi", "cari_id", c.cari_id, { secenekler: secenekListesi(cariler, "unvan", "— Cari seçin —") }),
          alan(yon === "alinan" ? "Alış tarihi" : "Veriliş tarihi", "alis_tarihi", c.alis_tarihi, { tip: "date" }),
          santiyeAlani("Şantiye", c.santiye_id, santiyeler),
          alan("Özel kod", "ozel_kod", c.ozel_kod),
          alan("Açıklama", "aciklama", c.aciklama, { genis: true }))),
        h("div", { class: "dugmeler" }, h("button", { class: "dugme ana" }, "Kaydet (F2)"),
          cek?.kaynak_dosya ? h("button", { type: "button", class: "dugme", onclick: () => belgeAc(`/api/cekler/${cek.id}/belge`) }, "Görseli göster") : null),
      ].filter(Boolean));
      if (kilitli) for (const a of ["tutar", "cari_id"]) form.elements[a].disabled = true;

      if (cek) {
        // Wolvox çek kartındaki bilgiler: evrak durumu, vade günü, kalan vade, ödendiği tarih
        form.append(h("fieldset", {}, h("legend", {}, "Durum"), h("div", { class: "alanlar" },
          h("label", {}, "Evrak durumu", h("input", { value: cek.durum_adi, disabled: true })),
          h("label", {}, "Vade günü", h("input", { value: cek.vade_gunu ?? "", disabled: true })),
          h("label", {}, "Kalan vade (gün)", h("input", { value: cek.kalan_gun ?? "", disabled: true, class: cek.kalan_gun < 0 ? "belirsiz" : "" })),
          h("label", {}, yon === "alinan" ? "Ciro / tahsil / takas tarihi" : "Ödendiği tarih", h("input", { value: tarih(cek.islem_tarihi) || "", disabled: true })),
          cek.ciro_cari_unvan ? h("label", {}, "Ciro edilen", h("input", { value: cek.ciro_cari_unvan, disabled: true })) : null,
          cek.banka_hesap_ad ? h("label", {}, "Banka hesabı", h("input", { value: cek.banka_hesap_ad, disabled: true })) : null)));
      }
      if (cek && CEK_IZINLI[cek.durum]?.length) {
        const a = { banka_hesap_id: cek.banka_hesap_id };
        const tarihG = h("input", { type: "date", value: new Date().toISOString().slice(0, 10) });
        const yap = async () => {
          const v = akibetVerisi(a, tarihG.value);
          if (!v) return bildir("Yapılacak işlemi seçin.", true);
          try {
            await api(`/api/cekler/${cek.id}/islem`, { metod: "POST", veri: v });
            bildir("Çek işlemi kaydedildi.");
            cekEkranlariniTazele();
            yenidenCiz();
          } catch (e) { bildir(e.message, true); }
        };
        form.append(h("fieldset", {}, h("legend", {}, "Çek İşlemi (ciro, takas, teminat, ödendi / tahsil edildi)"),
          h("div", { class: "alanlar" }, h("label", { class: "genis" }, "İşlem", akibetSecici(yon, a, { cariler: cariler.filter((x) => x.id !== cek.cari_id), hesaplar }, () => {}, cek.durum)),
            h("label", {}, "İşlem tarihi", tarihG)),
          h("p", { class: "ipucu" }, "Bankadan ödendi / tahsil edildi seçilince para o banka hesabının hareketlerine, kasadan seçilince Nakit Kasa'ya işlenir. Aynı tutar ekstreden gelmişse ikinci kez yazılmaz."),
          h("div", { class: "dugmeler" }, h("button", { type: "button", class: "dugme ana", onclick: yap }, "İşlemi kaydet"))));
      }
      el.append(form);
      this.form = form;
    },
    async kaydet() {
      if (!this.form.reportValidity()) return;
      const v = formVerisi(this.form, ["tutar", "cari_id", "santiye_id"]);
      v.yon = yon;
      if (cek) { v.tutar = v.tutar ?? cek.tutar; v.cari_id = this.form.elements.cari_id.disabled ? cek.cari_id : v.cari_id; }
      v.para_birimi = v.para_birimi || "TRY";
      try {
        cek = cek ? await api(`/api/cekler/${cek.id}`, { metod: "PUT", veri: v }) : await api("/api/cekler", { metod: "POST", veri: v });
        bildir("Çek kaydedildi.");
        s.baslik = `Çek ${cek.cek_no || "#" + cek.id}`;
        listeyiTazele(`cekler-${yon}`);
        yenidenCiz();
      } catch (e) { bildir(e.message, true); }
    },
  });
}

// ---------------------------------------------------------------- toplu çek girişi
// Çekler tablo halinde girilir: elle, Excel'den yapıştırarak, Excel şablonundan ya da fotoğraf/PDF okuyarak.
// Satırlar kaydedilene kadar burada bekler (onay ekranı); okumada emin olunamayan alanlar kırmızıdır.
const TOPLU_CEK_ALANLARI = [
  ["tur", "Tür", "secim"], ["cek_no", "Çek / Senet No"], ["banka", "Banka"], ["sube", "Şube"], ["hesap_no", "Hesap No"],
  ["kesideci", "Çeki yazan firma"], ["kesideci_vkn", "Çeki yazan firma VKN"], ["lehtar", "Lehtar (çekin yazıldığı firma)"],
  ["vade", "Vade", "tarih"], ["tutar", "Tutar", "para"],
  ["para_birimi", "Para Birimi"], ["alis_tarihi", "Alış / Veriliş", "tarih"], ["santiye_ad", "Şantiye"], ["aciklama", "Açıklama"],
];
const BANKA_ADLARI = ["Ziraat Bankası", "Halkbank", "VakıfBank", "Akbank", "Garanti BBVA", "İş Bankası", "Yapı Kredi", "QNB", "TEB",
  "DenizBank", "ING", "HSBC", "Şekerbank", "Kuveyt Türk", "Türkiye Finans", "Albaraka Türk", "Ziraat Katılım", "Vakıf Katılım",
  "Emlak Katılım", "Odeabank", "Fibabanka", "Anadolubank", "Alternatif Bank", "Burgan Bank"];

// "12.500,00" / "12500.5" / "₺ 1.250" -> sayı
function sayiCoz(m) {
  if (m == null || m === "") return null;
  if (typeof m === "number") return m;
  let t = String(m).replace(/[^\d,.\-]/g, "");
  if (t.includes(",")) t = t.replace(/\./g, "").replace(",", ".");
  else if ((t.match(/\./g) || []).length > 1 || /\.\d{3}$/.test(t)) t = t.replace(/\./g, "");
  const n = Number(t);
  return t && Number.isFinite(n) ? n : null;
}
// "15.12.2026" / "2026-12-15" -> "2026-12-15"
function tarihCoz(m) {
  const t = String(m ?? "").trim();
  let r = t.match(/^(\d{4})-(\d{1,2})-(\d{1,2})/);
  if (r) return `${r[1]}-${r[2].padStart(2, "0")}-${r[3].padStart(2, "0")}`;
  r = t.match(/^(\d{1,2})[./-](\d{1,2})[./-](\d{4})/);
  return r ? `${r[3]}-${r[2].padStart(2, "0")}-${r[1].padStart(2, "0")}` : null;
}

function topluCekAc(yon = "alinan") {
  const anahtar = () => `toplu-cek-${yon}`;
  const bugun = () => new Date().toISOString().slice(0, 10);
  const yeniSatir = (x = {}) => ({ tur: "cek", para_birimi: "TRY", alis_tarihi: bugun(), belirsiz: [], ...x, _id: Math.random().toString(36).slice(2) });
  let satirlar = [];
  const yukle = () => {
    try { satirlar = JSON.parse(localStorage.getItem(anahtar()) || "[]"); } catch { satirlar = []; }
  };
  const sakla = () => { try { localStorage.setItem(anahtar(), JSON.stringify(satirlar)); } catch { /* depolama kapalı */ } };
  yukle();
  let secenekler = { cariler: [], santiyeler: [], hesaplar: [] };
  const s = sekmeAc("toplu-cek", "Toplu Çek Girişi", {
    async ciz(el) {
      secenekler = await tumSecenekler().catch(() => secenekler);
      const { cariler, santiyeler } = secenekler;
      const govde = h("tbody");
      const ozet = h("span", { class: "ipucu" });
      const doluMu = (x) => TOPLU_CEK_ALANLARI.some(([a]) => !["tur", "para_birimi", "alis_tarihi"].includes(a) && x[a] != null && x[a] !== "");
      const tazeleOzet = () => {
        const dolu = satirlar.filter(doluMu);
        const toplam = dolu.reduce((t, x) => t + (Number(x.tutar) || 0), 0);
        ozet.textContent = `${dolu.length} çek · toplam ${para(toplam)}` + (dolu.some((x) => x.belirsiz?.length) ? " · kırmızı alanları kontrol edin" : "");
      };
      const alanOnayla = (x, b) => {
        x.belirsiz = (x.belirsiz || []).filter((y) => y !== b);
        x.onaylanan = [...new Set([...(x.onaylanan || []), b])];
      };
      const satiriOnayla = (x) => { for (const b of [...(x.belirsiz || [])]) alanOnayla(x, b); };
      const hucre = (x, [a, , tip]) => {
        const kirmizi = x.belirsiz?.includes(a === "kesideci_vkn" ? "vkn" : a);
        const degisti = (deger) => {
          x[a] = deger;
          const b = a === "kesideci_vkn" ? "vkn" : a;
          if (x.belirsiz?.includes(b)) {  // elle düzeltilen kırmızı alan onaylanmış sayılır
            alanOnayla(x, b);
            girdi.classList.add("onayli"); girdi.title = "";
            girdi.parentElement?.querySelector(".onay-tik")?.remove();
          }
          girdi.classList.remove("belirsiz");
          sakla(); tazeleOzet();
        };
        let girdi;
        if (a === "santiye_ad") return santiyeHucresi(x);
        if (tip === "secim") {
          girdi = h("select", { onchange: (e) => degisti(e.target.value) }, [["cek", "Çek"], ["senet", "Senet"]].map(([d, m]) => h("option", { value: d, selected: x[a] === d }, m)));
        } else {
          girdi = h("input", { value: tip === "para" && x[a] != null ? para(x[a]) : x[a] ?? "", type: tip === "tarih" ? "date" : "text",
            list: { banka: "toplu-cek-bankalar", santiye_ad: "toplu-cek-santiyeler" }[a] || null,
            class: tip === "para" ? "sayi" : null,
            onchange: (e) => degisti(tip === "para" ? sayiCoz(e.target.value) : e.target.value.trim() || null) });
          if (tip === "para") girdi.addEventListener("blur", () => { if (x[a] != null) girdi.value = para(x[a]); });
        }
        girdi.dataset.alan = a;
        const b = a === "kesideci_vkn" ? "vkn" : a;
        if (x.onaylanan?.includes(b)) girdi.classList.add("onayli");
        if (!kirmizi) return h("td", {}, girdi);
        girdi.classList.add("belirsiz");
        if (x.nedenler?.[a]) girdi.title = x.nedenler[a];  // neden kırmızı: üstüne gelince görünür
        // ✓: okunan (ya da tahmin edilen) değer doğru; basınca onaylanır, hücre yeşile döner
        const tik = h("button", { type: "button", class: "onay-tik", title: "Doğru, onayla", onclick: () => {
          alanOnayla(x, b); girdi.classList.remove("belirsiz"); girdi.classList.add("onayli"); girdi.title = ""; tik.remove();
          sakla(); tazeleOzet();
        } }, "✓");
        return h("td", { class: "onayli-hucre" }, h("div", { class: "hucre-tik" }, girdi, tik));
      };
      // Şantiye: listeden seçilir, yazarak aranır, yoksa "+ yeni şantiye aç"
      const santiyeHucresi = (x) => {
        if (!x.santiye_id && x.santiye_ad) x.santiye_id = santiyeler.find((st) => aramaAnahtari(st.ad) === aramaAnahtari(x.santiye_ad))?.id ?? null;
        const kap = santiyeSecici(santiyeler, "— Şantiye yok —");
        const sel = kap.secim;
        if (x.santiye_id) { sel.value = String(x.santiye_id); sel.tazele?.(); }
        sel.addEventListener("change", () => {
          const id = Number(sel.value) || null;
          const ad = id ? [...sel.options].find((o) => o.value === sel.value)?.textContent : null;
          if (id && !santiyeler.some((st) => st.id === id)) santiyeler.push({ id, ad });
          x.santiye_id = id; x.santiye_ad = ad;
          sakla();
        });
        const kutu = kap.querySelector(".arama-kutu");
        kutu.dataset.alan = "santiye_ad";
        if (!x.santiye_id && x.santiye_ad) {  // Excel'den/yapıştırmadan gelen, listede olmayan şantiye: kayıtta açılır
          kutu.classList.add("belirsiz");
          kutu.title = `"${x.santiye_ad}" şantiyesi listede yok; kaydedince açılacak. İsterseniz listeden seçin.`;
          kutu.value = x.santiye_ad;
        }
        return h("td", { class: "santiye-hucre" }, kap);
      };
      const ciz = () => {
        govde.replaceChildren(...satirlar.map((x, i) => h("tr", { class: x.sorun ? "hatali" : "" },
          h("td", {}, h("input", { type: "checkbox", checked: !!x._sec, onchange: (e) => { x._sec = e.target.checked; } })),
          h("td", { class: "sayi" }, i + 1),
          ...TOPLU_CEK_ALANLARI.map((t) => hucre(x, t)),
          h("td", { class: "akibet-hucre" }, akibetSecici(yon, (x.akibet ||= {}), secenekler, sakla)),
          h("td", { class: "toplu-sorun" }, x.sorun ? h("span", { class: "negatif" }, x.sorun) : x.dosya_adi ? h("span", { class: "ipucu" }, x.dosya_adi) : ""),
          h("td", { class: "satir-dugmeler" },
            x.belirsiz?.length ? h("button", { type: "button", class: "dugme kucuk onay-tik", title: "Bu satırdaki bütün kırmızı alanları onayla",
              onclick: () => { satiriOnayla(x); sakla(); ciz(); } }, "✓ Tümü") : "",
            h("button", { type: "button", class: "dugme kucuk", title: "Satırı çıkar",
              onclick: () => { satirlar.splice(i, 1); sakla(); ciz(); } }, "✕")))));
        tazeleOzet();
      };
      const ekle = (yeni) => {
        satirlar = satirlar.filter(doluMu).concat(yeni.map((x) => yeniSatir({ ...x, santiye_ad: x.santiye_ad ?? null })));
        if (!satirlar.length) satirlar.push(yeniSatir());
        sakla(); ciz();
      };
      // Excel'den (ya da başka bir tablodan) yapıştırma: hücreler sekmeyle, satırlar alt satırla ayrılır
      govde.addEventListener("paste", (e) => {
        const metin = e.clipboardData?.getData("text") || "";
        if (!/[\t\n]/.test(metin.trim())) return;
        e.preventDefault();
        const tr = e.target.closest("tr");
        let i = [...govde.children].indexOf(tr);
        const ilkAlan = TOPLU_CEK_ALANLARI.findIndex(([a]) => a === e.target.dataset.alan);
        for (const satir of metin.replace(/\r/g, "").split("\n").filter((l) => l.trim())) {
          if (!satirlar[i]) satirlar.push(yeniSatir());
          const x = satirlar[i];
          satir.split("\t").forEach((d, j) => {
            const t = TOPLU_CEK_ALANLARI[ilkAlan + j];
            if (!t) return;
            const [a, , tip] = t;
            d = d.trim();
            x[a] = tip === "para" ? sayiCoz(d) : tip === "tarih" ? tarihCoz(d) : tip === "secim" ? (aramaAnahtari(d).startsWith("senet") ? "senet" : "cek") : d || null;
            if (a === "santiye_ad") x.santiye_id = null;
          });
          i++;
        }
        sakla(); ciz();
        bildir("Yapıştırılan satırlar tabloya eklendi. Kontrol edip kaydedin.");
      });
      // Yapay zekayla oku (isteğe bağlı): kural okumasının boş/kırmızı bıraktığı alanlar yapay zekayla doldurulur
      let yzModu = false;
      const yzIleOku = () => {
        if (!BEN.ai_var) return alert("Yapay zekayla okuma için Claude API anahtarı gerekir.\n\nProgram klasöründeki .env dosyasına\nANTHROPIC_API_KEY=anahtarınız\nsatırını yazıp programı baslat.bat ile yeniden açın.\n\nAnahtar olmadan da çekler normal okunur.");
        let onay = false;
        try { onay = localStorage.getItem("yzCekOnayi") === "1"; } catch { /* tarayıcı izin vermiyor: her seferinde sorulur */ }
        if (!onay) {
          if (!confirm("Yapay zekayla okuma internet üzerinden çalışır:\n\n"
            + "• Programın okuyamadığı ya da kırmızı bıraktığı çeklerin görüntüsü bilgisayarınızdan çıkıp yapay zeka servisine (Anthropic) gönderilir. Sorunsuz okunan çekler gönderilmez.\n"
            + "• Her okuma API hesabınıza ücret yazabilir.\n"
            + "• Sonuçlar taslaktır: kaydetmeden önce kontrol edin.\n\nDevam edilsin mi?")) return;
          try { localStorage.setItem("yzCekOnayi", "1"); } catch { /* yok sayılır */ }
        }
        yzModu = true; resimGirdi.click();
      };
      const resimGirdi = h("input", { type: "file", multiple: true, hidden: true, accept: "image/*,application/pdf,.heic,.heif", onchange: async (e) => {
        const dosyalar = [...e.target.files]; e.target.value = "";
        const yz = yzModu; yzModu = false;
        let okunan = 0, yzAlan = 0; const okunamayan = []; let eksik = [];
        for (const [n, d] of dosyalar.entries()) {
          durum(`Çekler ${yz ? "yapay zekayla " : ""}okunuyor… ${n + 1}/${dosyalar.length}`);
          const fd = new FormData(); fd.append("dosyalar", d);
          try {
            const r = await api(`/api/cekler/oku-toplu${yz ? "?yapay_zeka=true" : ""}`, { metod: "POST", dosya: fd });
            ekle(r.satirlar.map((x) => ({ ...x, sorun: x.sorun || null })));
            okunan += r.satirlar.length; okunamayan.push(...r.okunamayan); eksik = r.eksik || [];
            yzAlan += r.satirlar.reduce((t, x) => t + (x.yz_alanlar?.length || 0), 0);
          } catch (err) { okunamayan.push(`${d.name}: ${err.message}`); }
        }
        durum("Hazır");
        bildir(`${okunan} çek okundu.` + (yz ? ` Yapay zeka ${yzAlan} alan doldurdu.` : "") + (okunan ? " Kırmızı alanları kontrol edip kaydedin." : ""), !okunan);
        // Eksik paket varsa açıkça söylenir; Genel Durum'daki "Kur" düğmesiyle kurulur
        const ekNot = eksik.length ? `\n\n${eksik.join("\n")}\nGenel Durum'daki "Kur" düğmesine basın.` : "";
        if (okunamayan.length || eksik.length) alert(`${okunamayan.length ? `Okunamayanlar:\n\n${okunamayan.join("\n")}` : ""}${ekNot}`.trim());
      } });
      // İsteğe bağlı okuma raporu: çeklerin okuma ayrıntısı (okuma motoru, ham yazı, güven puanı, konum) ZIP olarak iner
      const raporGirdi = h("input", { type: "file", multiple: true, hidden: true, accept: "image/*,application/pdf,.heic,.heif", onchange: async (e) => {
        const fd = new FormData(); for (const d of e.target.files) fd.append("dosyalar", d);
        e.target.value = "";
        durum("Okuma raporu hazırlanıyor…");
        try {
          const blob = await api("/api/cekler/okuma-raporu", { metod: "POST", dosya: fd });
          const a = h("a", { href: URL.createObjectURL(blob), download: "cek-okuma-raporu.zip" });
          a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 1000);
        } catch (err) { bildir(err.message, true); }
        durum("Hazır");
      } });
      const excelGirdi = h("input", { type: "file", hidden: true, accept: ".xlsx", onchange: async (e) => {
        const fd = new FormData(); fd.append("dosya", e.target.files[0]); e.target.value = "";
        try {
          const r = await api(`/api/excel/cekler/onizle?yon=${yon}`, { metod: "POST", dosya: fd });
          ekle(r.satirlar);
          bildir(`${r.satirlar.length} çek tabloya alındı.` + (r.atlanan ? ` ${r.atlanan} satır öteki yönde (${yon === "alinan" ? "verilen" : "alınan"}) olduğu için alınmadı.` : "")
            + (r.toplam_satiri ? ` Excel'deki ${r.toplam_satiri} toplam satırı çek sayılmadı.` : ""));
          if (r.uyari) alert(r.uyari);
        } catch (err) { bildir(err.message, true); }
      } });
      // Seçilen satırlara aynı akıbet: örn. hepsi "X firmasına ciro edildi" ya da "Y bankasına takasa verildi"
      const topluA = {};
      const topluAkibet = h("div", { class: "liste-ust" }, h("span", {}, "Seçilen satırların akıbeti: "),
        akibetSecici(yon, topluA, secenekler),
        h("button", { type: "button", class: "dugme", onclick: () => {
          const sec = satirlar.filter((x) => x._sec);
          if (!sec.length) return bildir("Önce satır başındaki kutucuklardan çek seçin.", true);
          for (const x of sec) x.akibet = { ...topluA };
          sakla(); ciz();
          bildir(`${sec.length} satıra uygulandı.`);
        } }, "Seçilenlere uygula"),
        h("button", { type: "button", class: "dugme", onclick: () => { satirlar.forEach((x) => { x._sec = true; }); ciz(); } }, "Tümünü seç"));
      if (!satirlar.length) satirlar.push(yeniSatir(), yeniSatir(), yeniSatir());
      ciz();
      el.append(h("div", { class: "form-pencere genis-pencere" },
        h("h2", {}, "Toplu Çek Girişi"),
        h("div", { class: "liste-ust" },
          h("label", {}, "Çekler: ", h("select", { onchange: (e) => { yon = e.target.value; yukle(); yenidenCiz(); } },
            [["alinan", "Alınan çekler (müşteriden)"], ["verilen", "Verilen çekler (tedarikçiye)"]].map(([d, m]) => h("option", { value: d, selected: d === yon }, m)))),
          h("button", { type: "button", class: "dugme ana", onclick: () => { yzModu = false; resimGirdi.click(); } }, "Çek fotoğrafı / PDF oku"), resimGirdi,
          h("button", { type: "button", class: "dugme", title: "İsteğe bağlı: okunamayan ya da kırmızı kalan alanları yapay zeka doldurur (Claude API anahtarı gerekir)", onclick: yzIleOku }, "Yapay zekayla oku"),
          h("button", { type: "button", class: "dugme", title: "Çek neden boş ya da kırmızı okundu: seçtiğiniz çek dosyalarının okuma ayrıntısı (ZIP). Kaydetmez.", onclick: () => raporGirdi.click() }, "Okuma raporu (ZIP)"), raporGirdi,
          h("button", { type: "button", class: "dugme", onclick: () => excelGirdi.click() }, "Excel şablonundan al"), excelGirdi,
          h("button", { type: "button", class: "dugme", onclick: () => indir("/api/excel/cek-sablon", "cek-sablonu.xlsx") }, "Şablonu indir"),
          h("button", { type: "button", class: "dugme", onclick: () => { satirlar.push(yeniSatir()); sakla(); ciz(); govde.lastChild?.querySelector("input[data-alan=cek_no]")?.focus(); } }, "+ Satır ekle")),
        topluAkibet,
        h("p", { class: "ipucu" }, "Excel'deki çek satırlarını kopyalayıp tablodaki ilk hücreye yapıştırabilirsiniz. Birden çok fotoğraf ya da tek sayfada birkaç çek seçilebilir. Kaydedilene kadar satırlar burada bekler."),
        h("div", { class: "tablo-kap" }, h("table", { class: "liste toplu-cek" },
          h("thead", {}, h("tr", {}, h("th", {}, ""), h("th", {}, "#"), ...TOPLU_CEK_ALANLARI.map(([, b]) => h("th", {}, b)),
            h("th", { title: yon === "alinan" ? "Çek ne oldu: portföyde mi, kime ciro edildi, hangi bankaya takasa/teminata verildi, tahsil edildi mi" : "Çek ödendi mi: hangi bankadan ya da kasadan" }, yon === "alinan" ? "Akıbet (ciro / takas / tahsil)" : "Durum (ödendi mi)"),
            h("th", {}, "Durum"), h("th", {}, ""))),
          govde)),
        h("datalist", { id: "toplu-cek-bankalar" }, BANKA_ADLARI.map((b) => h("option", { value: b }))),
        h("datalist", { id: "toplu-cek-santiyeler" }, santiyeler.map((x) => h("option", { value: x.ad }))),
        h("div", { class: "dugmeler" },
          h("button", { type: "button", class: "dugme ana", onclick: () => this.kaydet() }, "Tümünü kaydet (F2)"),
          h("button", { type: "button", class: "dugme", onclick: () => this.kaydet(true) }, "Seçilenleri kaydet"),
          h("button", { type: "button", class: "dugme", title: "Seçili satırlardaki bütün kırmızı alanları doğru say", onclick: () => {
            const sec = satirlar.filter((x) => x._sec);
            if (!sec.length) return bildir("Önce satır başındaki kutucuklardan çek seçin.", true);
            sec.forEach(satiriOnayla); sakla(); ciz();
            bildir(`${sec.length} satırdaki kırmızı alanlar onaylandı.`);
          } }, "✓ Seçilenlerin kırmızılarını onayla"),
          h("button", { type: "button", class: "dugme tehlike", onclick: () => { satirlar = satirlar.filter((x) => !x._sec); sakla(); ciz(); } }, "Seçilenleri tablodan çıkar"),
          ozet)));
      this.satirlariCiz = ciz;
    },
    async kaydet(yalnizSecili = false) {
      const { cariler, santiyeler } = secenekler;
      const gidecek = satirlar.filter((x) => TOPLU_CEK_ALANLARI.some(([a]) => !["tur", "para_birimi", "alis_tarihi"].includes(a) && x[a] != null && x[a] !== "")
        && (!yalnizSecili || x._sec));
      if (!gidecek.length) return bildir(yalnizSecili ? "Kaydedilecek satır seçin." : "Tabloda kaydedilecek çek yok.", true);
      const onaysiz = gidecek.filter((x) => x.belirsiz?.length);
      if (onaysiz.length && !confirm(`${onaysiz.length} çekte onaylanmamış kırmızı alan var (${onaysiz.map((x) => x.cek_no || "?").slice(0, 6).join(", ")}${onaysiz.length > 6 ? "…" : ""}).\n\nKırmızı alanları çekle karşılaştırıp ✓ ile onaylamanız önerilir. Yine de kaydedilsin mi?`)) return;
      // Cari sütunu yok: sunucu alınan çekte çeki yazan firmayı, verilen çekte lehtarı cari yapar. Excel şablonunda
      // Cari yazılmış ve listede olmayan adlar için benzer cari varsa sorulur
      const bilinmeyen = [...new Map(gidecek.filter((x) => !x.cari_id && x.cari_unvan).map((x) => [aramaAnahtari(x.cari_unvan), x])).values()];
      for (const x of bilinmeyen) {
        const b = await benzerCariKontrol(x.cari_unvan, x.cari_vkn);
        if (!b) return;
        if (b !== "yeni") for (const y of gidecek) if (aramaAnahtari(y.cari_unvan) === aramaAnahtari(x.cari_unvan)) { y.cari_id = b.id; y.cari_unvan = b.unvan; }
      }
      // Listede olmayan şantiye adları kayıttan önce açılır (aynı ad varsa sunucu var olanı verir)
      for (const x of gidecek.filter((x) => !x.santiye_id && x.santiye_ad)) {
        try {
          const st = await api("/api/santiyeler", { metod: "POST", veri: { ad: x.santiye_ad } });
          if (!santiyeler.some((y) => y.id === st.id)) santiyeler.push(st);
          x.santiye_id = st.id; x.santiye_ad = st.ad;
        } catch (e) { return bildir(e.message, true); }
      }
      listeyiTazele("santiyeler");
      const govdeyeCevir = (x) => {
        const st = (x.santiye_id && { id: x.santiye_id }) || (x.santiye_ad && santiyeler.find((st) => aramaAnahtari(st.ad) === aramaAnahtari(x.santiye_ad)));
        return { yon, tur: x.tur || "cek", cek_no: x.cek_no || null, banka: x.banka || null, sube: x.sube || null, hesap_no: x.hesap_no || null,
          kesideci: x.kesideci || null, kesideci_vkn: x.kesideci_vkn || null, lehtar: x.lehtar || null, tutar: sayiCoz(x.tutar), para_birimi: x.para_birimi || "TRY", vade: tarihCoz(x.vade),
          alis_tarihi: tarihCoz(x.alis_tarihi), cari_id: x.cari_id || null, cari_unvan: x.cari_id ? null : x.cari_unvan || null,
          cari_vkn: x.cari_vkn || null, santiye_id: st ? st.id : null, aciklama: [x.aciklama, x.santiye_ad && !st ? `Şantiye: ${x.santiye_ad}` : null].filter(Boolean).join(" · ") || null,
          kaynak_dosya: x.kaynak_dosya || null, akibet: akibetVerisi(x.akibet, akibetTarihi(x)) };
      };
      // Ödendi / tahsil edildi: vade geçmişse vade günü, değilse bugün; ciro, takas, teminat: alış tarihi
      const akibetTarihi = (x) => {
        const bugunT = bugun(), vade = tarihCoz(x.vade);
        if (/^(tahsil|ode)/.test(x.akibet?.islem || "")) return vade && vade < bugunT ? vade : bugunT;
        return tarihCoz(x.alis_tarihi) || bugunT;
      };
      try {
        const r = await api("/api/cekler/toplu", { metod: "POST", veri: { satirlar: gidecek.map(govdeyeCevir) } });
        r.sonuc.forEach((s, i) => { gidecek[i].sorun = s.ok ? null : s.hata; gidecek[i]._kaydedildi = s.ok; });
        satirlar = satirlar.filter((x) => !x._kaydedildi);
        if (!satirlar.length) satirlar.push(yeniSatir());
        sakla();
        this.satirlariCiz?.();
        const hatali = r.sonuc.length - r.kaydedilen;
        bildir(`${r.kaydedilen} çek kaydedildi` + (r.yeni_cari ? `, ${r.yeni_cari} yeni cari açıldı` : "") + (hatali ? `. ${hatali} satır kaydedilemedi, nedeni satırda kırmızı yazıyor.` : "."), hatali > 0);
        cekEkranlariniTazele();
      } catch (e) { bildir(e.message, true); }
    },
  });
  return s;
}

async function belgeAc(yol) {
  try {
    const blob = await api(yol);
    window.open(URL.createObjectURL(blob), "_blank");
  } catch (e) { bildir(e.message, true); }
}

// ---------------------------------------------------------------- banka hesapları
function bankaHesaplariAc() {
  sekmeAc("banka-hesaplari", "Banka Hesapları", listeEkrani({
    baslik: "Banka Hesapları ve Kredi Kartları",
    kaynak: () => api("/api/banka-hesaplari"),
    kolonlar: [{ alan: "ad", baslik: "Hesap" }, { alan: "tur", baslik: "Tür", deger: (b) => (b.tur === "kredi_karti" ? "Kredi kartı" : "Banka") },
      { alan: "banka", baslik: "Banka" }, { alan: "sube", baslik: "Şube" },
      { alan: "iban", baslik: "IBAN / Kart No", deger: (b) => (b.tur === "kredi_karti" ? b.kart_no : b.iban) || "" }, { alan: "para_birimi", baslik: "Para Birimi" }, { alan: "bakiye", baslik: "Bakiye", tip: "para" },
      { alan: "hareket_sayisi", baslik: "Hareket", deger: (b) => b.hareket_sayisi + (b.onay_bekleyen ? ` (${b.onay_bekleyen} onay bekliyor)` : "") },
      { alan: "ekstre_bakiye", baslik: "Ekstre Bakiyesi", tip: "para" }, { alan: "ekstre_tarihi", baslik: "Ekstre Tarihi", tip: "tarih" },
      { alan: "son_odeme_tarihi", baslik: "Kart Son Ödeme", tip: "tarih" },
      { alan: "mutabakat_farki", baslik: "Mutabakat", metin: (b) => mutabakatYazi(b),
        deger: (b) => h("span", { class: b.mutabakat_farki ? "negatif" : "", title: b.mutabakat_farki ? "Onay bekleyen ya da eksik hareket var" : "" }, mutabakatYazi(b)) }],
    toplamlar: ["bakiye"],
    ustAlan: () => h("span", { class: "ipucu" }, "Hareketleri görmek için hesaba çift tıklayın. Kredi kartında eksi bakiye kart borcudur."),
    yeni: () => bankaHesapFormAc(),
    ac: (b) => hareketListesiAc(b),
    silSorarak: (b) => bankaHesaplariniSil([b]),
    toplu: [{ ad: "Hareketlerini aç", islem: (sec) => { sec.forEach((b) => hareketListesiAc(b)); return false; } },
      { ad: "Seçilenleri sil", tehlikeli: true, islem: (sec) => bankaHesaplariniSil(sec) }],
  }));
}

// Hareketsiz hesap sorulup silinir; hareketli hesap için ne gideceği gösterilir, SİL yazılırsa yedek alınıp
// hesap hareketleriyle birlikte silinir.
async function bankaHesaplariniSil(sec) {
  const bos = sec.filter((b) => !b.hareket_sayisi);
  const dolu = sec.filter((b) => b.hareket_sayisi);
  let silinen = 0;
  const kalan = [];
  if (bos.length && confirm(`Hareketi olmayan ${bos.length} hesap (${bos.map((b) => b.ad).join(", ")}) silinsin mi?`)) {
    for (const b of bos) {
      try { await api(`/api/banka-hesaplari/${b.id}`, { metod: "DELETE" }); silinen++; } catch (e) { kalan.push(`${b.ad}: ${e.message}`); }
    }
  }
  for (const b of dolu) {
    const o = await api(`/api/banka-hesaplari/${b.id}/silme-ozeti`);
    const cevap = prompt(`${b.ad} hesabında ${o.hareket} hareket var` + (o.onay_bekleyen ? ` (${o.onay_bekleyen} tanesi onay bekliyor)` : "") + ".\n\n"
      + `Hareketleri tek tek görüp silmek için hesaba çift tıklayın. Hesabı HAREKETLERİYLE BİRLİKTE silerseniz:\n`
      + `• ${o.hareket} hareket silinir` + (o.giris || o.cikis ? ` (onaylı girişler ${para(o.giris)} TL, çıkışlar ${para(o.cikis)} TL)` : "") + "\n"
      + (o.cari ? `• ${o.cari} carinin bakiyesi değişir\n` : "")
      + "• Virman ve nakit çekimlerin karşı hesaptaki / kasadaki kaydı da silinir\n"
      + "• Silmeden önce otomatik yedek alınır\n\nOnaylamak için SİL yazın:");
    if (cevap == null) continue;
    if (cevap.trim().toLocaleUpperCase("tr") !== "SİL") { kalan.push(`${b.ad}: onay için SİL yazılmadı`); continue; }
    try {
      const r = await api(`/api/banka-hesaplari/${b.id}?hareketlerle=true`, { metod: "DELETE" });
      silinen++;
      bildir(`${b.ad} ve ${r.silinen_hareket} hareketi silindi (öncesinde yedek alındı).`);
    } catch (e) { kalan.push(`${b.ad}: ${e.message}`); }
  }
  if (silinen) bildir(`${silinen} hesap silindi.`);
  if (kalan.length) alert(`Silinmeyenler:\n\n${kalan.join("\n")}`);
  if (!silinen && !kalan.length) return false;
  for (const l of ["kasa", "cariler"]) listeyiTazele(l);
}

const mutabakatYazi = (b) => (b.mutabakat_farki == null ? "" : b.mutabakat_farki ? `Fark ${para(b.mutabakat_farki)}` : "Tutuyor ✓");

function bankaHesapFormAc(b = null) {
  const s = sekmeAc(b ? `banka-${b.id}` : `banka-yeni-${Date.now()}`, b ? b.ad : "Yeni Banka Hesabı / Kart", {
    ciz(el) {
      const form = h("form", { class: "form-pencere", onsubmit: (e) => { e.preventDefault(); this.kaydet(); } },
        h("h2", {}, "Banka Hesabı / Kredi Kartı"),
        h("fieldset", {}, h("legend", {}, "Bilgiler"), h("div", { class: "alanlar" },
          alan("Hesap adı", "ad", b?.ad, { zorunlu: true }),
          alan("Tür", "tur", b?.tur || "banka", { secenekler: [["banka", "Banka hesabı"], ["kredi_karti", "Kredi kartı"]] }),
          alan("Banka", "banka", b?.banka), alan("Şube", "sube", b?.sube),
          alan("IBAN", "iban", b?.iban), alan("Kart No (son 4 hane yeter)", "kart_no", b?.kart_no),
          alan("Para Birimi", "para_birimi", b?.para_birimi || "TRY"),
          alan("Açılış bakiyesi (kart borcu eksi yazılır)", "acilis_bakiyesi", b?.acilis_bakiyesi ?? 0, { tip: "number" }))),
        h("div", { class: "dugmeler" }, h("button", { class: "dugme ana" }, "Kaydet (F2)")));
      el.append(form);
      this.form = form;
    },
    async kaydet() {
      if (!this.form.reportValidity()) return;
      const v = formVerisi(this.form, ["acilis_bakiyesi"]);
      v.acilis_bakiyesi = v.acilis_bakiyesi || 0;
      v.para_birimi = v.para_birimi || "TRY";
      try {
        if (b) await api(`/api/banka-hesaplari/${b.id}`, { metod: "PUT", veri: v });
        else await api("/api/banka-hesaplari", { metod: "POST", veri: v });
        bildir("Banka hesabı kaydedildi.");
        sekmeKapat(s);
        listeyiTazele("banka-hesaplari");
      } catch (e) { bildir(e.message, true); }
    },
  });
}

// ---------------------------------------------------------------- hareketler
function hareketListesiAc(hesap = null) {
  sekmeAc(hesap ? `hareketler-${hesap.id}` : "hareketler", hesap ? `Hareketler: ${hesap.ad}` : "Tahsilat / Ödeme", listeEkrani({
    baslik: hesap ? `${hesap.tur === "kredi_karti" ? "Kart" : "Banka"} Hareketleri: ${hesap.ad}` : "Tahsilat / Ödeme Hareketleri",
    // Hesabın tüm hareketleri: ekstreden gelip onay bekleyenler de (bakiyeye yalnız onaylılar girer)
    kaynak: async () => {
      if (!hesap) return api("/api/hareketler?durum=onayli");
      // Açılış bakiyesi ekstre yüklenince/silinince değişir: liste açıldığındaki değil güncel olanı kullanılır
      const [liste, hesaplar] = await Promise.all([api(`/api/hareketler?banka_hesap_id=${hesap.id}`), api("/api/banka-hesaplari")]);
      let bakiye = Number((hesaplar.find((b) => b.id === hesap.id) || hesap).acilis_bakiyesi || 0);
      for (const x of [...liste].reverse()) {
        if (x.durum === "onayli") bakiye += x.yon === "giris" ? x.tutar : -x.tutar;
        x.bakiye = x.durum === "onayli" ? Math.round(bakiye * 100) / 100 : null;
      }
      return liste;
    },
    ustAlan: hesap ? () => h("span", {}, h("button", { class: "dugme", onclick: () => bankaHesapFormAc(hesap) }, "Hesap kartı"), " ",
      h("button", { class: "dugme", onclick: () => ekstreYukleAc(hesap.id) }, "Ekstre yükle")) : null,
    kolonlar: [
      { alan: "tarih", baslik: "Tarih", tip: "tarih" }, { alan: "tur", baslik: "Tür", deger: (x) => HAREKET_TURLERI[x.tur] || x.tur },
      { alan: "giris", baslik: "Giriş", tip: "para", deger: (x) => (x.yon === "giris" ? x.tutar : null) },
      { alan: "cikis", baslik: "Çıkış", tip: "para", deger: (x) => (x.yon === "cikis" ? x.tutar : null) },
      { alan: "cari_unvan", baslik: "Cari" }, { alan: "banka_hesap_ad", baslik: "Banka / Kasa", deger: (x) => x.banka_hesap_ad || (x.cek_id ? "Çek portföyü" : "Kasa") },
      { alan: "santiye_ad", baslik: "Şantiye" }, { alan: "aciklama", baslik: "Açıklama" },
      ...(hesap ? [{ alan: "bakiye", baslik: "Bakiye", tip: "para" },
        { alan: "durum", baslik: "Durum", deger: (x) => (x.durum === "onayli" ? "Onaylı" : h("span", { class: "negatif" }, x.durum === "iptal" ? "İptal" : "Onay bekliyor")),
          metin: (x) => (x.durum === "onayli" ? "Onaylı" : x.durum === "iptal" ? "İptal" : "Onay bekliyor") }] : []),
    ],
    yeni: () => hareketFormAc(null, hesap?.id),
    ac: (x) => (x.cek_id ? bildir("Çek hareketleri çek kartından yönetilir.") : hareketFormAc(x)),
    sil: (x) => api(`/api/hareketler/${x.id}`, { metod: "DELETE" }),
    toplu: [{ ad: "Seçilenleri sil", tehlikeli: true, islem: hareketleriSil }],
    excel: "/api/excel/hareketler",
  }));
}

function hareketFormAc(hr = null, bankaId = null, varsayilan = {}) {
  const s = sekmeAc(hr ? `hareket-${hr.id}` : `hareket-yeni-${Date.now()}`, hr ? "Hareket" : bankaId ? "Yeni Tahsilat / Ödeme" : "Kasa Hareketi", {
    async ciz(el) {
      const { cariler, santiyeler, hesaplar } = await tumSecenekler();
      const x = hr || { tarih: new Date().toISOString().slice(0, 10), yon: "giris", tur: "tahsilat", banka_hesap_id: bankaId, ...varsayilan };
      const form = h("form", { class: "form-pencere", onsubmit: (e) => { e.preventDefault(); this.kaydet(); } },
        h("h2", {}, "Tahsilat / Ödeme"),
        h("fieldset", {}, h("legend", {}, "Hareket"), h("div", { class: "alanlar" },
          alan("Tarih", "tarih", x.tarih, { tip: "date", zorunlu: true }),
          alan("Yön", "yon", x.yon, { secenekler: [["giris", "Giriş (para geldi)"], ["cikis", "Çıkış (para gitti)"]] }),
          alan("Tür", "tur", x.tur, { secenekler: Object.entries(HAREKET_TURLERI).filter(([k]) => !k.startsWith("cek_")) }),
          alan("Tutar", "tutar", x.tutar, { tip: "number", zorunlu: true }),
          alan("Cari", "cari_id", x.cari_id, { secenekler: secenekListesi(cariler, "unvan", "— Cari yok —") }),
          alan("Banka / Kasa", "banka_hesap_id", x.banka_hesap_id, { secenekler: secenekListesi(hesaplar, "ad", "Kasa (nakit)") }),
          santiyeAlani("Şantiye", x.santiye_id, santiyeler),
          alan("Gider Türü", "gider_turu", x.gider_turu, { secenekler: [["", "—"], ...BEN.gider_turleri.map((g) => [g, g])] }),
          alan("Açıklama", "aciklama", x.aciklama, { genis: true }))),
        x.durum === "iptal" ? h("div", { class: "uyari-satiri hata" }, `İptal edildi: ${x.iptal_nedeni || ""}. Bakiyede yer almaz; değiştirmek için önce iptali geri alın.`) : "",
        h("div", { class: "dugmeler" }, h("button", { class: "dugme ana", disabled: x.durum === "iptal" }, "Kaydet (F2)"),
          ...(hr ? kayitDugmeleri("hareket", x, "Hareket", async () => hareketFormAc(await api(`/api/hareketler/${hr.id}`))) : [])));
      el.append(form);
      this.form = form;
    },
    async kaydet() {
      if (!this.form.reportValidity()) return;
      const v = formVerisi(this.form, ["tutar", "cari_id", "banka_hesap_id", "santiye_id"]);
      try {
        if (hr) await api(`/api/hareketler/${hr.id}`, { metod: "PUT", veri: v });
        else await api("/api/hareketler", { metod: "POST", veri: v });
        bildir("Hareket kaydedildi.");
        sekmeKapat(s);
        listeyiTazele("kasa");
      } catch (e) { bildir(e.message, true); }
    },
  });
}

// ---------------------------------------------------------------- nakit kasa
function kasaAc() {
  let bakiye = 0;
  sekmeAc("kasa", "Nakit Kasa", listeEkrani({
    baslik: "Nakit Kasa",
    kaynak: async () => {
      const r = await api("/api/kasa");
      bakiye = r.bakiye;
      const b = $("#kasa-bakiye");
      if (b) { b.textContent = `Kasa bakiyesi: ${para(bakiye)}`; b.className = bakiye < 0 ? "negatif" : ""; }
      return r.hareketler;
    },
    ustAlan: () => h("span", { style: "display:flex;gap:6px;align-items:center" },
      h("b", { id: "kasa-bakiye" }, ""),
      h("button", { class: "dugme ana", onclick: () => hareketFormAc(null, null, { yon: "cikis", tur: "odeme" }) }, "Kasadan ödeme"),
      h("button", { class: "dugme", onclick: () => hareketFormAc(null, null, { yon: "giris", tur: "tahsilat" }) }, "Kasaya giriş")),
    kolonlar: [
      { alan: "tarih", baslik: "Tarih", tip: "tarih" }, { alan: "tur", baslik: "Tür", deger: (x) => HAREKET_TURLERI[x.tur] || x.tur },
      { alan: "giris", baslik: "Giriş", tip: "para", deger: (x) => (x.yon === "giris" ? x.tutar : null) },
      { alan: "cikis", baslik: "Çıkış", tip: "para", deger: (x) => (x.yon === "cikis" ? x.tutar : null) },
      { alan: "cari_unvan", baslik: "Cari" }, { alan: "aciklama", baslik: "Açıklama" },
    ],
    yeni: () => hareketFormAc(null, null, { yon: "cikis", tur: "odeme" }),
    ac: (x) => (x.kaynak === "esleme" ? bildir("Bu satır bankadaki nakit çekimden gelir; bankadaki hareketi değiştirin.") : hareketFormAc(x)),
    sil: (x) => api(`/api/hareketler/${x.id}`, { metod: "DELETE" }),
    toplu: [{ ad: "Seçilenleri sil", tehlikeli: true, islem: hareketleriSil }],
  }));
}

// ---------------------------------------------------------------- banka ekstresi
function ekstreYukleAc(hesapId = null) {
  sekmeAc("ekstre-yukle", "Ekstre Yükle", {
    async ciz(el) {
      const hesaplar = await api("/api/banka-hesaplari").catch(() => []);
      // "kart": kredi kartı ekstresi; kart, ekstredeki kart numarasından bulunur, yoksa açılır.
      const hesapS = h("select", {}, [...hesaplar.map((b) => h("option", { value: b.id, selected: b.id === hesapId },
        `${b.ad}${b.tur === "kredi_karti" ? (b.kart_no ? " · " + b.kart_no : " · kredi kartı") : b.iban ? " · " + b.iban : ""}`)),
        h("option", { value: "kart", selected: hesapId === "kart" || !hesaplar.length }, "Kredi kartı (kart ekstreden bulunur)")]);
      const sonuc = h("div", { class: "yukleme-listesi" });
      const girdi = h("input", { type: "file", multiple: true, accept: ".xlsx,.csv,application/pdf,image/jpeg,image/png,image/webp", hidden: true,
        onchange: (e) => { yukle([...e.target.files]); e.target.value = ""; } });
      const alanEl = h("div", { class: "birak-alani", onclick: () => girdi.click(),
        ondragover: (e) => { e.preventDefault(); alanEl.classList.add("uzerinde"); }, ondragleave: () => alanEl.classList.remove("uzerinde"),
        ondrop: (e) => { e.preventDefault(); alanEl.classList.remove("uzerinde"); yukle([...e.dataTransfer.files]); } },
        h("b", {}, "Banka ya da kredi kartı ekstresini buraya sürükleyin"), `Excel (.xlsx), CSV, PDF${BEN.ai_var ? " veya ekran görüntüsü" : ""}. Aynı satırlar ikinci kez eklenmez. Eski .xls dosyasını Excel'de açıp .xlsx olarak kaydedin.`);
      async function yukle(dosyalar) {
        for (const d of dosyalar) {
          const satir = h("div", {}, h("span", {}, d.name), h("span", { class: "durum" }, okunuyorYazisi()));
          sonuc.prepend(satir);
          const fd = new FormData(); fd.append("dosya", d);
          try {
            const r = await api(hesapS.value === "kart" ? "/api/kredi-karti-ekstresi"
              : `/api/banka-hesaplari/${hesapS.value}/ekstre?yontem=${OKUMA_YONTEMI}`, { metod: "POST", dosya: fd });
            satir.lastChild.textContent = `${r.hesap}: ${r.eklenen} yeni satır${r.atlanan ? ` · ${r.atlanan_nedeni || `${r.atlanan} atlandı`}` : ""}${r.eslesen ? `, ${r.eslesen} transfer diğer hesaptaki kayıtla eşleşti` : ""}${r.yeni_cari ? `, ${r.yeni_cari} yeni cari açıldı` : ""}${r.notlar ? " · " + r.notlar : ""}`;
            if (r.islenemeyen?.length) satir.append(h("div", { class: "hata-kutu" }, `${r.islenemeyen.length} satır işlenemedi:`, h("ul", {}, r.islenemeyen.map((x) => h("li", {}, x)))));
            if (r.eklenen) satir.append(h("button", { class: "dugme ana", onclick: taslakHareketlerAc }, "Kontrol et ve onayla"));
          } catch (e) { satir.lastChild.textContent = "Hata: " + e.message; }
        }
      }
      el.append(h("div", { class: "form-pencere" }, h("h2", {}, "Banka / Kredi Kartı Ekstresi Yükle"),
        h("p", { style: "margin:0 0 8px" }, "Program her satırı okur, açıklamadaki VKN, IBAN veya ünvandan cariyi bulur ve türünü önerir. Kart ekstresinde her harcama işyerinin carisine işlenir. Siz onaylayınca cari ve banka bakiyelerine işlenir."),
        h("div", { class: "liste-ust" }, "Hesap:", hesapS, yontemSecimi()), alanEl, girdi, sonuc));
    },
  });
}

function taslakHareketlerAc() {
  const secili = new Set();
  let yalnizSorunlu = false, hesapSuzgeci = "";
  sekmeAc("taslak-hareketler", "Onay Bekleyen Hareketler", {
    async ciz(el) {
      let liste, sec;
      try { [liste, sec] = await Promise.all([api("/api/hareketler?durum=taslak"), tumSecenekler()]); } catch (e) { return bildir(e.message, true); }
      const sorunlu = liste.filter((x) => x.sorun).length;
      // Hesaba göre süzülür: yanlış hesaba yüklenen ekstre satırları tek seferde seçilip silinebilsin
      const hesapAdlari = [...new Set(liste.map((x) => x.banka_hesap_ad || "Kasa"))];
      if (!hesapAdlari.includes(hesapSuzgeci)) hesapSuzgeci = "";
      if (yalnizSorunlu) liste = liste.filter((x) => x.sorun);
      if (hesapSuzgeci) liste = liste.filter((x) => (x.banka_hesap_ad || "Kasa") === hesapSuzgeci);
      for (const id of [...secili]) if (!liste.some((x) => x.id === id)) secili.delete(id);
      const secim = (dizi, deger, onchange) => h("select", { onchange }, dizi.map(([d, m]) => h("option", { value: d, selected: String(d) === String(deger ?? "") }, m)));
      const kaydetSatir = async (x, alanAd, deger) => {
        const v = { tarih: x.tarih, yon: x.yon, tur: x.tur, tutar: x.tutar, cari_id: x.cari_id, banka_hesap_id: x.banka_hesap_id,
          santiye_id: x.santiye_id, gider_turu: x.gider_turu, aciklama: x.aciklama, [alanAd]: deger };
        try { Object.assign(x, await api(`/api/hareketler/${x.id}`, { metod: "PUT", veri: v })); durum("Satır güncellendi"); yenidenCiz(); }
        catch (e) { bildir(e.message, true); }
      };
      // Açıklamadaki karşı taraf adı: giden "açıklama, ALICI, banka, IBAN"; gelen "GÖNDEREN, ...".
      const adTahmini = (x) => {
        const p = (x.aciklama || "").split(",").map((t) => t.trim());
        return (p.length > 1 ? (x.yon === "cikis" ? p[1] : p[0].split(/'\s*DAN|\//i)[0]) : p[0]).toLocaleUpperCase("tr");
      };
      const yeniCari = async (x, secimEl) => {
        const unvan = prompt("Yeni carinin ünvanı:", adTahmini(x));
        if (!unvan?.trim()) { secimEl.value = x.cari_id ?? ""; return; }
        try {
          const c = await api("/api/cariler", { metod: "POST", veri: { unvan: unvan.trim(), tur: x.yon === "giris" ? "musteri" : "tedarikci" } });
          bildir(`'${c.unvan}' carisi açıldı.`);
          await kaydetSatir(x, "cari_id", c.id);
        } catch (err) { bildir(err.message, true); }
      };
      const turler = Object.entries(HAREKET_TURLERI).filter(([k]) => !k.startsWith("cek_c") && k !== "cek_karsiliksiz");
      const topluCariS = h("select", {}, secenekListesi(sec.cariler, "unvan", "— Cari seçin —").map(([d, m]) => h("option", { value: d }, m)));
      const topluTurS = h("select", {}, [["", "— Tür seçin —"], ...turler].map(([d, m]) => h("option", { value: d }, m)));
      const topluAta = async (veri) => {
        if (!secili.size) return bildir("Önce satır seçin.");
        try {
          const r = await api("/api/hareketler/toplu-guncelle", { metod: "POST", veri: { idler: [...secili], ...veri } });
          bildir(`${r.guncellenen} satır güncellendi.`);
          yenidenCiz();
        } catch (e) { bildir(e.message, true); }
      };
      const tumu = h("input", { type: "checkbox", onchange: (e) => { liste.forEach((x) => (e.target.checked ? secili.add(x.id) : secili.delete(x.id))); yenidenCiz(); } });
      tumu.checked = liste.length > 0 && secili.size === liste.length;
      const govde = h("tbody", {}, liste.map((x) => h("tr", { class: x.sorun ? "islenemedi" : "", title: x.sorun || "" },
        h("td", {}, h("input", { type: "checkbox", checked: secili.has(x.id), onchange: (e) => (e.target.checked ? secili.add(x.id) : secili.delete(x.id)) })),
        h("td", {}, tarih(x.tarih)), h("td", { style: "white-space:normal;min-width:220px" }, x.aciklama || ""),
        h("td", { class: "sayi" }, x.yon === "giris" ? para(x.tutar) : ""), h("td", { class: "sayi" }, x.yon === "cikis" ? para(x.tutar) : ""),
        h("td", {}, secim([...secenekListesi(sec.cariler, "unvan", "— Cari yok —"), ["__yeni", "+ Yeni cari oluştur…"]], x.cari_id,
          async (e) => (e.target.value === "__yeni" ? yeniCari(x, e.target) : kaydetSatir(x, "cari_id", Number(e.target.value) || null)))),
        h("td", {}, secim(turler, x.tur, (e) => kaydetSatir(x, "tur", e.target.value))),
        h("td", {}, x.banka_hesap_ad || ""), h("td", { style: "white-space:normal" }, x.sorun || ""))));
      const toplu = async (islem) => {
        if (!secili.size) return bildir("Önce satır seçin.");
        try {
          if (islem === "onayla") { const r = await api("/api/hareketler/onayla", { metod: "POST", veri: { idler: [...secili] } }); bildir(`${r.onaylanan} hareket onaylandı.`); }
          else {
            if (!confirm(`${secili.size} satır silinsin mi?` + (secili.size > 1 ? "\n\nSilmeden önce otomatik yedek alınır." : ""))) return;
            const r = await api("/api/hareketler/toplu-sil", { metod: "POST", veri: { idler: [...secili] } });
            bildir(`${r.silinen} satır silindi.` + (r.silinmeyen.length ? ` ${r.silinmeyen.length} satır silinmedi: ${r.silinmeyen[0]}` : ""), r.silinmeyen.length > 0);
          }
          secili.clear();
          yenidenCiz();
        } catch (e) { bildir(e.message, true); }
      };
      el.append(h("div", { class: "liste-ust" }, h("h2", {}, "Onay Bekleyen Banka ve Kart Hareketleri"),
          h("button", { class: "dugme ana", onclick: () => toplu("onayla") }, "Seçilenleri onayla"),
          h("button", { class: "dugme tehlike", onclick: () => toplu("sil") }, "Seçilenleri sil"),
          h("label", {}, h("input", { type: "checkbox", checked: yalnizSorunlu, onchange: (e) => { yalnizSorunlu = e.target.checked; yenidenCiz(); } }), " Yalnız işlenemeyenler"),
          hesapAdlari.length > 1 ? h("label", {}, "Hesap: ", h("select", { onchange: (e) => { hesapSuzgeci = e.target.value; secili.clear(); yenidenCiz(); } },
            [["", "Tümü"], ...hesapAdlari.map((a) => [a, a])].map(([d, m]) => h("option", { value: d, selected: d === hesapSuzgeci }, m)))) : null,
          h("span", {}, "Cari, açıklamadaki ünvan, VKN veya IBAN'dan bulunur; yoksa yeni açılır. Banka kesintileri MUHTELİF BANKA İŞLEMLERİ carisine, nakit çekimler kasaya, hesaplar arası transferler ve kart borcu ödemeleri karşı hesaba işlenir. Kart harcamasında seçtiğiniz cari sonraki ekstrelerde hatırlanır.")),
        sorunlu ? h("div", { class: "hata-kutu" }, `${sorunlu} satır işlenemedi (kırmızı). Nedeni son sütunda yazıyor; cari ya da tür seçerek düzeltin.`) : null,
        h("div", { class: "liste-ust" }, "Seçilenlere:", topluCariS, topluTurS,
          h("button", { class: "dugme", onclick: () => {
            const v = { cari_id: Number(topluCariS.value) || null, tur: topluTurS.value || null };
            return v.cari_id || v.tur ? topluAta(v) : bildir("Cari ya da tür seçin.", true);
          } }, "Ata"),
          h("button", { class: "dugme", onclick: () => topluAta({ muhtelif: true }) }, "MUHTELİF BANKA İŞLEMLERİ'ne ata")),
        liste.length ? h("div", { class: "tablo-kap" }, h("table", { class: "liste kalemler-secim" },
          h("thead", {}, h("tr", {}, h("th", {}, tumu), ["Tarih", "Açıklama", "Giriş", "Çıkış", "Cari", "Tür", "Hesap", "İşlenemedi çünkü"].map((b) => h("th", {}, b)))),
          govde)) : h("p", {}, "Onay bekleyen hareket yok."));
      durum(`${liste.length} hareket onay bekliyor`);
    },
    yenile: () => yenidenCiz(),
  });
}

// ---------------------------------------------------------------- yazdırma
/** Sunucunun hazırladığı yazdırma sayfasını yeni pencerede açar (pencere açılır açılmaz yazdırma penceresi gelir). */
async function yazdirAc(yol) {
  const pencere = window.open("", "_blank"); // açılır pencere engeline takılmamak için tıklama anında açılır
  try {
    const blob = await api(yol);
    const url = URL.createObjectURL(new Blob([blob], { type: "text/html" }));
    if (pencere) pencere.location = url; else window.open(url, "_blank");
  } catch (e) { pencere?.close(); bildir(e.message, true); }
}

// ---------------------------------------------------------------- mali raporlar
/** Basit rapor tablosu: kolonlar [alan, başlık, tip], toplam alınacak alanlar, çift tıklama. */
function raporTablosu(kolonlar, satirlar, { toplam = [], ac, sinif } = {}) {
  const hucre = ([a, , tip], s) => {
    const v = typeof a === "function" ? a(s) : s[a];
    if (tip === "para") return h("td", { class: "sayi" + (v < 0 ? " negatif" : "") }, v ? para(v) : "");
    if (tip === "tarih") return h("td", {}, tarih(v));
    return h("td", {}, v ?? "");
  };
  return h("div", { class: "tablo-kap" }, h("table", { class: "liste" },
    h("thead", {}, h("tr", {}, kolonlar.map(([, b, tip]) => h("th", { class: tip === "para" ? "sayi" : "" }, b)))),
    h("tbody", {}, satirlar.map((s) => h("tr", { class: sinif?.(s) || "", ondblclick: ac ? () => ac(s) : null }, kolonlar.map((k) => hucre(k, s))))),
    toplam.length ? h("tfoot", {}, h("tr", {}, kolonlar.map(([a], i) => toplam.includes(a)
      ? h("td", { class: "sayi" }, para(satirlar.reduce((t, s) => t + (s[a] || 0), 0)))
      : h("td", {}, i === 0 ? "Toplam" : ""))))
      : null));
}
const yilSecimi = (f) => h("label", {}, "Yıl: ", h("input", { type: "number", value: f.yil, style: "width:80px",
  onchange: (e) => { f.yil = Number(e.target.value) || f.yil; yenidenCiz(); } }));
const ACIKLAMA = (metin) => h("p", { style: "color:#4a5866;max-width:900px" }, metin);
// Mali raporlar resmi beyan değildir: ekranda ve yazdırılınca en üstte görünür.
const MALI_UYARI = (ek) => h("div", { class: "mali-uyari" }, "Mali müşavirle karşılaştırma amaçlıdır; resmi beyan yerine geçmez.", ek ? h("br") : null, ek || null);

function kdvOzetiAc() {
  const f = { yil: new Date().getFullYear(), devreden: 0 };
  const q = () => `yil=${f.yil}&devreden=${f.devreden || 0}`;
  sekmeAc("rapor-kdv", "KDV Özeti", {
    async ciz(el) {
      let v;
      try { v = await api(`/api/raporlar/kdv?${q()}`); } catch (e) { return bildir(e.message, true); }
      el.append(MALI_UYARI(), h("div", { class: "liste-ust" }, h("h2", {}, `KDV Özeti ${f.yil}`), yilSecimi(f),
          h("label", {}, "Geçen yıldan devreden KDV: ", h("input", { type: "number", step: "any", value: f.devreden, style: "width:110px",
            onchange: (e) => { f.devreden = Number(e.target.value) || 0; yenidenCiz(); } })),
          h("button", { class: "dugme ana", onclick: () => this.excel() }, "Excel'e aktar (F9)")),
        raporTablosu([["ad", "Ay"], ["satis_matrah", "Satış Matrahı", "para"], ["hesaplanan", "Hesaplanan KDV", "para"],
          ["satis_tevkifat", "Satışta Tevkifat", "para"], ["alis_matrah", "Alış Matrahı", "para"], ["indirilecek", "İndirilecek KDV", "para"],
          ["onceki_devreden", "Önceki Aydan Devir", "para"], ["odenecek", "Ödenecek KDV (KDV-1)", "para"],
          ["devreden", "Sonraki Aya Devir", "para"], ["kdv2", "KDV-2 (alıştaki tevkifat)", "para"]], v.aylar,
        { toplam: ["satis_matrah", "hesaplanan", "satis_tevkifat", "alis_matrah", "indirilecek", "odenecek", "kdv2"],
          sinif: (a) => (a.odenecek ? "uyari-satir" : "") }),
        ACIKLAMA("Onaylı faturalardan hesaplanır, beyanname yerine geçmez; mali müşavirinizle karşılaştırmak içindir. Satış faturasındaki tevkifatı alıcı öder ve ödenecek KDV'den düşülür. Alış faturasındaki tevkifatı firmanız KDV-2 beyannamesiyle öder."));
      durum("KDV özeti hazır");
    },
    yenile: () => yenidenCiz(),
    excel: () => indir(`/api/excel/kdv?${q()}`, `kdv-ozeti-${f.yil}.xlsx`),
  });
}

function tevkifatRaporuAc() {
  const once = new Date(); once.setMonth(once.getMonth() - 1); // KDV-2 bir önceki ay için verilir
  const f = { ay: `${once.getFullYear()}-${String(once.getMonth() + 1).padStart(2, "0")}`, tumYil: false };
  const q = () => { const [y, a] = f.ay.split("-"); return `yil=${Number(y)}&ay=${f.tumYil ? 0 : Number(a)}`; };
  sekmeAc("rapor-tevkifat", "Tevkifat Raporu", {
    async ciz(el) {
      let v;
      try { v = await api(`/api/raporlar/tevkifat?${q()}`); } catch (e) { return bildir(e.message, true); }
      const kol = [["kod", "Kod"], ["oran", "Oran"], ["aciklama", "Açıklama"], ["belge_sayisi", "Belge"],
        ["matrah", "Tevkifata Tabi Tutar", "para"], ["kdv", "Hesaplanan KDV", "para"], ["tevkifat", "Tevkifat", "para"]];
      const toplam = { toplam: ["belge_sayisi", "matrah", "kdv", "tevkifat"] };
      el.append(MALI_UYARI(), h("div", { class: "liste-ust" }, h("h2", {}, "Tevkifat Raporu"),
          "Dönem:", h("input", { type: "month", value: f.ay, onchange: (e) => { f.ay = e.target.value || f.ay; yenidenCiz(); } }),
          h("label", {}, h("input", { type: "checkbox", checked: f.tumYil, onchange: (e) => { f.tumYil = e.target.checked; yenidenCiz(); } }), " Tüm yıl"),
          h("button", { class: "dugme ana", onclick: () => this.excel() }, "Excel'e aktar (F9)")),
        h("h3", {}, `Alışlarda tevkifat: KDV-2 ile firmanız öder (${para(v.kdv2)})`),
        v.alis.length ? raporTablosu(kol, v.alis, toplam) : h("p", {}, "Bu dönemde tevkifatlı alış yok."),
        h("h3", {}, `Satışlarda tevkifat: alıcı öder, KDV-1'den düşülür (${para(v.satis_tevkifat)})`),
        v.satis.length ? raporTablosu(kol, v.satis, toplam) : h("p", {}, "Bu dönemde tevkifatlı satış yok."),
        h("h3", {}, "Faturalar"),
        v.faturalar.length ? raporTablosu([["tarih", "Tarih", "tarih"], [(x) => (x.yon === "alis" ? "Alış" : "Satış"), "Taraf"], ["fatura_no", "Fatura No"],
          ["cari", "Cari"], ["kodlar", "Kod"], ["matrah", "KDV Hariç", "para"], ["kdv", "KDV", "para"], ["tevkifat", "Tevkifat", "para"],
          ["odenecek", "Cariye işlenen (ödenecek)", "para"], ["uyari", "Uyarı"]], v.faturalar,
          { toplam: ["matrah", "kdv", "tevkifat", "odenecek"], ac: (x) => faturaFormAc({ id: x.id }, null),
            sinif: (x) => (x.uyari ? "uyari-satir" : "") }) : null,
        ACIKLAMA("Onaylı faturaların kalemlerindeki tevkifat oranı ve KDVGUT koduna göre hesaplanır. Cariye tevkifat düşülmüş tutar işlenir. Kalemlerinde oran seçilmemiş eski faturalar 'Satırlarda oran yok' satırında fatura toplamıyla görünür. Satıra çift tıklayınca fatura açılır."));
      durum("Tevkifat raporu hazır");
    },
    yenile: () => yenidenCiz(),
    excel: () => indir(`/api/excel/tevkifat?${q()}`, `tevkifat-${f.ay}.xlsx`),
  });
}

function stopajRaporuAc() {
  const once = new Date(); once.setMonth(once.getMonth() - 1); // muhtasar bir önceki ay için verilir
  const f = { ay: `${once.getFullYear()}-${String(once.getMonth() + 1).padStart(2, "0")}`, tumYil: false };
  const q = () => { const [y, a] = f.ay.split("-"); return `yil=${Number(y)}&ay=${f.tumYil ? 0 : Number(a)}`; };
  sekmeAc("rapor-stopaj", "Stopaj Raporu", {
    async ciz(el) {
      let v;
      try { v = await api(`/api/raporlar/stopaj?${q()}`); } catch (e) { return bildir(e.message, true); }
      const kol = [["oran", "Oran"], ["belge_sayisi", "Belge"], ["matrah", "Stopaja Tabi Tutar", "para"], ["stopaj", "Stopaj", "para"]];
      const toplam = { toplam: ["belge_sayisi", "matrah", "stopaj"] };
      el.append(MALI_UYARI(), h("div", { class: "liste-ust" }, h("h2", {}, "Stopaj Raporu"),
          "Dönem:", h("input", { type: "month", value: f.ay, onchange: (e) => { f.ay = e.target.value || f.ay; yenidenCiz(); } }),
          h("label", {}, h("input", { type: "checkbox", checked: f.tumYil, onchange: (e) => { f.tumYil = e.target.checked; yenidenCiz(); } }), " Tüm yıl"),
          h("button", { class: "dugme ana", onclick: () => this.excel() }, "Excel'e aktar (F9)")),
        h("h3", {}, `Alışlarda stopaj: firmanız keser, muhtasar ile öder (${para(v.alis_stopaj)})`),
        v.alis.length ? raporTablosu(kol, v.alis, toplam) : h("p", {}, "Bu dönemde stopajlı alış yok."),
        h("h3", {}, `Satışlarda stopaj: alıcı keser, firmanız adına öder (${para(v.satis_stopaj)})`),
        v.satis.length ? raporTablosu(kol, v.satis, toplam) : h("p", {}, "Bu dönemde stopajlı satış yok."),
        h("h3", {}, "Faturalar"),
        v.faturalar.length ? raporTablosu([["tarih", "Tarih", "tarih"], [(x) => (x.yon === "alis" ? "Alış" : "Satış"), "Taraf"], ["fatura_no", "Fatura No"],
          ["cari", "Cari"], ["oran", "Oran"], ["matrah", "KDV Hariç", "para"], ["stopaj", "Stopaj", "para"],
          ["odenecek", "Cariye işlenen (ödenecek)", "para"]], v.faturalar,
          { toplam: ["matrah", "stopaj", "odenecek"], ac: (x) => faturaFormAc({ id: x.id }, null) }) : null,
        ACIKLAMA("Onaylı faturaların kalemlerindeki stopaj oranına göre hesaplanır. Stopaj ödenecek tutardan düşülür; cariye stopaj düşülmüş tutar işlenir. Satıra çift tıklayınca fatura açılır."));
      durum("Stopaj raporu hazır");
    },
    yenile: () => yenidenCiz(),
    excel: () => indir(`/api/excel/stopaj?${q()}`, `stopaj-${f.ay}.xlsx`),
  });
}

function babsAc() {
  const once = new Date(); once.setMonth(once.getMonth() - 1); // Ba-Bs bir önceki ay için verilir
  const f = { ay: `${once.getFullYear()}-${String(once.getMonth() + 1).padStart(2, "0")}`, limit: 5000 };
  const q = () => { const [y, a] = f.ay.split("-"); return `yil=${Number(y)}&ay=${Number(a)}&limit=${f.limit}`; };
  sekmeAc("rapor-babs", "Ba-Bs Formları", {
    async ciz(el) {
      let v;
      try { v = await api(`/api/raporlar/ba-bs?${q()}`); } catch (e) { return bildir(e.message, true); }
      const kol = [["unvan", "Ünvan"], ["vkn", "VKN/TCKN"], ["belge_sayisi", "Belge Sayısı"], ["tutar", "KDV Hariç Tutar", "para"]];
      const ac = (t) => (t.cari_id ? cariEkstreAc({ id: t.cari_id, unvan: t.unvan }) : null);
      el.append(MALI_UYARI(v.kaldirildi ? "Ba-Bs bildirimi Eylül 2024 döneminden itibaren verilmiyor (VUK Genel Tebliği 565); bu liste yalnız iç kontrol içindir." : null), h("div", { class: "liste-ust" }, h("h2", {}, "Ba-Bs Formları"),
          "Dönem:", h("input", { type: "month", value: f.ay, onchange: (e) => { f.ay = e.target.value || f.ay; yenidenCiz(); } }),
          h("label", {}, "Alt sınır (TL): ", h("input", { type: "number", value: f.limit, style: "width:100px",
            onchange: (e) => { f.limit = Number(e.target.value) || 5000; yenidenCiz(); } })),
          h("button", { class: "dugme ana", onclick: () => this.excel() }, "Excel'e aktar (F9)")),
        h("h3", {}, `Form Ba — mal ve hizmet alımları (${v.ba.length} kişi/kurum)`),
        v.ba.length ? raporTablosu(kol, v.ba, { toplam: ["belge_sayisi", "tutar"], ac }) : h("p", {}, "Sınırı aşan alış yok."),
        h("h3", {}, `Form Bs — mal ve hizmet satışları (${v.bs.length} kişi/kurum)`),
        v.bs.length ? raporTablosu(kol, v.bs, { toplam: ["belge_sayisi", "tutar"], ac }) : h("p", {}, "Sınırı aşan satış yok."),
        ACIKLAMA("Aynı kişi veya kurumla ay içindeki KDV hariç belge toplamı sınırı geçenler listelenir. Sınır KDV hariç 5.000 TL'dir; değişirse yukarıdan düzeltin. Satıra çift tıklayınca carinin ekstresi açılır."));
    },
    yenile: () => yenidenCiz(),
    excel: () => indir(`/api/excel/ba-bs?${q()}`, `ba-bs-${f.ay}.xlsx`),
  });
}

function gelirGiderAc() {
  const f = { yil: new Date().getFullYear() };
  sekmeAc("rapor-gelir-gider", "Gelir-Gider Tablosu", {
    async ciz(el) {
      let v;
      try { v = await api(`/api/raporlar/gelir-gider?yil=${f.yil}`); } catch (e) { return bildir(e.message, true); }
      const satir = (ad, aylar, sinif = "") => h("tr", { class: sinif }, h("td", {}, ad),
        ...aylar.map((x) => h("td", { class: "sayi" + (x < 0 ? " negatif" : "") }, x ? para(x) : "")),
        h("td", { class: "sayi" }, para(aylar.reduce((t, x) => t + x, 0))));
      el.append(MALI_UYARI(), h("div", { class: "liste-ust" }, h("h2", {}, `Gelir-Gider Tablosu ${f.yil}`), yilSecimi(f),
          h("button", { class: "dugme ana", onclick: () => this.excel() }, "Excel'e aktar (F9)")),
        h("div", { class: "tablo-kap" }, h("table", { class: "liste" },
          h("thead", {}, h("tr", {}, h("th", {}, "Kalem"), ...v.aylar.map((a) => h("th", { class: "sayi" }, a)), h("th", { class: "sayi" }, "Yıl"))),
          h("tbody", {}, satir("SATIŞLAR (KDV hariç)", v.gelir, "ara-toplam"),
            ...v.gider.map((g) => satir(g.tur, g.aylar)),
            satir("GİDERLER TOPLAMI", v.gider_toplam, "ara-toplam"), satir("NET (gelir − gider)", v.net, "ara-toplam")))),
        ACIKLAMA("Onaylı satış faturaları gelir, alış faturaları (KDV hariç, ÖİV gibi indirilemeyen vergiler dahil) ve doğrudan girilen masraflar gider olarak gider türüne göre yazılır. Amortisman, maaş gibi faturasız giderler bu tabloda yoktur."));
    },
    yenile: () => yenidenCiz(),
    excel: () => indir(`/api/excel/gelir-gider?yil=${f.yil}`, `gelir-gider-${f.yil}.xlsx`),
  });
}

/** Mutabakat: banka ekstresi ile program, bekleyen/ekstrede görünmeyen çekler, carilere mutabakat mektubu. */
function mutabakatAc() {
  const f = { tarih: new Date().toISOString().slice(0, 10) };
  sekmeAc("mutabakat", "Mutabakat", {
    async ciz(el) {
      let v;
      try { v = await api(`/api/mutabakat?tarih=${f.tarih}`); } catch (e) { return bildir(e.message, true); }
      const hareketAc = async (x) => (x.cek_id ? cekFormAc(await api(`/api/cekler/${x.cek_id}`), null) : hareketFormAc(await api(`/api/hareketler/${x.id}`)));
      const kayitKol = [["tarih", "Tarih", "tarih"], ["tur", "Tür"], [(x) => (x.yon === "giris" ? x.tutar : -x.tutar), "Tutar", "para"],
        ["cari", "Cari"], ["aciklama", "Açıklama"], ["neden", "Neden"]];
      const bankalar = v.banka.filter((b) => !b.kart || b.ekstre_tarihi);
      const secili = new Set();
      const cariKutu = (c) => h("input", { type: "checkbox", onchange: (e) => (e.target.checked ? secili.add(c.id) : secili.delete(c.id)) });
      el.append(h("div", { class: "liste-ust" }, h("h2", {}, "Mutabakat")),
        h("h3", {}, "Banka: ekstre ile program"),
        raporTablosu([["ad", "Hesap"], ["ekstre_tarihi", "Son ekstre tarihi", "tarih"], ["ekstre_bakiye", "Ekstre bakiyesi", "para"],
          ["program_bakiye", "Programda (aynı tarihte)", "para"], [(b) => (b.ekstre_tarihi ? (b.fark ? b.fark : "Tutuyor") : "Ekstre yüklenmemiş"), "Fark"],
          ["bakiye", "Bugünkü bakiye", "para"]], bankalar, { sinif: (b) => (b.fark ? "uyari-satir" : ""), ac: (b) => hareketListesiAc({ ...b, tur: b.kart ? "kredi_karti" : "banka" }) }),
        ...bankalar.filter((b) => b.kayitlar.length).flatMap((b) => [
          h("h4", {}, `${b.ad}: farkın nedeni olabilecek kayıtlar`),
          raporTablosu(kayitKol, b.kayitlar, { ac: hareketAc })]),
        h("h3", {}, `Çekler (portföyde ${para(v.cek.portfoy)} TL, ödenecek ${para(v.cek.verilen)} TL)`),
        v.cek.vadesi_gecen.length ? raporTablosu([["vade", "Vade", "tarih"], [(c) => (c.yon === "alinan" ? "Alınan" : "Verilen"), "Yön"],
          ["cek_no", "Çek No"], ["cari", "Cari"], ["durum", "Durum"], ["tutar", "Tutar", "para"], ["neden", "Neden"]], v.cek.vadesi_gecen,
          { ac: async (c) => cekFormAc(await api(`/api/cekler/${c.id}`), null) }) : h("p", {}, "Vadesi geçip bekleyen çek yok."),
        v.cek.ekstrede_yok.length ? raporTablosu([...kayitKol.slice(0, 3), ["banka", "Banka"], ["aciklama", "Açıklama"], ["neden", "Neden"]],
          v.cek.ekstrede_yok, { ac: hareketAc }) : "",
        h("h3", {}, "Cariler"),
        h("div", { class: "liste-ust" }, h("label", {}, "Tarih itibarıyla: ", h("input", { type: "date", value: f.tarih,
          onchange: (e) => { f.tarih = e.target.value || f.tarih; yenidenCiz(); } })),
          h("button", { class: "dugme ana", onclick: () => {
            if (!secili.size) return bildir("Mektup yazdırılacak carileri işaretleyin.", true);
            yazdirAc(`/api/yazdir/mutabakat-toplu?idler=${[...secili].join(",")}&tarih=${f.tarih}`);
          } }, "Seçilenlere mutabakat mektubu yazdır")),
        raporTablosu([[cariKutu, ""], ["unvan", "Cari"], ["vkn", "VKN"], [(c) => (c.bakiye > 0 ? c.bakiye : null), "Bize borçlu", "para"],
          [(c) => (c.bakiye < 0 ? -c.bakiye : null), "Bizim borcumuz", "para"]], v.cari,
          { ac: (c) => cariEkstreAc({ id: c.id, unvan: c.unvan }) }),
        ACIKLAMA("Banka satırı kırmızıysa ekstre ile program aynı tarihte farklı bakiye gösteriyor; altındaki kayıtlar farkın olası nedenidir. Satıra çift tıklayınca kayıt açılır."));
      durum("Mutabakat hazır");
    },
    yenile: () => yenidenCiz(),
  });
}

function yaslandirmaAc() {
  const f = { tarih: new Date().toISOString().slice(0, 10) };
  sekmeAc("rapor-yaslandirma", "Yaşlandırma (Vade Analizi)", {
    async ciz(el) {
      let v;
      try { v = await api(`/api/raporlar/yaslandirma?tarih=${f.tarih}`); } catch (e) { return bildir(e.message, true); }
      const kol = [["unvan", "Cari"], ["bakiye", "Açık Bakiye", "para"], ...v.dilimler.map(([a, b]) => [a, b, "para"]), ["en_eski", "En Eski Açık Vade", "tarih"]];
      const toplam = ["bakiye", ...v.dilimler.map(([a]) => a)];
      const ac = (r) => cariEkstreAc({ id: r.cari_id, unvan: r.unvan });
      const gecmis = v.acik_faturalar.filter((x) => x.gecen_gun > 0);
      el.append(h("div", { class: "liste-ust" }, h("h2", {}, "Yaşlandırma (Vade Analizi)"),
          "Tarih:", h("input", { type: "date", value: f.tarih, onchange: (e) => { f.tarih = e.target.value || f.tarih; yenidenCiz(); } }),
          h("button", { class: "dugme ana", onclick: () => this.excel() }, "Excel'e aktar (F9)")),
        h("h3", {}, "Alacaklarımız (cari bize borçlu)"),
        v.alacak.length ? raporTablosu(kol, v.alacak, { toplam, ac }) : h("p", {}, "Açık alacak yok."),
        h("h3", {}, "Borçlarımız (biz cariye borçluyuz)"),
        v.borc.length ? raporTablosu(kol, v.borc, { toplam, ac }) : h("p", {}, "Açık borç yok."),
        h("h3", {}, `Vadesi geçmiş açık faturalar (${gecmis.length})`),
        gecmis.length ? raporTablosu([["unvan", "Cari"], [(x) => (x.tur === "alacak" ? "Tahsil edilecek" : "Ödenecek"), "Tür"],
          ["belge", "Fatura No"], ["tarih", "Tarih", "tarih"], ["vade", "Vade", "tarih"], ["gecen_gun", "Geçen Gün"], ["acik_tutar", "Açık Tutar", "para"]],
        gecmis, { ac: (x) => faturaFormAc({ id: x.fatura_id }, null), sinif: (x) => (x.gecen_gun > 60 ? "islenemedi" : "") }) : h("p", {}, "Vadesi geçmiş açık fatura yok."),
        ACIKLAMA("Ödemeler en eski faturayı kapatır sayılır; kalan bakiye en son faturalardan oluşur ve vadesine (vade yoksa fatura tarihine) göre dilimlere ayrılır. 60 günü geçenler kırmızıdır."));
    },
    yenile: () => yenidenCiz(),
    excel: () => indir(`/api/excel/yaslandirma?tarih=${f.tarih}`, `yaslandirma-${f.tarih}.xlsx`),
  });
}

// ---------------------------------------------------------------- firma bilgileri ve kullanıcılar
function firmaBilgileriAc() {
  sekmeAc("firma", "Firma Bilgileri", {
    async ciz(el) {
      let s;
      try { s = await api("/api/sirket"); } catch (e) { return bildir(e.message, true); }
      const form = h("form", { class: "form-pencere", onsubmit: (e) => { e.preventDefault(); this.kaydet(); } },
        h("h2", {}, "Firma Bilgileri"),
        h("fieldset", {}, h("legend", {}, "Yazdırılan fatura, ekstre ve mutabakat mektuplarında görünür"), h("div", { class: "alanlar" },
          alan("Ünvan", "unvan", s.unvan, { zorunlu: true, genis: true }), alan("VKN", "vkn", s.vkn),
          alan("Vergi Dairesi", "vergi_dairesi", s.vergi_dairesi), alan("Telefon", "telefon", s.telefon), alan("E-posta", "eposta", s.eposta),
          alan("IBAN", "iban", s.iban), alan("Satış faturası serisi (3 harf, ör. AFS)", "fatura_seri", s.fatura_seri),
          alan("Adres", "adres", s.adres, { cok_satir: true, genis: true }))),
        h("p", { style: "color:#4a5866" }, "VKN girilirse PDF faturalarda hangi tarafın firmanız olduğu daha kesin bulunur. Fatura serisi girilirse yeni satış faturasına sıradaki numara (SERİ + YIL + 9 hane) otomatik önerilir."),
        h("div", { class: "dugmeler" }, h("button", { class: "dugme ana", disabled: BEN.rol !== "sahip" }, "Kaydet (F2)"),
          BEN.rol !== "sahip" ? h("span", {}, "Yalnız şirket sahibi değiştirebilir.") : null));
      el.append(form);
      this.form = form;
    },
    async kaydet() {
      if (!this.form.reportValidity()) return;
      try {
        await api("/api/sirket", { metod: "PUT", veri: formVerisi(this.form) });
        BEN = await api("/api/ben");
        $("#sirket-adi").textContent = BEN.sirket;
        bildir("Firma bilgileri kaydedildi.");
      } catch (e) { bildir(e.message, true); }
    },
  });
}

function kullanicilarAc() {
  sekmeAc("kullanicilar", "Kullanıcılar", {
    async ciz(el) {
      let v;
      try { v = await api("/api/kullanicilar"); } catch (e) { return bildir(e.message, true); }
      const sahipMi = BEN.rol === "sahip";
      const islem = async (fn, mesaj) => { try { await fn(); bildir(mesaj); yenidenCiz(); } catch (e) { bildir(e.message, true); } };
      const satirlar = v.kullanicilar.map((x) => h("tr", {}, h("td", {}, x.ad, x.ben ? " (siz)" : ""), h("td", {}, x.eposta),
        h("td", {}, h("select", { disabled: !sahipMi || x.ben, onchange: (e) => islem(() => api(`/api/kullanicilar/${x.id}`, { metod: "PUT", veri: { rol: e.target.value } }), "Yetki değiştirildi.") },
          Object.entries(v.roller).map(([d, m]) => h("option", { value: d, selected: d === x.rol }, m)))),
        h("td", {}, sahipMi ? h("button", { class: "dugme", onclick: () => {
          const sifre = prompt(`${x.ad} için yeni şifre (en az 6 karakter):`);
          if (sifre) islem(() => api(`/api/kullanicilar/${x.id}`, { metod: "PUT", veri: { sifre } }), "Şifre değiştirildi.");
        } }, "Şifre değiştir") : null,
        sahipMi && !x.ben ? h("button", { class: "dugme tehlike", onclick: () => confirm(`${x.ad} silinsin mi?`) &&
          islem(() => api(`/api/kullanicilar/${x.id}`, { metod: "DELETE" }), "Kullanıcı silindi.") }, "Sil") : null)));
      const form = h("form", { class: "liste-ust", onsubmit: (e) => {
        e.preventDefault();
        islem(() => api("/api/kullanicilar", { metod: "POST", veri: formVerisi(form) }), "Kullanıcı eklendi.");
      } }, h("b", {}, "Yeni kullanıcı:"), h("input", { name: "ad", placeholder: "Ad", required: true }),
        h("input", { name: "eposta", type: "email", placeholder: "E-posta", required: true }),
        h("input", { name: "sifre", type: "password", placeholder: "Şifre (en az 6)", required: true, minlength: 6 }),
        h("select", { name: "rol" }, Object.entries(v.roller).filter(([d]) => d !== "sahip").concat([["sahip", v.roller.sahip]])
          .map(([d, m]) => h("option", { value: d }, m))), h("button", { class: "dugme ana" }, "Ekle"));
      el.append(h("div", { class: "liste-ust" }, h("h2", {}, "Kullanıcılar ve Yetkiler")),
        h("div", { class: "tablo-kap" }, h("table", { class: "liste" },
          h("thead", {}, h("tr", {}, ["Ad", "E-posta", "Yetki", ""].map((b) => h("th", {}, b)))), h("tbody", {}, satirlar))),
        sahipMi ? form : h("p", {}, "Kullanıcı eklemeyi yalnız şirket sahibi yapabilir."),
        ACIKLAMA("Muhasebeci kayıt girer ve onaylar; izleyici yalnız görür ve rapor alır; sahip ayrıca kullanıcıları ve firma bilgilerini yönetir. Eklenen kişi aynı bilgisayardaki programa kendi e-posta ve şifresiyle girer."));
    },
    yenile: () => yenidenCiz(),
  });
}

// ---------------------------------------------------------------- hızlı arama (F3 / Ctrl+K)
function hizliAramaAc() {
  if ($(".hizli-arama")) return;
  const kutu = h("input", { placeholder: "Cari, fatura no, tutar, şantiye, çek no ya da menü adı yazın…", autocomplete: "off" });
  const liste = h("ul", { class: "arama-sonuc" });
  const d = h("dialog", { class: "secim-penceresi hizli-arama" }, kutu, liste,
    h("small", { class: "ipucu" }, "↑ ↓ ile seçin, Enter ile açın, Esc ile kapatın."));
  let sonuclar = [], imlec = 0, sira = 0;
  const kapat = () => d.close();
  const ac = (s) => { kapat(); s.ac(); };
  const ciz = () => liste.replaceChildren(...sonuclar.map((s, i) => h("li", { class: i === imlec ? "secili" : "", onmousedown: (e) => { e.preventDefault(); ac(s); } },
    h("span", { class: "tur" }, s.tur), h("span", {}, s.yazi), s.ek ? h("span", { class: "ek" }, s.ek) : null)));
  const ara = async () => {
    const q = kutu.value.trim(), benim = ++sira, anahtar = aramaAnahtari(q);
    const menu = anahtar ? MODULLER.flatMap(([grup, ogeler]) => ogeler.filter(([ad, fn]) => fn && aramaAnahtari(`${grup} ${ad}`).includes(anahtar))
      .map(([ad, fn]) => ({ tur: "Menü", yazi: ad, ek: grup, ac: fn }))).slice(0, 5) : [];
    let r = { cariler: [], faturalar: [], santiyeler: [], cekler: [] };
    if (q.length >= 2 || /\d/.test(q)) { try { r = await api(`/api/ara?q=${encodeURIComponent(q)}`); } catch { /* arama hatası sessiz */ } }
    if (benim !== sira) return;  // daha yeni bir arama başladı
    sonuclar = [
      ...r.cariler.map((c) => ({ tur: "Cari", yazi: c.unvan, ek: c.vkn || "", ac: async () => cariFormAc((await api("/api/cariler")).find((x) => x.id === c.id) || c) })),
      ...r.faturalar.map((f) => ({ tur: f.yon === "gelen" ? "Alış" : "Satış", yazi: `${f.fatura_no || "Numarasız"} · ${f.cari || ""}`,
        ek: `${tarih(f.tarih)} · ${para(f.genel_toplam)}${f.durum !== "onayli" ? " · " + (DURUM_ADI[f.durum] || f.durum) : ""}`, ac: () => faturaFormAc({ id: f.id }, null) })),
      ...r.santiyeler.map((s) => ({ tur: "Şantiye", yazi: s.ad, ac: async () => santiyeFormAc((await api("/api/santiyeler")).find((x) => x.id === s.id) || s) })),
      ...r.cekler.map((c) => ({ tur: "Çek", yazi: `${c.cek_no || "Numarasız"} · ${c.cari || ""}`, ek: `${tarih(c.vade)} · ${para(c.tutar)}`,
        ac: () => cekFormAc({ id: c.id, yon: c.yon, cek_no: c.cek_no }, c.yon) })),
      ...menu,
    ];
    imlec = 0;
    if (!sonuclar.length && q) liste.replaceChildren(h("li", { class: "bos" }, "Bulunamadı."));
    else ciz();
  };
  let zamanlayici;
  kutu.addEventListener("input", () => { clearTimeout(zamanlayici); zamanlayici = setTimeout(ara, 200); });
  kutu.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      imlec = (imlec + (e.key === "ArrowDown" ? 1 : -1) + sonuclar.length) % (sonuclar.length || 1);
      ciz();
    } else if (e.key === "Enter") { e.preventDefault(); if (sonuclar[imlec]) ac(sonuclar[imlec]); }
    e.stopPropagation();  // F2/Del gibi kısayollar arkadaki ekrana gitmesin
  });
  d.addEventListener("close", () => setTimeout(() => d.remove(), 0));
  document.body.append(d);
  d.showModal();
  kutu.focus();
}

// ---------------------------------------------------------------- ödeme takvimi / nakit akışı
const TAKVIM_TURLERI = { fatura: "Fatura", cek: "Çek", duzenli: "Düzenli", kart: "Kredi kartı" };

// Açık faturanın ödemesini / tahsilatını bilgileri dolu formla kaydeder
function faturaOdemesiAc(x) {
  const giris = x.yon === "giris";
  hareketFormAc(null, null, { yon: x.yon, tur: giris ? "tahsilat" : "odeme", tutar: x.tutar, cari_id: x.cari_id, aciklama: x.aciklama });
}

async function duzenliOdendi(d) {
  const { hesaplar } = await tumSecenekler();
  const hesapSec = h("select", {}, [["", "Kasa (nakit)"], ...hesaplar.map((b) => [b.id, b.ad])].map(([v, m]) => h("option", { value: v }, m)));
  if (d.banka_hesap_id) hesapSec.value = String(d.banka_hesap_id);
  const sec = await secimSor(`${d.ad}: ${para(d.tutar)}`, h("div", {},
    h("p", {}, "En eski ödenmemiş vade ödendi sayılacak."),
    h("label", {}, "Nereden: ", hesapSec),
    h("p", { class: "ipucu" }, "Banka ekstresinden zaten gelecekse \"Sadece işaretle\"yi seçin; çift kayıt olmaz.")),
  [["hareket", "Ödendi, kaydını da aç", true], ["isaret", "Sadece işaretle"], [null, "Vazgeç"]]);
  if (!sec) return false;
  try {
    await api(`/api/duzenli-odemeler/${d.id}/odendi`, { metod: "POST",
      veri: { hareket: sec === "hareket", banka_hesap_id: hesapSec.value ? Number(hesapSec.value) : null } });
    bildir(sec === "hareket" ? "Ödendi ve banka/kasa kaydı açıldı." : "Ödendi olarak işaretlendi.");
    yenidenCiz();
  } catch (e) { bildir(e.message, true); }
}

function odemeTakvimiAc() {
  let gun = 60;
  sekmeAc("odeme-takvimi", "Ödeme Takvimi", {
    async ciz(el) {
      let v;
      try { v = await api(`/api/raporlar/nakit-akisi?gun=${gun}`); } catch (e) { return bildir(e.message, true); }
      const o = v.ozet;
      const kart = (baslik, satirlar) => h("div", { class: "ozet-kart" }, h("h3", {}, baslik),
        h("dl", {}, satirlar.flatMap(([a, deger, kirmizi]) => [h("dt", {}, a), h("dd", { class: kirmizi ? "negatif" : "" }, para(deger))])));
      const islem = (x) => {
        if (x.tur === "fatura") return h("button", { class: "dugme kucuk", onclick: () => faturaOdemesiAc(x) }, x.yon === "giris" ? "Tahsilat al" : "Ödeme yap");
        if (x.tur === "duzenli") return h("button", { class: "dugme kucuk", onclick: () => duzenliOdendi({ id: x.duzenli_id, ad: x.aciklama, tutar: x.tutar }) }, "Ödendi");
        return h("button", { class: "dugme kucuk", onclick: () => cekFormAc({ id: x.cek_id, yon: x.cek_yon }, x.cek_yon) }, "Çeki aç");
      };
      el.append(
        h("div", { class: "liste-ust" }, h("h2", {}, "Ödeme Takvimi ve Nakit Akışı"),
          h("label", {}, "Süre: ", h("select", { onchange: (e) => { gun = Number(e.target.value); yenidenCiz(); } },
            [[30, "30 gün"], [60, "60 gün"], [90, "90 gün"], [180, "6 ay"]].map(([d, m]) => h("option", { value: d, selected: d === gun }, m))))),
        h("div", { class: "kart-satiri" },
          kart("Bugün", [["Banka + kasa", v.mevcut, v.mevcut < 0], ["En düşük beklenen bakiye", o.en_dusuk_bakiye, o.en_dusuk_bakiye < 0]]),
          kart("Vadesi geçmiş", [["Tahsil edilmemiş", o.gecikmis_giris, o.gecikmis_giris > 0], ["Ödenmemiş", o.gecikmis_cikis, o.gecikmis_cikis > 0]]),
          kart("Önümüzdeki 7 gün", [["Tahsil edilecek", o.hafta_giris], ["Ödenecek", o.hafta_cikis]]),
          kart("Önümüzdeki 30 gün", [["Tahsil edilecek", o.ay_giris], ["Ödenecek", o.ay_cikis]])),
        h("h3", {}, "Haftalık beklenen bakiye"),
        raporTablosu([["ad", "Hafta"], ["giris", "Tahsil Edilecek", "para"], ["cikis", "Ödenecek", "para"], ["bakiye", "Beklenen Bakiye", "para"]],
          v.donemler, { sinif: (d) => (d.bakiye < 0 ? "negatif" : "") }),
        h("h3", {}, "Vadeler"),
        v.kalemler.length ? raporTablosu([
          [(x) => h("span", {}, tarih(x.tarih), x.gecikmis ? ` (${x.gecikme_gun} gün geçti)` : ""), "Vade"],
          [(x) => TAKVIM_TURLERI[x.tur], "Tür"], ["aciklama", "Açıklama"], ["cari", "Cari"],
          [(x) => (x.yon === "giris" ? x.tutar : null), "Tahsil Edilecek", "para"], [(x) => (x.yon === "cikis" ? x.tutar : null), "Ödenecek", "para"],
          [islem, ""]], v.kalemler, {
          sinif: (x) => (x.gecikmis ? "negatif" : ""),
          ac: (x) => (x.fatura_id ? faturaFormAc({ id: x.fatura_id }, null) : x.cek_id ? cekFormAc({ id: x.cek_id, yon: x.cek_yon }, x.cek_yon) : duzenliOdemelerAc()),
        }) : h("p", {}, "Bu süre içinde vadesi gelen kayıt yok."),
        ACIKLAMA("Açık faturalar (vade yoksa cari kartındaki vade günü), elimizdeki çekler ve düzenli ödemelerden hesaplanır. Satıra çift tıklayınca kaydı açar."));
    },
    yenile: () => yenidenCiz(),
    excel: () => indir(`/api/excel/nakit-akisi?gun=${gun}`, "Ödeme Takvimi.xlsx"),
  });
}

// ---------------------------------------------------------------- düzenli ödemeler
const PERIYOTLAR = [[1, "Her ay"], [2, "2 ayda bir"], [3, "3 ayda bir"], [6, "6 ayda bir"], [12, "Yılda bir"]];

function duzenliOdemelerAc() {
  sekmeAc("duzenli-odemeler", "Düzenli Ödemeler", listeEkrani({
    baslik: "Düzenli Ödemeler (kira, kredi taksidi, SGK, maaş…)",
    kaynak: () => api("/api/duzenli-odemeler"),
    kolonlar: [
      { alan: "ad", baslik: "Ad" }, { alan: "yon", baslik: "Yön", deger: (d) => (d.yon === "giris" ? "Tahsilat" : "Ödeme") },
      { alan: "gun", baslik: "Ayın Günü" }, { alan: "periyot", baslik: "Sıklık", deger: (d) => Object.fromEntries(PERIYOTLAR)[d.periyot] },
      { alan: "cari_unvan", baslik: "Cari" }, { alan: "banka_hesap_ad", baslik: "Banka / Kasa", deger: (d) => d.banka_hesap_ad || "Kasa" },
      { alan: "sonraki_vade", baslik: "Sıradaki Vade", deger: (d) => (d.aktif ? h("span", { class: d.geciken ? "negatif" : "" },
        tarih(d.sonraki_vade), d.geciken ? ` (${d.geciken} ödenmemiş)` : "") : "Durduruldu"), metin: (d) => tarih(d.sonraki_vade) },
      { alan: "tutar", baslik: "Tutar", tip: "para" },
      { alan: "islem", baslik: "", deger: (d) => (d.aktif && d.sonraki_vade ? h("button", { class: "dugme kucuk",
        onclick: (e) => { e.stopPropagation(); duzenliOdendi(d); } }, "Ödendi") : ""), metin: () => "" },
    ],
    yeni: () => duzenliFormAc(),
    ac: (d) => duzenliFormAc(d),
    sil: (d) => api(`/api/duzenli-odemeler/${d.id}`, { metod: "DELETE" }),
  }));
}

function duzenliFormAc(d = null) {
  const s = sekmeAc(d ? `duzenli-${d.id}` : `duzenli-yeni-${Date.now()}`, d ? d.ad : "Yeni Düzenli Ödeme", {
    async ciz(el) {
      const { cariler, hesaplar } = await tumSecenekler();
      const x = d || { yon: "cikis", gun: new Date().getDate(), periyot: 1, baslangic: new Date().toISOString().slice(0, 10), aktif: true };
      const form = h("form", { class: "form-pencere", onsubmit: (e) => { e.preventDefault(); this.kaydet(); } },
        h("h2", {}, "Düzenli Ödeme / Tahsilat"),
        h("fieldset", {}, h("legend", {}, "Bilgiler"), h("div", { class: "alanlar" },
          alan("Ad (ör. Ofis kirası, Kredi taksidi)", "ad", x.ad, { zorunlu: true, genis: true }),
          alan("Yön", "yon", x.yon, { secenekler: [["cikis", "Ödeme (para çıkar)"], ["giris", "Tahsilat (para girer)"]] }),
          alan("Tutar", "tutar", x.tutar, { tip: "number", zorunlu: true }),
          alan("Ayın kaçında", "gun", x.gun, { tip: "number", zorunlu: true }),
          alan("Sıklık", "periyot", x.periyot, { secenekler: PERIYOTLAR }),
          alan("İlk vade ayı (başlangıç)", "baslangic", x.baslangic, { tip: "date", zorunlu: true }),
          alan("Bitiş (boşsa süresiz)", "bitis", x.bitis, { tip: "date" }),
          alan("Cari", "cari_id", x.cari_id, { secenekler: secenekListesi(cariler, "unvan", "— Cari yok —") }),
          alan("Genelde ödendiği yer", "banka_hesap_id", x.banka_hesap_id, { secenekler: secenekListesi(hesaplar, "ad", "Kasa (nakit)") }),
          alan("Durum", "aktif", x.aktif ? "1" : "", { secenekler: [["1", "Aktif"], ["", "Durduruldu"]] }),
          alan("Açıklama", "aciklama", x.aciklama, { genis: true }))),
        h("div", { class: "dugmeler" }, h("button", { class: "dugme ana" }, "Kaydet (F2)")));
      el.append(form, ACIKLAMA("Bir kez tanımlayın; her vadede Ödeme Takvimi'nde ve Genel Durum'da görünür. Ödendiğinde \"Ödendi\" düğmesiyle tek tıkla kaydedilir."));
      this.form = form;
      $("input", form).focus();
    },
    async kaydet() {
      if (!this.form.reportValidity()) return;
      const v = formVerisi(this.form, ["tutar", "gun", "periyot", "cari_id", "banka_hesap_id"]);
      v.aktif = !!v.aktif;
      try {
        if (d) await api(`/api/duzenli-odemeler/${d.id}`, { metod: "PUT", veri: v });
        else await api("/api/duzenli-odemeler", { metod: "POST", veri: v });
        bildir("Düzenli ödeme kaydedildi.");
        sekmeKapat(s);
        listeyiTazele("duzenli-odemeler");
      } catch (e) { bildir(e.message, true); }
    },
  });
}

// ---------------------------------------------------------------- cariye hatırlatma (WhatsApp / e-posta, ücretsiz)
async function cariHatirlat(cariId, kanal) {
  try {
    const [c, e] = await Promise.all([api("/api/cariler").then((l) => l.find((x) => x.id === cariId)), api(`/api/raporlar/cari-ekstre/${cariId}`)]);
    const metin = `Sayın ${c.unvan}, ${new Date().toLocaleDateString("tr-TR")} itibarıyla cari hesap bakiyesi `
      + `${para(Math.abs(e.bakiye))} TL ${e.bakiye >= 0 ? "(tarafımıza borcunuz)" : "(alacağınız)"} olarak görünmektedir. `
      + `Bilgilerinize sunar, iyi çalışmalar dileriz. ${BEN.sirket}`;
    if (kanal === "whatsapp") {
      let no = String(c.telefon || "").replace(/\D/g, "");
      if (!no) return bildir("Cari kartına telefon numarası ekleyin.", true);
      if (no.startsWith("0")) no = no.slice(1);
      if (no.length === 10) no = "90" + no;
      window.open(`https://wa.me/${no}?text=${encodeURIComponent(metin)}`, "_blank");
    } else {
      if (!c.eposta) return bildir("Cari kartına e-posta adresi ekleyin.", true);
      location.href = `mailto:${c.eposta}?subject=${encodeURIComponent("Cari hesap bakiyesi")}&body=${encodeURIComponent(metin)}`;
    }
  } catch (err) { bildir(err.message, true); }
}

async function cariHizliHareket(cariId, yon) {
  let bakiye = 0;
  try { bakiye = (await api(`/api/raporlar/cari-ekstre/${cariId}`)).bakiye; } catch { /* tutar boş kalır */ }
  const tutar = yon === "giris" ? (bakiye > 0 ? bakiye : null) : (bakiye < 0 ? -bakiye : null);
  hareketFormAc(null, null, { yon, tur: yon === "giris" ? "tahsilat" : "odeme", cari_id: cariId, tutar });
}

// ---------------------------------------------------------------- çek / senet raporları
// Alınan ve verilen bütün çekler tek listede: yön, durum, cari, ciro edilen, banka, vade aralığı, şantiye süzgeçleriyle
function cekRaporuAc() {
  const f = { yon: "", durum: "", cari_id: "", ciro_cari_id: "", banka_hesap_id: "", vade_bas: "", vade_bit: "", santiye_id: "" };
  const qs = () => Object.entries(f).filter(([, v]) => v).map(([k, v]) => `${k}=${encodeURIComponent(v)}`).join("&");
  const ozet = h("div", { class: "ipucu", style: "margin:4px 0" });
  let sec = null;
  const secenekYukle = tumSecenekler().then((x) => { sec = x; }).catch(() => { sec = { cariler: [], santiyeler: [], hesaplar: [] }; });
  const DURUMLAR = [["", "Tüm durumlar"], ["acik", "Açık (portföy, takas, teminat, ödenmedi)"], ["portfoyde", "Portföyde"], ["tahsilde", "Takasta"],
    ["teminatta", "Teminatta"], ["ciro_edildi", "Ciro edildi"], ["tahsil_edildi", "Tahsil edildi"], ["verildi", "Ödenmedi (verilen)"],
    ["odendi", "Ödendi (verilen)"], ["karsiliksiz", "Karşılıksız / protesto"], ["iade", "İade"]];
  const secim = (ad, liste) => h("select", { onchange: (e) => { f[ad] = e.target.value; } },
    liste.map(([d, m]) => h("option", { value: d, selected: String(d) === String(f[ad]) }, m)));
  const ekran = listeEkrani({
    baslik: "Çek / Senet Raporları",
    kaynak: async () => {
      await secenekYukle;
      const r = await api(`/api/raporlar/cekler?${qs()}`);
      const o = r.ozet;
      ozet.textContent = `Alınan: ${o.alinan.adet} çek, ${para(o.alinan.tutar)} (elimizde/takasta ${para(o.alinan.acik)}) · `
        + `Verilen: ${o.verilen.adet} çek, ${para(o.verilen.tutar)} (ödenmemiş ${para(o.verilen.acik)})`;
      return r.satirlar;
    },
    ustAlan: (yenile) => {
      const cariListe = [["", "Tüm cariler"], ...(sec?.cariler || []).map((c) => [c.id, c.unvan])];
      const cariS = secim("cari_id", cariListe), ciroS = secim("ciro_cari_id", [["", "Ciro edilen: tümü"], ...cariListe.slice(1)]);
      const kap = h("div", { style: "display:flex;flex-wrap:wrap;gap:6px;align-items:center;width:100%" },
        secim("yon", [["", "Alınan ve verilen"], ["alinan", "Alınan çekler"], ["verilen", "Verilen çekler"]]),
        secim("durum", DURUMLAR), h("span", { class: "cari-filtre" }, cariS), h("span", { class: "cari-filtre" }, ciroS),
        secim("banka_hesap_id", [["", "Tüm banka hesapları"], ...(sec?.hesaplar || []).filter((b) => b.tur !== "kredi_karti").map((b) => [b.id, b.ad])]),
        secim("santiye_id", [["", "Tüm şantiyeler"], ...(sec?.santiyeler || []).map((x) => [x.id, x.ad])]),
        h("label", {}, "Vade ", h("input", { type: "date", value: f.vade_bas, onchange: (e) => { f.vade_bas = e.target.value; } })),
        h("label", {}, "– ", h("input", { type: "date", value: f.vade_bit, onchange: (e) => { f.vade_bit = e.target.value; } })),
        h("button", { class: "dugme ana", onclick: () => yenile() }, "Listele"),
        h("button", { class: "dugme", onclick: () => indir(`/api/excel/cekler?${qs()}`, "cek-senet-raporu.xlsx") }, "Excel'e aktar"),
        ozet);
      queueMicrotask(() => { aramaliSec(cariS, { bosYazi: "Tüm cariler" }); aramaliSec(ciroS, { bosYazi: "Ciro edilen: tümü" }); });
      return kap;
    },
    kolonlar: [
      { alan: "yon", baslik: "Yön", deger: (c) => (c.yon === "alinan" ? "Alınan" : "Verilen") },
      { alan: "durum_adi", baslik: "Durum" },
      { alan: "alis_tarihi", baslik: "Alış / Veriliş", tip: "tarih" },
      { alan: "vade", baslik: "Vade", deger: vadeHucresi, metin: (c) => tarih(c.vade) },
      ...CEK_GUN_KOLONLARI,
      { alan: "cek_no", baslik: "Çek No" }, { alan: "banka", baslik: "Banka" }, { alan: "kesideci", baslik: "Çeki Yazan Firma" },
      { alan: "lehtar", baslik: "Lehtar (çekin yazıldığı firma)" },
      { alan: "cari_unvan", baslik: "Kimden Alındı / Kime Verildi" }, { alan: "ciro_cari_unvan", baslik: "Ciro Edilen" },
      { alan: "banka_hesap_ad", baslik: "Banka Hesabı" }, { alan: "santiye_ad", baslik: "Şantiye" },
      { alan: "giris", baslik: "Alınan Tutar", tip: "para", deger: (c) => (c.yon === "alinan" ? c.tutar : null) },
      { alan: "cikis", baslik: "Verilen Tutar", tip: "para", deger: (c) => (c.yon === "verilen" ? c.tutar : null) },
    ],
    ac: (c) => cekFormAc(c, c.yon),
  });
  ekran.excel = () => indir(`/api/excel/cekler?${qs()}`, "cek-senet-raporu.xlsx");
  sekmeAc("cek-raporu", "Çek / Senet Raporları", ekran);
}

// ---------------------------------------------------------------- vade bildirimi
// Vadesi gelen ya da geçen çek (alınan ve verilen) varsa açılışta pencere çıkar; program açık kaldıkça her saat yeniden
// hatırlatır (Windows bildirimi de). Çek ödendi / tahsil edildi / ciro edildi işaretlenince listeden düşer.
const VADE_HATIRLATMA_MS = 60 * 60 * 1000;
let vadeZamanlayici = null;
function vadeOncedenGun() { try { return Number(localStorage.getItem("vade_onceden_gun")) || 0; } catch { return 0; } }
async function vadeBildirimiKontrol(pencere = true, hepsi = false) {
  if (!TOKEN) return;
  let liste = [];
  try { liste = await api(`/api/cekler/vadesi-gelen?gun=${vadeOncedenGun()}`); } catch { return; }
  const yazi = $("#vade-uyari");
  if (yazi) {
    yazi.hidden = !liste.length;
    yazi.textContent = liste.length ? `⚠ ${liste.length} çekin vadesi geldi` : "";
  }
  if (!pencere || (!liste.length && !hepsi)) return;
  const verilen = liste.filter((c) => c.yon === "verilen"), alinan = liste.filter((c) => c.yon === "alinan");
  const metin = [verilen.length ? `${verilen.length} verilen çek ödenecek (${para(verilen.reduce((t, c) => t + c.tutar, 0))})` : "",
    alinan.length ? `${alinan.length} alınan çek tahsil edilecek (${para(alinan.reduce((t, c) => t + c.tutar, 0))})` : ""].filter(Boolean).join(", ");
  try {
    if (liste.length && "Notification" in window && Notification.permission === "granted") {
      const n = new Notification("Vadesi gelen çek var", { body: metin + ". Ödenince programda işaretleyin.", tag: "muhasebe-vade", requireInteraction: true });
      n.onclick = () => { window.focus(); n.close(); };
    }
  } catch { /* bildirim verilemedi */ }
  vadePenceresi(liste, metin);
}
function vadePenceresi(liste, metin) {
  document.querySelector(".vade-perde")?.remove();
  const kapat = () => perde.remove();
  const satir = (c) => h("tr", { class: "tiklanir", onclick: () => { kapat(); cekFormAc(c, c.yon); } },
    h("td", {}, vadeHucresi(c)), h("td", {}, c.yon === "alinan" ? "Tahsil edilecek" : "Ödenecek"), h("td", {}, c.cek_no || ""),
    h("td", {}, c.cari_unvan || c.kesideci || ""), h("td", {}, c.durum_adi), h("td", { class: "sayi" }, para(c.tutar)));
  const onceden = h("select", { onchange: (e) => { try { localStorage.setItem("vade_onceden_gun", e.target.value); } catch {} vadeBildirimiKontrol(true, true); } },
    [[0, "vade günü"], [1, "1 gün önce"], [3, "3 gün önce"], [7, "7 gün önce"]].map(([d, m]) => h("option", { value: d, selected: d === vadeOncedenGun() }, m)));
  const izin = "Notification" in window && Notification.permission === "default"
    ? h("button", { class: "dugme", onclick: async () => { try { await Notification.requestPermission(); } catch {} izin.remove(); } }, "Windows bildirimini aç") : null;
  const perde = h("div", { class: "vade-perde", onclick: (e) => { if (e.target === perde) kapat(); } },
    h("div", { class: "vade-pencere" },
      h("h3", {}, liste.length ? "Vadesi gelen çekler" : "Vadesi gelen çek yok"),
      liste.length ? h("p", {}, metin + ". Çeke tıklayıp \"Bankadan ödendi\", \"Kasadan ödendi\" ya da \"Tahsil edildi\" seçin; işaretleyene kadar her saat hatırlatılır.") : null,
      liste.length ? h("div", { class: "tablo-kap" }, h("table", { class: "liste" },
        h("thead", {}, h("tr", {}, ["Vade", "Ne yapılacak", "Çek No", "Cari", "Durum", "Tutar"].map((b) => h("th", {}, b)))),
        h("tbody", {}, liste.map(satir)))) : null,
      h("div", { class: "dugmeler" }, h("label", {}, "Haber ver: ", onceden), izin,
        h("button", { class: "dugme", onclick: () => { kapat(); cekRaporuAc(); } }, "Çek / Senet Raporları"),
        h("button", { class: "dugme ana", onclick: kapat }, "Tamam"))));
  document.body.append(perde);
}
function vadeBildirimiBaslat() {
  clearInterval(vadeZamanlayici);
  setTimeout(() => vadeBildirimiKontrol(true), 1500);
  vadeZamanlayici = setInterval(() => vadeBildirimiKontrol(true), VADE_HATIRLATMA_MS);
}

// ---------------------------------------------------------------- verileri sıfırla
// Denemeden sonra temiz başlangıç: bütün kayıtlar silinir, firma bilgileri ve kullanıcılar kalır. Önce yedek alınır.
function verileriSifirla() {
  const girdi = h("input", { type: "text", placeholder: "SIFIRLA", autocomplete: "off", style: "width:100%;margin-top:8px" });
  const d = h("dialog", { class: "secim-penceresi" },
    h("h3", { style: "color:#c62828" }, "Bütün veriler silinsin mi?"),
    h("div", {}, h("p", {}, "Faturalar, ekstreler, banka ve kasa hareketleri, çekler, cariler, şantiyeler ve banka hesapları silinir. Firma bilgileri ve kullanıcılar kalır."),
      h("p", {}, "Silmeden önce yedek alınır; vazgeçerseniz Yedekler'den \"Bu yedeğe dön\" ile geri gelir."),
      h("b", {}, "Onaylamak için SIFIRLA yazın:"), girdi),
    h("div", { class: "dugmeler" },
      h("button", { type: "button", class: "dugme", onclick: () => d.close() }, "Vazgeç"),
      h("button", { type: "button", class: "dugme tehlike", onclick: async () => {
        if (girdi.value.trim().toLocaleUpperCase("tr").replace("İ", "I") !== "SIFIRLA") { girdi.focus(); return bildir("Onay için SIFIRLA yazın.", true); }
        try {
          durum("Yedek alınıyor ve veriler siliniyor…");
          await api("/api/sistem/sifirla", { metod: "POST", veri: { onay: girdi.value } });
          try { for (const a of Object.keys(localStorage)) if (a.startsWith("toplu-cek-")) localStorage.removeItem(a); } catch { /* depolama kapalı */ }
          d.close();
          alert("Bütün veriler silindi. Önceki hâli yedekte duruyor.");
          location.reload();
        } catch (e) { bildir(e.message, true); durum("Hazır"); }
      } }, "Bütün verileri sil")));
  d.addEventListener("close", () => setTimeout(() => d.remove(), 0));
  document.body.append(d);
  d.showModal();
  girdi.focus();
}

// ---------------------------------------------------------------- modül menüsü
const MODULLER = [
  ["Fatura", [["Belgeden Fatura Oku", aiOkumaAc], ["Alış Faturaları", () => faturaListesiAc("gelen")], ["Satış Faturaları", () => faturaListesiAc("giden")]]],
  ["Günlük Takip", [["Hızlı Arama (F3)", () => hizliAramaAc()], ["Ödeme Takvimi / Nakit Akışı", odemeTakvimiAc], ["Düzenli Ödemeler", duzenliOdemelerAc]]],
  ["Cari", [["Cari Listesi", cariListesiAc], ["Yeni Cari", () => cariFormAc()], ["Cari Bakiye Raporu", cariBakiyeAc], ["Mutabakat", mutabakatAc]]],
  ["Şantiye", [["Şantiyeler", santiyeListesiAc], ["Şantiye Bazlı Faturalar", santiyeFaturalariAc], ["Şantiye Maliyet Raporu", santiyeOzetAc]]],
  ["Çek / Senet", [["Alınan Çekler", () => cekListesiAc("alinan")], ["Verilen Çekler", () => cekListesiAc("verilen")], ["Toplu Çek Girişi", () => topluCekAc("alinan")], ["Vade Takvimi", vadeTakvimiAc],
    ["Çek / Senet Raporları", cekRaporuAc], ["Vadesi Gelen Çekler", () => vadeBildirimiKontrol(true, true)]]],
  ["Banka / Kasa", [["Banka Hesapları", bankaHesaplariAc], ["Nakit Kasa", kasaAc], ["Ekstre Yükle", () => ekstreYukleAc()],
    ["Kredi Kartı Ekstresi Yükle", () => ekstreYukleAc("kart")], ["Onay Bekleyen Hareketler", taslakHareketlerAc],
    ["Tahsilat / Ödeme", hareketListesiAc], ["Mutabakat", mutabakatAc]]],
  ["Mali Raporlar", [["KDV Özeti", kdvOzetiAc], ["Tevkifat Raporu", tevkifatRaporuAc], ["Stopaj Raporu", stopajRaporuAc], ["Ba-Bs Formları", babsAc], ["Gelir-Gider Tablosu", gelirGiderAc],
    ["Yaşlandırma (Vade Analizi)", yaslandirmaAc]]],
  ["Araçlar", [["Excel İşlemleri", excelIslemleriAc], ["Yedekler", yedeklerAc], ["Firma Bilgileri", firmaBilgileriAc], ["Kullanıcılar", kullanicilarAc], ["Değişiklik Geçmişi", () => gecmisAc()],
    ["Güncellemeleri Denetle", guncellemeleriDenetle], ["Verileri Sıfırla", verileriSifirla]]],
];
function modulPaneliCiz() {
  $("#modul-paneli").replaceChildren(...MODULLER.map(([grup, ogeler]) => {
    const g = h("div", { class: "modul-grup" }, h("div", { onclick: () => g.classList.toggle("kapali") }, grup),
      h("ul", {}, ogeler.map(([ad, fn]) => h("li", { class: fn ? "" : "yakinda", onclick: fn ? () => fn() : null }, ad))));
    return g;
  }));
}

// ---------------------------------------------------------------- giriş
let kayitModu = false;
$("#kayit-gecis").addEventListener("click", () => {
  kayitModu = !kayitModu;
  document.querySelectorAll(".kayit-alani").forEach((l) => { l.hidden = !kayitModu; $("input", l).required = kayitModu; });
  $("#giris-formu button").textContent = kayitModu ? "Hesap aç" : "Giriş";
  $("#kayit-gecis").textContent = kayitModu ? "Zaten hesabım var" : "Yeni şirket hesabı aç";
});
$("#giris-formu").addEventListener("submit", async (e) => {
  e.preventDefault();
  const v = Object.fromEntries(new FormData(e.target));
  try {
    const r = await fetch(kayitModu ? "/api/kayit" : "/api/giris", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(v) });
    const j = await r.json();
    if (!r.ok) throw new Error(typeof j.detail === "string" ? j.detail : "Giriş yapılamadı. Bilgileri kontrol edin.");
    TOKEN = j.token;
    try { localStorage.setItem("muhasebe_token", TOKEN); } catch {}
    baslat();
  } catch (err) { bildir(err.message, true); }
});
$("#cikis").addEventListener("click", cikisYap);
$("#hizli-ara").addEventListener("click", () => hizliAramaAc());

function cikisYap() {
  TOKEN = null;
  try { localStorage.removeItem("muhasebe_token"); } catch {}
  $("#uygulama").hidden = true;
  $("#giris-ekrani").hidden = false;
}

async function baslat() {
  if (!TOKEN) return cikisYap();
  try { [BEN, HAREKET_TURLERI] = await Promise.all([api("/api/ben"), api("/api/hareket-turleri")]); } catch { return cikisYap(); }
  $("#giris-ekrani").hidden = true;
  $("#uygulama").hidden = false;
  $("#sirket-adi").textContent = BEN.sirket;
  $("#kullanici-adi").textContent = BEN.ad;
  $("#durum-tarih").textContent = `${BEN.sirket} · ${new Date().toLocaleDateString("tr-TR")} · Sürüm ${BEN.surum || "?"}`;
  aracCubugunuCiz();
  modulPaneliCiz();
  if (!sekmeler.length) bosEkran();
  aracCubugunuGuncelle();
  if (!$("#vade-uyari")) $("#durum-tarih").after(h("span", { id: "vade-uyari", class: "negatif tiklanir", hidden: true, style: "margin-left:12px;font-weight:600",
    onclick: () => vadeBildirimiKontrol(true, true) }));
  vadeBildirimiBaslat();
}
baslat();
