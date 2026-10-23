import os

# Testler okuma işlevlerini değiştirir (monkeypatch); ayrı işlemlerde bu değişiklik görünmez, okuma aynı işlemde yapılır.
os.environ.setdefault("MUHASEBE_ISLEMCI", "1")
