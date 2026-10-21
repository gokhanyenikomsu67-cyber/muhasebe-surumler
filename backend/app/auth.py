"""Basit şifre ve oturum yönetimi."""
import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from .db import get_db
from .models import Kullanici, Oturum

_TUR = 200_000
OTURUM_SURESI = timedelta(days=30)


def sifre_hashle(sifre: str) -> str:
    tuz = os.urandom(16)
    ozet = hashlib.pbkdf2_hmac("sha256", sifre.encode(), tuz, _TUR)
    return f"{tuz.hex()}${ozet.hex()}"


def sifre_dogru(sifre: str, kayitli: str) -> bool:
    tuz_hex, ozet_hex = kayitli.split("$")
    ozet = hashlib.pbkdf2_hmac("sha256", sifre.encode(), bytes.fromhex(tuz_hex), _TUR)
    return hmac.compare_digest(ozet.hex(), ozet_hex)


def oturum_ac(db: Session, kullanici: Kullanici) -> str:
    token = secrets.token_hex(32)
    db.add(Oturum(token=token, kullanici_id=kullanici.id))
    db.commit()
    return token


def aktif_kullanici(authorization: str = Header(default=""), db: Session = Depends(get_db)) -> Kullanici:
    token = authorization.removeprefix("Bearer ").strip()
    oturum = db.get(Oturum, token) if token else None
    if oturum and oturum.olusturma and datetime.utcnow() - oturum.olusturma > OTURUM_SURESI:
        db.delete(oturum)  # eski oturum: yeniden giriş istenir
        db.commit()
        oturum = None
    if not oturum:
        raise HTTPException(401, "Giriş yapmanız gerekiyor.")
    db.info["kullanici_id"] = oturum.kullanici_id  # değişiklik geçmişinde "kim"
    return oturum.kullanici


def yazabilir(k: Kullanici = Depends(aktif_kullanici)) -> Kullanici:
    if k.rol == "izleyici":
        raise HTTPException(403, "Bu işlem için yetkiniz yok.")
    return k
