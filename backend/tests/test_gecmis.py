"""İptal/düzeltme ve değişiklik geçmişi: kayıtlı işlem silinmeden iptal edilir, her değişiklik kim/ne zaman/ne ile yazılır."""
from tests.test_api import client
from tests.test_cek_banka import bakiye, banka_bakiye, kur


def gecmis(h, **q):
    return client.get("/api/gecmis", params=q, headers=h).json()


def test_onayli_fatura_degisikligi_iptali_ve_geri_alinmasi_gecmise_yazilir():
    h, musteri, tedarikci, banka = kur()
    f = client.post("/api/faturalar", json={"yon": "giden", "fatura_no": "S9", "cari_id": musteri["id"], "tarih": "2026-10-01",
                                            "kalemler": [{"aciklama": "Daire", "birim_fiyat": 1000, "kdv_orani": 0}]}, headers=h).json()
    # Taslakken yapılan düzenleme geçmişe yazılmaz
    client.put(f"/api/faturalar/{f['id']}", json={"yon": "giden", "fatura_no": "S9", "cari_id": musteri["id"], "tarih": "2026-10-02",
                                                  "kalemler": [{"aciklama": "Daire", "birim_fiyat": 1000, "kdv_orani": 0}]}, headers=h)
    assert gecmis(h, tablo="fatura", kayit_id=f["id"]) == []
    client.post(f"/api/faturalar/{f['id']}/onayla", headers=h)
    # Onaylıyken tutar ve tarih değişti: eski ve yeni değer, kullanıcı adı kaydedilir
    client.put(f"/api/faturalar/{f['id']}", json={"yon": "giden", "fatura_no": "S9", "cari_id": musteri["id"], "tarih": "2026-10-05",
                                                  "kalemler": [{"aciklama": "Daire", "birim_fiyat": 1200, "kdv_orani": 0}]}, headers=h)
    g = gecmis(h, tablo="fatura", kayit_id=f["id"])
    assert [x["islem"] for x in g] == ["degisti", "onaylandi"]
    assert g[0]["alanlar"]["genel_toplam"] == [1000, 1200] and g[0]["alanlar"]["tarih"] == ["2026-10-02", "2026-10-05"]
    assert "kalemler" in g[0]["alanlar"] and "Tarih: 2026-10-02 → 2026-10-05" in g[0]["ozet"]
    assert g[0]["kullanici"] == "Ali"
    assert bakiye(h, musteri["id"]) == 1200

    # İptal: silinmez, bakiyeden düşer, nedeni kalır; iptalliyken değiştirilemez
    assert client.post(f"/api/faturalar/{f['id']}/iptal", json={"neden": ""}, headers=h).status_code == 400
    assert client.post(f"/api/faturalar/{f['id']}/iptal", json={"neden": "Yanlış cariye kesildi"}, headers=h).status_code == 200
    assert bakiye(h, musteri["id"]) == 0
    iptal = client.get(f"/api/faturalar/{f['id']}", headers=h).json()
    assert iptal["durum"] == "iptal" and iptal["iptal_nedeni"] == "Yanlış cariye kesildi"
    assert client.put(f"/api/faturalar/{f['id']}", json={"yon": "giden", "fatura_no": "S9", "kalemler": []}, headers=h).status_code == 400
    assert client.get("/api/raporlar/kdv?yil=2026", headers=h).json()["aylar"][9]["satis_matrah"] == 0

    client.post(f"/api/faturalar/{f['id']}/iptal-geri", headers=h)
    assert bakiye(h, musteri["id"]) == 1200
    assert [x["islem"] for x in gecmis(h, tablo="fatura", kayit_id=f["id"])][:2] == ["iptal_geri", "iptal"]

    # Silinen onaylı faturanın son hali (kalemleriyle) geçmişte durur
    client.delete(f"/api/faturalar/{f['id']}", headers=h)
    son = gecmis(h, tablo="fatura", kayit_id=f["id"])[0]
    assert son["islem"] == "silindi" and son["alanlar"]["kalemler"][0]["aciklama"] == "Daire"
    assert son["alanlar"]["genel_toplam"] == 1200


def test_hareket_iptali_bakiyeden_duser_nakit_karsiligi_da_kalkar():
    h, musteri, _, banka = kur()
    t = client.post("/api/hareketler", json={"tarih": "2026-10-03", "yon": "giris", "tur": "tahsilat", "tutar": 500,
                                             "cari_id": musteri["id"], "banka_hesap_id": banka["id"]}, headers=h).json()
    n = client.post("/api/hareketler", json={"tarih": "2026-10-04", "yon": "cikis", "tur": "nakit_cekim", "tutar": 200,
                                             "banka_hesap_id": banka["id"]}, headers=h).json()
    assert client.get("/api/kasa", headers=h).json()["bakiye"] == 200
    for x in (t, n):
        assert client.post(f"/api/hareketler/{x['id']}/iptal", json={"neden": "Mükerrer giriş"}, headers=h).status_code == 200
    assert banka_bakiye(h, banka["id"]) == 1000 and bakiye(h, musteri["id"]) == 0
    assert client.get("/api/kasa", headers=h).json()["bakiye"] == 0
    assert client.put(f"/api/hareketler/{t['id']}", json={"tarih": "2026-10-03", "yon": "giris", "tur": "tahsilat",
                                                          "tutar": 1}, headers=h).status_code == 400
    client.post(f"/api/hareketler/{n['id']}/iptal-geri", headers=h)
    assert client.get("/api/kasa", headers=h).json()["bakiye"] == 200
    g = gecmis(h, tablo="hareket", kayit_id=t["id"])
    assert [x["islem"] for x in g] == ["iptal", "eklendi"]
    # Onay bekleyen ekstre satırının silinmesi geçmişi doldurmaz; onaylı hareketin silinmesi yazılır
    client.delete(f"/api/hareketler/{n['id']}", headers=h)
    assert gecmis(h, tablo="hareket", kayit_id=n["id"])[0]["islem"] == "silindi"


def test_cari_ve_cek_degisiklikleri_kim_ne_zaman():
    h, musteri, tedarikci, banka = kur()
    client.put(f"/api/cariler/{musteri['id']}", json={"unvan": "Ahmet Yapı A.Ş.", "tur": "musteri", "vkn": "5555555555"}, headers=h)
    g = gecmis(h, tablo="cari", kayit_id=musteri["id"])
    assert g[0]["islem"] == "degisti" and g[0]["alanlar"]["unvan"] == ["Ahmet Yapı", "Ahmet Yapı A.Ş."]
    c = client.post("/api/cekler", json={"yon": "alinan", "tutar": 300, "vade": "2026-12-01", "cari_id": musteri["id"]}, headers=h).json()
    client.post(f"/api/cekler/{c['id']}/islem", json={"islem": "ciro", "tarih": "2026-11-01", "cari_id": tedarikci["id"]}, headers=h)
    g = gecmis(h, tablo="cek", kayit_id=c["id"])
    assert g[0]["alanlar"]["durum"] == ["portfoyde", "ciro_edildi"] and "Ciro edilen cari: - → Demir Ltd" in g[0]["ozet"]
    # Başka şirket bu geçmişi göremez
    from tests.test_api import yeni_kullanici
    baska = yeni_kullanici("baska-gecmis@ornek.com")
    assert gecmis(baska) == []
