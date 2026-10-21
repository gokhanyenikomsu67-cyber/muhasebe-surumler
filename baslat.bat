@echo off
title Muhasebe Programi
cd /d "%~dp0"
set "GUNLUK=%~dp0baslat-gunlugu.txt"
> "%GUNLUK%" echo Muhasebe baslatma gunlugu %DATE% %TIME%
call :yaz "Muhasebe programi baslatiliyor... (her adim bu pencerede yazar; ayni bilgi baslat-gunlugu.txt dosyasinda)"
call :yaz "Not: bu pencerenin icine tiklarsaniz Windows yaziyi durdurabilir; durursa Esc tusuna basin."

rem Eski surum hala aciksa once kapatilir: acik program paket dosyalarini kilitler, kurulum/guncelleme yapilamaz
set "ESKI="
for /f "tokens=5" %%p in ('netstat -ano ^| findstr /r /c:":8000 .*LISTENING"') do (tasklist /fi "pid eq %%p" | findstr /i "python" >nul && taskkill /f /pid %%p >nul 2>nul && set "ESKI=1")
if defined ESKI call :yaz "      Acik kalan eski program penceresi kapatildi."
if defined ESKI timeout /t 2 /nobreak >nul

rem Program icinden "Guncelle" denildiyse yeni surum (program kapaliyken) yazilir. Bu dosya da degisebilecegi icin
rem islem tek blokta yapilir ve program yeni pencerede yeniden acilir
if exist "guncelleme-bekliyor.txt" if exist "backend\.venv\Scripts\python.exe" (
  call :yaz "Yeni surum yukleniyor; verileriniz ve ayarlariniz degismez..."
  "backend\.venv\Scripts\python.exe" -I "backend\app\guncelleme.py" uygula >> "%GUNLUK%" 2>&1
  start "" cmd /c baslat.bat
  exit
)

rem --- Python var mi? Cekte el yazisi okuma Python 3.12/3.13 ister (daha yenisinde paketi yok); once onlar aranir ---
call :yaz "[1/6] Python araniyor..."
set "PY="
call :py_bul
if defined PY goto python_var
rem Uygun surum yok: varsa daha yeni/eski Python yedekte tutulur (program onunla da acilir, yalniz el yazisi okunmaz)
set "PY_YEDEK="
where py >nul 2>nul && py -3 --version <nul >nul 2>nul && set "PY_YEDEK=py -3"
if not defined PY_YEDEK python --version <nul >nul 2>nul && set "PY_YEDEK=python"
set "SON_PY="
if exist "python312-son-deneme.txt" set /p SON_PY=<"python312-son-deneme.txt"
if defined PY_YEDEK if "%SON_PY%"=="%DATE%" goto py_yedek
where winget >nul 2>nul || goto py_yedek
call :yaz "      Uygun Python (3.12) kuruluyor; bir kez yapilir, birkac dakika surebilir. Windows izin sorarsa Evet deyin."
winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements >> "%GUNLUK%" 2>&1
call :py_bul
if defined PY goto python_var
> "python312-son-deneme.txt" echo %DATE%
call :yaz "      Python 3.12 kurulamadi; program yine acilir, yalniz cekte el yazisi okunmaz. Yarin tekrar denenir."
:py_yedek
set "PY=%PY_YEDEK%"
if defined PY goto python_var
call :yaz "HATA: Python kurulamadi. Internet baglantinizi kontrol edip baslat.bat'i tekrar acin."
call :yaz "Duzelmezse bu pencerenin fotografini ya da baslat-gunlugu.txt dosyasini gonderin."
pause
exit /b

:python_var
call :py_uygun %PY% && del "python312-son-deneme.txt" >nul 2>nul
%PY% --version > "%TEMP%\muhasebe-python-surumu.txt" 2>&1
set "PYV="
set /p PYV=<"%TEMP%\muhasebe-python-surumu.txt"
call :yaz "      %PYV% bulundu."

rem --- Ilk acilista API anahtarini sor ---
if exist ".env" goto anahtar_var
echo.
echo Program yapay zeka olmadan calisir: e-Fatura XML, PDF, fotograf, Excel ve banka ekstreleri
echo bu bilgisayarda okunur. Claude API anahtari yalniz istege bagli yapay zeka okumasi icindir.
echo Anahtariniz yoksa bos birakip Enter'a basin.
set "ANAHTAR="
set /p "ANAHTAR=API anahtari: "
> ".env" echo ANTHROPIC_API_KEY=%ANAHTAR%
>> ".env" echo MUHASEBE_YEDEK_KLASORLERI=%USERPROFILE%\Documents\MuhasebeYedek

:anahtar_var
for /f "usebackq eol=# tokens=1,* delims==" %%a in (".env") do set "%%a=%%b"

rem --- Paketler: yalniz ilk acilista ve paket listesi degisince kurulur; her acilista internete gidilmez ---
cd backend
call :yaz "[2/6] Program ortami kontrol ediliyor..."
if exist ".venv-eski" rmdir /s /q ".venv-eski" >nul 2>nul
if not exist ".venv\Scripts\python.exe" goto venv_yok
rem Ortam uygun olmayan Python ile kurulduysa ve simdi uygun Python varsa ortam bir kez yeniden kurulur (veriler etkilenmez)
call :py_uygun ".venv\Scripts\python.exe" && goto venv_var
call :py_uygun %PY% || goto venv_var
call :yaz "      Program ortami uygun Python ile yeniden hazirlaniyor (bir kez, internet gerekir)..."
ren ".venv" ".venv-eski" >nul 2>nul
if exist ".venv\Scripts\python.exe" goto venv_var
rmdir /s /q ".venv-eski" >nul 2>nul
:venv_yok
call :yaz "      Ilk acilis: program ortami hazirlaniyor..."
%PY% -m venv .venv
if exist ".venv\Scripts\python.exe" goto venv_var
call :yaz "HATA: program ortami olusturulamadi. Bu pencerenin fotografini gonderin."
pause
exit /b
:venv_var
if not exist ".venv\kurulu-requirements.txt" goto zorunlu_kur
fc /b requirements.txt ".venv\kurulu-requirements.txt" >nul 2>nul || goto zorunlu_kur
call :yaz "      Paketler kurulu, internete gidilmiyor."
goto zorunlu_denetle

:zorunlu_kur
call :yaz "[3/6] Program paketleri kuruluyor (ilk acilista ya da guncellemede, internet gerekir, birkac dakika surebilir)..."
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check --prefer-binary --timeout 30 -r requirements.txt
if errorlevel 1 call :yaz "      Bazi paketler kurulamadi; asagida kontrol ediliyor."
if not errorlevel 1 copy /y requirements.txt ".venv\kurulu-requirements.txt" >nul

:zorunlu_denetle
rem Zorunlu paketler eksikse program baslamaz (yarim acilip hata vermesin); eksik olan ekrana yazilir
call :yaz "[4/6] Program dosyalari kontrol ediliyor..."
".venv\Scripts\python.exe" -c "import fastapi, uvicorn, sqlalchemy, anthropic, openpyxl, multipart, pypdf, lxml, pdfplumber, pypdfium2, PIL" >> "%GUNLUK%" 2>&1
if not errorlevel 1 goto zorunlu_tamam
echo.
".venv\Scripts\python.exe" -c "import fastapi, uvicorn, sqlalchemy, anthropic, openpyxl, multipart, pypdf, lxml, pdfplumber, pypdfium2, PIL"
call :yaz "HATA: programin gerekli paketleri eksik. Internet baglantinizi kontrol edip baslat.bat'i tekrar acin."
call :yaz "Duzelmezse bu pencerenin fotografini ya da baslat-gunlugu.txt dosyasini gonderin."
del ".venv\kurulu-requirements.txt" >nul 2>nul
pause
exit /b

:zorunlu_tamam
rem Istege bagli paketler (HEIC, karekod): yalniz hazir paket indirilir (derleme yok), gunde en cok bir kez denenir
if exist ".venv\kurulu-requirements-ek.txt" fc /b requirements-ek.txt ".venv\kurulu-requirements-ek.txt" >nul 2>nul && goto ek_tamam
set "SON_EK="
if exist ".venv\ek-son-deneme.txt" set /p SON_EK=<".venv\ek-son-deneme.txt"
if "%SON_EK%"=="%DATE%" goto ek_tamam
call :yaz "[5/6] Ek paketler (iPhone fotografi, karekod) kuruluyor; kurulamazsa atlanir..."
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check --only-binary :all: --timeout 20 -r requirements-ek.txt >> "%GUNLUK%" 2>&1
rem Not: parantezli blok kullanilmaz; blok icindeki ")" betigi sessizce kapatiyordu
if not errorlevel 1 goto ek_kuruldu
> ".venv\kurulum-hatasi.txt" echo Ek paketler - iPhone fotografi ve karekod okuma - kurulamadi.
> ".venv\ek-son-deneme.txt" echo %DATE%
call :yaz "      Ek paketler kurulamadi; program yine acilir, yarin tekrar denenir."
goto ek_tamam
:ek_kuruldu
call :yaz "      Ek paketler kuruldu."
copy /y requirements-ek.txt ".venv\kurulu-requirements-ek.txt" >nul
del ".venv\kurulum-hatasi.txt" >nul 2>nul
del ".venv\ek-son-deneme.txt" >nul 2>nul
:ek_tamam
rem Istege bagli el yazisi okuma (cekte vade ve tutar): ayri kurulur, kurulamazsa digerlerini etkilemez
if exist ".venv\kurulu-requirements-el.txt" fc /b requirements-el.txt ".venv\kurulu-requirements-el.txt" >nul 2>nul && goto el_tamam
set "SON_EL="
if exist ".venv\el-son-deneme.txt" set /p SON_EL=<".venv\el-son-deneme.txt"
if "%SON_EL%"=="%DATE%" goto el_tamam
call :yaz "      Cekte el yazisi okuma paketi kuruluyor (bir kez, internet gerekir); kurulamazsa atlanir..."
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check --only-binary :all: --timeout 30 -r requirements-el.txt >> "%GUNLUK%" 2>&1
if not errorlevel 1 goto el_kuruldu
> ".venv\el-son-deneme.txt" echo %DATE%
call :yaz "      El yazisi okuma paketi kurulamadi; program yine acilir, yarin tekrar denenir."
goto el_tamam
:el_kuruldu
rem Okuma modeli simdi bir kez indirilir (ilk cek okunurken beklenmesin); indirilemezse ilk okumada denenir
".venv\Scripts\python.exe" -c "from rapidocr import RapidOCR; RapidOCR()" >> "%GUNLUK%" 2>&1
copy /y requirements-el.txt ".venv\kurulu-requirements-el.txt" >nul
del ".venv\el-son-deneme.txt" >nul 2>nul
:el_tamam

rem --- Resimden okuma (taranmis PDF, fotograf, cek): Tesseract bir kez kurulur, sonra internetsiz calisir ---
rem Kurulum basarisiz olursa gunde bir kez yeniden denenir; program icinden de "Kur" ile denenebilir.
del ".venv\tesseract-denendi" >nul 2>nul
call :tesseract_var && goto ocr_var
set "SON_DENEME="
if exist ".venv\tesseract-son-deneme.txt" set /p SON_DENEME=<".venv\tesseract-son-deneme.txt"
if "%SON_DENEME%"=="%DATE%" goto ocr_var
where winget >nul 2>nul || goto ocr_var
call :yaz "[5/6] Fotograf okuma programi (Tesseract) kuruluyor. Windows izin sorarsa Evet deyin."
call :yaz "      Kurulmazsa program yine acilir; yalniz fotograf okunamaz."
winget install -e --id UB-Mannheim.TesseractOCR --accept-source-agreements --accept-package-agreements
call :tesseract_var && goto tesseract_kuruldu
> ".venv\tesseract-son-deneme.txt" echo %DATE%
call :yaz "      Fotograf okuma programi kurulamadi; program yine acilir, yarin tekrar denenir."
goto ocr_var
:tesseract_kuruldu
del ".venv\tesseract-son-deneme.txt" >nul 2>nul
call :yaz "      Fotograf okuma programi kuruldu."
goto ocr_var

:tesseract_var
where tesseract >nul 2>nul && exit /b 0
if exist "%ProgramFiles%\Tesseract-OCR\tesseract.exe" exit /b 0
if exist "%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe" exit /b 0
exit /b 1

:py_bul
rem Once py ile 3.12/3.13, sonra winget'in kurdugu yerler denenir (yeni kurulanlar bu pencerenin PATH'inde olmayabilir)
where py >nul 2>nul && call :py_uygun py -3.12 && set "PY=py -3.12" && exit /b 0
where py >nul 2>nul && call :py_uygun py -3.13 && set "PY=py -3.13" && exit /b 0
call :py_uygun "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" && set "PY="%LOCALAPPDATA%\Programs\Python\Python312\python.exe"" && exit /b 0
call :py_uygun "%ProgramFiles%\Python312\python.exe" && set "PY="%ProgramFiles%\Python312\python.exe"" && exit /b 0
call :py_uygun "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" && set "PY="%LOCALAPPDATA%\Programs\Python\Python313\python.exe"" && exit /b 0
call :py_uygun "%ProgramFiles%\Python313\python.exe" && set "PY="%ProgramFiles%\Python313\python.exe"" && exit /b 0
exit /b 1

:py_uygun
rem Verilen Python 3.12 ya da 3.13 ise 0 doner; <nul: py surumu yoksa kurulum sorusu bekletmesin
%* -c "import sys; sys.exit(0 if sys.version_info[:2] in ((3,12),(3,13)) else 1)" <nul >nul 2>nul
exit /b

:yaz
echo %~1
>> "%GUNLUK%" echo %TIME% %~1
exit /b 0

:ocr_var
echo.
set "ADRES=127.0.0.1"
if "%MUHASEBE_AG%"=="1" set "ADRES=0.0.0.0"
call :yaz "[6/6] Program aciliyor: http://localhost:8000 (tarayici birkac saniye icinde acilir)"
if "%MUHASEBE_AG%"=="1" echo AG MODU ACIK: ayni agdaki bilgisayarlar bu bilgisayarin IP adresinden :8000 ile girebilir.
if "%MUHASEBE_AG%"=="1" echo Yeni hesap yalniz bu bilgisayardan acilir; kullanicilari Araclar ^> Kullanicilar'dan ekleyin.
echo Verileriniz: %USERPROFILE%\Documents\Muhasebe Verileri (yeni paketi baska klasore acsaniz da kaybolmaz)
echo Kapatmak icin bu pencereyi kapatin.
rem Eski surum hala aciksa (onceki pencere kapatilmadiysa) kapatilir; yoksa tarayici eski programa baglanir
for /f "tokens=5" %%p in ('netstat -ano ^| findstr /r /c:":8000 .*LISTENING"') do (tasklist /fi "pid eq %%p" | findstr /i "python" >nul && taskkill /f /pid %%p >nul 2>nul)
start "" http://localhost:8000
rem Program ve ardindaki denetimler tek blokta: guncelleme bu dosyayi degistirse de bu pencere eski komutlarla biter
(
  ".venv\Scripts\python.exe" -m uvicorn app.main:app --host %ADRES% --port 8000
  rem Kur ya da Guncelle dugmesiyle program yeni pencerede yeniden acildiysa bu eski pencere sessizce kapanir
  if exist "yeniden-baslatiliyor.txt" (
    del "yeniden-baslatiliyor.txt" >nul 2>nul
    exit
  )
  rem Yeni surum hic acilamadan durduysa eski surum geri konur ve program yeniden acilir
  if exist "..\guncelleme-deneniyor.txt" (
    call :yaz "Yeni surum acilamadi; eski surume donuluyor..."
    ".venv\Scripts\python.exe" -I "app\guncelleme.py" geri >> "%GUNLUK%" 2>&1
    cd ..
    start "" cmd /c baslat.bat
    exit
  )
)
echo.
call :yaz "Program durdu. Yukarida hata yaziyorsa bu pencerenin fotografini gonderin."
pause
