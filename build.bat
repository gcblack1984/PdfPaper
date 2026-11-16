@echo off
setlocal
title PdfPaper - creazione versione portabile
cd /d "%~dp0"

echo ==========================================================
echo  PdfPaper - creazione cartella portabile (dist\PdfPaper)
echo ==========================================================

where py >nul 2>nul && (set "PY=py -3") || (set "PY=python")
%PY% --version || (echo Python non trovato. Installa Python 3.10+ da python.org & pause & exit /b 1)

if not exist .venv (
    echo [1/5] Creo ambiente virtuale...
    %PY% -m venv .venv || goto :err
)
call .venv\Scripts\activate.bat

echo [2/5] Installo le librerie...
python -m pip install --upgrade pip >nul
python -m pip install -r requirements.txt || goto :err

echo [3/5] Creo l'eseguibile...
pyinstaller --noconfirm --clean --onedir --windowed ^
  --name PdfPaper ^
  --icon assets\pdf_icon.ico ^
  --add-data "assets;assets" ^
  --contents-directory lib ^
  --version-file version_info.txt ^
  --exclude-module matplotlib --exclude-module numpy --exclude-module pandas ^
  pdfpaper.py || goto :err

echo [4/5] Dati lingua OCR (tessdata)...
set "TD=dist\PdfPaper\tessdata"
if not exist "%TD%" mkdir "%TD%"
if exist tessdata (
    xcopy /E /I /Y tessdata "%TD%" >nul
) else (
    for %%L in (ita eng) do (
        echo   scarico %%L.traineddata ...
        powershell -NoProfile -Command "Invoke-WebRequest -UseBasicParsing 'https://github.com/tesseract-ocr/tessdata_fast/raw/main/%%L.traineddata' -OutFile '%TD%\%%L.traineddata'" || echo   ATTENZIONE: download di %%L non riuscito
    )
)

echo [5/5] Licenze e documentazione...
python tools\collect_licenses.py dist\PdfPaper\licenze
if exist LICENSE copy /Y LICENSE dist\PdfPaper\ >nul
copy /Y THIRD_PARTY_NOTICES.md dist\PdfPaper\ >nul
copy /Y LEGGIMI.txt dist\PdfPaper\ >nul
copy /Y CHANGELOG.md dist\PdfPaper\ >nul
copy /Y docs\Guida_PdfPaper.pdf dist\PdfPaper\ >nul

echo.
echo  FATTO!  La cartella portabile e': dist\PdfPaper
echo  Avvia dist\PdfPaper\PdfPaper.exe  (copiabile su chiavetta o altro PC)
echo.
pause
exit /b 0

:err
echo.
echo  ERRORE durante la creazione. Controlla i messaggi sopra.
pause
exit /b 1
