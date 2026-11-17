@echo off
rem Installa PdfPaper come pacchetto MSIX di prova (serve la Modalita' sviluppatore di Windows)
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File tools\prova_msix.ps1
pause
