"""WhatsApp botu: program açıkken ofis bilgisayarında küçük bir köprü (whatsapp/kopru.mjs, Node.js) çalıştırır.
Köprü botun ayrı numarasıyla WhatsApp'a bağlanır (bir kez QR okutulur), gelen yazıyı programa sorar (/api/bot/mesaj),
cevabı aynı sohbete yazar. Cevaplar soru.py'de, yapay zekasız; yalnız Bot Numaraları'ndaki kişilere cevap verilir.

Köprü yalnız bu bilgisayardan (127.0.0.1) ve her açılışta yeniden üretilen gizli anahtarla konuşabilir.
"""
import json
import os
import re
import secrets
import shutil
import subprocess
import threading
import time
from pathlib import Path

from .db import VERI_KLASORU

PROGRAM = Path(__file__).resolve().parents[2]
KOPRU_KLASORU = PROGRAM / "whatsapp"
OTURUM = VERI_KLASORU / "whatsapp-oturum"   # WhatsApp bağlantı bilgileri (QR okutulunca); yedeğe girmez
AYAR = VERI_KLASORU / "whatsapp-bot.json"   # {"acik": true}
ANAHTAR = secrets.token_hex(24)
ANA_ADRES = os.environ.get("MUHASEBE_BOT_ADRES", "http://127.0.0.1:" + os.environ.get("MUHASEBE_PORT", "8000"))

DURUM: dict = {"durum": "kapali", "qr": None, "numara": None, "hata": None, "zaman": 0.0}
KURULUM: dict = {"durum": None, "hata": None}
TANINMAYANLAR: list[dict] = []  # son tanınmayan yazanlar (ekranda "Ekle" ile numara olarak eklenir)
_SUREC: dict = {"p": None}
_KILIT = threading.Lock()


def ayarlar() -> dict:
    try:
        return json.loads(AYAR.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def ayar_yaz(**degerler) -> None:
    a = {**ayarlar(), **degerler}
    AYAR.write_text(json.dumps(a, ensure_ascii=False), encoding="utf-8")


def rakamlar(numara: str | None) -> str:
    """'+90 532 123 45 67', '0532...', '905321234567@s.whatsapp.net' -> '905321234567'."""
    r = re.sub(r"\D", "", (numara or "").split("@")[0].split(":")[0])
    if len(r) == 11 and r.startswith("0"):
        r = "9" + r  # 0532... -> 90532...
    elif len(r) == 10 and r.startswith("5"):
        r = "90" + r
    return r


def node_yolu() -> str | None:
    bulunan = shutil.which("node")
    if bulunan:
        return bulunan
    for aday in (Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "nodejs" / "node.exe",
                 Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "nodejs" / "node.exe"):
        if aday.exists():
            return str(aday)
    return None


def kurulu_mu() -> bool:
    return bool(node_yolu()) and (KOPRU_KLASORU / "node_modules" / "baileys").exists()


def _npm(node: str) -> list[str]:
    npm = Path(node).parent / ("npm.cmd" if os.name == "nt" else "npm")
    return [str(npm) if npm.exists() else (shutil.which("npm") or "npm")]


def kur() -> None:
    """Node.js (yoksa, Windows'ta winget ile) ve köprünün paketleri (sürümleri package-lock.json'da sabit)."""
    gizli = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        if not node_yolu():
            if os.name != "nt":
                raise RuntimeError("Node.js bulunamadı.")
            subprocess.run(["winget", "install", "-e", "--id", "OpenJS.NodeJS.LTS", "--silent",
                            "--accept-source-agreements", "--accept-package-agreements"],
                           capture_output=True, timeout=1800, creationflags=gizli)
        node = node_yolu()
        if not node:
            raise RuntimeError("Node.js kurulamadı. İnternet bağlantısını kontrol edip tekrar deneyin.")
        sonuc = subprocess.run([*_npm(node), "ci", "--omit=dev", "--no-audit", "--no-fund"], cwd=KOPRU_KLASORU,
                               capture_output=True, text=True, timeout=1800, creationflags=gizli)
        if sonuc.returncode or not kurulu_mu():
            raise RuntimeError("Paketler kurulamadı: " + (sonuc.stderr or sonuc.stdout or "")[-300:])
        KURULUM.update(durum="bitti", hata=None)
    except (OSError, subprocess.TimeoutExpired, RuntimeError) as e:
        KURULUM.update(durum="hata", hata=str(e))


def baslat() -> None:
    with _KILIT:
        if _SUREC["p"] and _SUREC["p"].poll() is None:
            return
        node = node_yolu()
        if not node or not kurulu_mu():
            DURUM.update(durum="kurulu_degil", qr=None)
            return
        OTURUM.mkdir(parents=True, exist_ok=True)
        ortam = {**os.environ, "MUHASEBE_ADRES": ANA_ADRES, "MUHASEBE_BOT_ANAHTARI": ANAHTAR, "BOT_OTURUM": str(OTURUM)}
        gunluk = open(VERI_KLASORU / "whatsapp-gunlugu.txt", "a", encoding="utf-8")
        _SUREC["p"] = subprocess.Popen([node, str(KOPRU_KLASORU / "kopru.mjs")], cwd=KOPRU_KLASORU, env=ortam,
                                       stdout=gunluk, stderr=gunluk, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        DURUM.update(durum="baslatiliyor", qr=None, hata=None, zaman=time.time())


def durdur() -> None:
    with _KILIT:
        p = _SUREC["p"]
        if p and p.poll() is None:
            p.terminate()
            try:
                p.wait(10)
            except subprocess.TimeoutExpired:
                p.kill()
        _SUREC["p"] = None
        DURUM.update(durum="kapali", qr=None)


def cikis_yap() -> None:
    """Botun WhatsApp bağlantısını unutur: yeniden açılınca yeni QR ister (başka numara bağlanabilir)."""
    durdur()
    shutil.rmtree(OTURUM, ignore_errors=True)
    DURUM.update(numara=None)


def calisiyor_mu() -> bool:
    return bool(_SUREC["p"] and _SUREC["p"].poll() is None)


def bekci() -> None:
    """Açılışta ve sonra dakikada bir: bot açık seçildiyse köprü çalışsın (kapanırsa yeniden başlar)."""
    while True:
        try:
            if ayarlar().get("acik") and not calisiyor_mu():
                baslat()
        except Exception as e:  # noqa: BLE001
            DURUM.update(durum="hata", hata=str(e))
        time.sleep(60)


def taninmayan(gonderen: str, alt: str | None, ad: str | None, metin: str) -> None:
    kayit = {"gonderen": gonderen, "alt": alt, "ad": ad, "metin": (metin or "")[:80], "zaman": time.strftime("%d.%m %H:%M")}
    TANINMAYANLAR[:] = [x for x in TANINMAYANLAR if x["gonderen"] != gonderen][-19:] + [kayit]
