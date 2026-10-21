"""Unutulan giriş şifresini sıfırlar (bilgisayardaki kurulum için).

Şifreler geri çevrilemeyecek şekilde saklandığı için eski şifre öğrenilemez; yenisi belirlenir.
Kullanım: sifre_sifirla.bat dosyasına çift tıklayın (ya da: python sifre_sifirla.py).
"""
from sqlalchemy import delete, select

from app.auth import sifre_hashle
from app.db import Base, SessionLocal, engine
from app.models import Kullanici, Oturum


def main():
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        kullanicilar = db.scalars(select(Kullanici).order_by(Kullanici.id)).all()
        if not kullanicilar:
            print("Bu bilgisayarda kayıtlı hesap yok. Programı açıp 'Yeni şirket hesabı aç' ile hesap oluşturun.")
            return
        print("Kayıtlı hesaplar:\n")
        for i, k in enumerate(kullanicilar, 1):
            print(f"  {i}. {k.eposta}  ({k.ad}, {k.sirket.unvan})")
        secim = input("\nŞifresi sıfırlanacak hesabın numarası: ").strip()
        if not secim.isdigit() or not 1 <= int(secim) <= len(kullanicilar):
            print("Geçersiz numara, hiçbir şey değiştirilmedi.")
            return
        k = kullanicilar[int(secim) - 1]
        sifre = input("Yeni şifre (en az 6 karakter): ").strip()
        if len(sifre) < 6:
            print("Şifre en az 6 karakter olmalı, hiçbir şey değiştirilmedi.")
            return
        k.sifre_hash = sifre_hashle(sifre)
        db.execute(delete(Oturum).where(Oturum.kullanici_id == k.id))  # açık oturumları kapat
        db.commit()
        print(f"\nŞifre değiştirildi. Programa {k.eposta} e-postası ve yeni şifrenizle girin.")


if __name__ == "__main__":
    main()
