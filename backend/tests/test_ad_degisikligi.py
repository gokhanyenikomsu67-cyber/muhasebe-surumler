"""Şantiye/depo adı değişince bağlı kayıtlar aynı kayıtta kalır; eski adla gelen kayıt yeni şantiye/depo açmaz (sentetik veri)."""
import uuid

from tests.test_api import client, yeni_kullanici
from tests.test_kural import xlsx


def test_santiye_adi_degisince_kayitlar_ayni_santiyede_eski_ad_taninir():
    h = yeni_kullanici(f"{uuid.uuid4().hex}@ornek.com")
    s = client.post("/api/santiyeler", json={"ad": "Deneme Şantiye"}, headers=h).json()
    satici = client.post("/api/cariler", json={"unvan": "Örnek Market", "vkn": "1111111111"}, headers=h).json()
    f = client.post("/api/faturalar", json={"yon": "gelen", "fatura_no": "ADD1", "tarih": "2026-09-10", "cari_id": satici["id"],
                                            "santiye_id": s["id"], "kalemler": [{"aciklama": "Kum", "miktar": 1, "birim_fiyat": 100, "kdv_orani": 20}]},
                    headers=h).json()
    r = client.put(f"/api/santiyeler/{s['id']}", json={"ad": "Deneme 1.Grup", "durum": "aktif"}, headers=h)
    assert r.status_code == 200 and r.json()["eski_adlar"] == "Deneme Şantiye"
    assert [x["ad"] for x in client.get("/api/santiyeler", headers=h).json()] == ["Deneme 1.Grup"]
    assert client.get(f"/api/faturalar/{f['id']}", headers=h).json()["santiye_id"] == s["id"]
    # Eski adla açılmak istenen şantiye yenisi olmaz; Excel'de eski adla gelen kayıt aynı şantiyeye gider
    assert client.post("/api/santiyeler", json={"ad": "DENEME ŞANTİYE"}, headers=h).json()["id"] == s["id"]
    veri = xlsx([["Fatura No", "Tarih", "Tür (Alış/Satış)", "Cari Ünvan", "Kalem Açıklaması", "Birim Fiyat", "Şantiye"],
                 ["ADD2", "01.10.2026", "Alış", "Örnek Market", "Çimento", 10, "deneme santiye"]])
    r = client.post("/api/excel/faturalar/yukle", files={"dosya": ("f.xlsx", veri)}, headers=h)
    assert r.json()["yeni_santiye"] == 0
    ikinci = next(x for x in client.get("/api/faturalar?yon=gelen", headers=h).json() if x["fatura_no"] == "ADD2")
    assert ikinci["santiye_id"] == s["id"]
    # Eski ada geri dönülebilir; başka şantiyenin (eski) adı verilemez
    assert client.put(f"/api/santiyeler/{s['id']}", json={"ad": "Deneme Şantiye", "durum": "aktif"}, headers=h).json()["eski_adlar"] == "Deneme 1.Grup"
    b = client.post("/api/santiyeler", json={"ad": "Başka"}, headers=h).json()
    assert client.put(f"/api/santiyeler/{b['id']}", json={"ad": "deneme 1.grup", "durum": "aktif"}, headers=h).status_code == 409


def test_depo_adi_degisince_taseron_borcu_ayni_depoda():
    h = yeni_kullanici(f"{uuid.uuid4().hex}@ornek.com")
    s = client.post("/api/santiyeler", json={"ad": "Deneme"}, headers=h).json()
    taseron = client.post("/api/cariler", json={"unvan": "Taşeron Deneme"}, headers=h).json()
    satici = client.post("/api/cariler", json={"unvan": "Örnek Market", "vkn": "1111111111"}, headers=h).json()
    d = client.post("/api/depolar", json={"ad": "Depo Bir", "santiye_id": s["id"], "cari_id": taseron["id"]}, headers=h).json()
    f = client.post("/api/faturalar", json={"yon": "gelen", "fatura_no": "ADD3", "tarih": "2026-09-10", "cari_id": satici["id"], "santiye_id": s["id"],
                                            "kalemler": [{"aciklama": "Kum", "miktar": 1, "birim_fiyat": 100, "kdv_orani": 20, "depo_id": d["id"]}]},
                    headers=h).json()
    client.post(f"/api/faturalar/{f['id']}/onayla", headers=h)
    r = client.put(f"/api/depolar/{d['id']}", json={"ad": "Taşeron Yeni Ad", "santiye_id": s["id"], "cari_id": taseron["id"]}, headers=h)
    assert r.status_code == 200 and r.json()["ad"] == "Taşeron Yeni Ad" and r.json()["eski_adlar"] == "Depo Bir"
    rapor = client.get("/api/raporlar/depo-harcamalari", headers=h).json()
    assert [(x["depo"], x["kalem"]) for x in rapor] == [("Taşeron Yeni Ad", "Kum")]
    assert client.get(f"/api/raporlar/cari-ekstre/{taseron['id']}", headers=h).json()["bakiye"] == 120
    assert client.post("/api/depolar", json={"ad": "depo bir", "santiye_id": s["id"]}, headers=h).json()["id"] == d["id"]
