"""Aynı firmaya açılmış cariler birleşir: faturaları, çekleri ve bakiyesi tek cariye geçer; eski adla gelen kayıt o cariye işlenir (sentetik veri)."""
import uuid

from tests.test_api import client, yeni_kullanici
from tests.test_cek_banka import bakiye


def test_cariler_birlesir_bakiye_ve_eski_ad_tek_caride():
    h = yeni_kullanici(f"{uuid.uuid4().hex}@ornek.com")
    asil = client.post("/api/cariler", json={"unvan": "Deneme Elektrik Sist.Yat.ve Tic.A.Ş.", "vkn": "1234567890"}, headers=h).json()
    kisa = client.post("/api/cariler", json={"unvan": "DENEME ELEKTRİK", "tur": "musteri", "iban": "TR000000000000000000000009"}, headers=h).json()
    tek = client.post("/api/cariler", json={"unvan": "DENEME"}, headers=h).json()
    f = client.post("/api/faturalar", json={"yon": "gelen", "fatura_no": "CB1", "tarih": "2026-09-10", "cari_id": kisa["id"],
                                            "kalemler": [{"aciklama": "Kablo", "miktar": 1, "birim_fiyat": 1000, "kdv_orani": 0}]}, headers=h).json()
    client.post(f"/api/faturalar/{f['id']}/onayla", headers=h)
    c = client.post("/api/cekler", json={"yon": "verilen", "tutar": 400, "vade": "2026-12-01", "cari_id": tek["id"], "cek_no": "77"}, headers=h).json()
    assert bakiye(h, kisa["id"]) + bakiye(h, tek["id"]) == -600

    r = client.post(f"/api/cariler/{asil['id']}/birlestir", json={"idler": [asil["id"], kisa["id"], tek["id"]]}, headers=h)
    assert r.status_code == 200
    m = r.json()
    assert m["eski_adlar"] == "DENEME ELEKTRİK\nDENEME" and m["iban"] == "TR000000000000000000000009" and m["tur"] == "her_ikisi"
    assert [x["id"] for x in client.get("/api/cariler", headers=h).json()] == [asil["id"]]
    assert bakiye(h, asil["id"]) == -600
    assert client.get(f"/api/faturalar/{f['id']}", headers=h).json()["cari_id"] == asil["id"]
    assert next(x for x in client.get("/api/cekler", headers=h).json() if x["id"] == c["id"])["cari_id"] == asil["id"]
    # Eski adla açılmak istenen cari yenisi olmaz
    assert client.post("/api/cariler", json={"unvan": "Deneme Elektrik"}, headers=h).json()["id"] == asil["id"]
    # VKN'leri farklı cariler ayrı firmadır, birleşmez
    baska = client.post("/api/cariler", json={"unvan": "Başka Firma", "vkn": "9876543210"}, headers=h).json()
    assert client.post(f"/api/cariler/{asil['id']}/birlestir", json={"idler": [baska["id"]]}, headers=h).status_code == 409
