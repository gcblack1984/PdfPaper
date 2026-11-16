@echo off
rem Avvio rapido senza creare l'exe (richiede di aver eseguito build.bat almeno una volta)
cd /d "%~dp0"
if exist .venv\Scripts\pythonw.exe (
    start "" .venv\Scripts\pythonw.exe pdfpaper.py %*
) else (
    echo Esegui prima build.bat per installare le librerie.
    pause
)
