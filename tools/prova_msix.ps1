# Prova del pacchetto MSIX sul proprio PC, PRIMA di inviarlo allo Store.
# Richiede: build.bat già eseguito (cartella dist\PdfPaper) e la "Modalità sviluppatore" di Windows
# (Impostazioni > Sistema > Per sviluppatori). Installa PdfPaper come farebbe lo Store, senza firma.
param([string]$Dist = "dist\PdfPaper")
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
if (-not (Test-Path "$Dist\PdfPaper.exe")) { throw "Non trovo $Dist\PdfPaper.exe: esegui prima build.bat" }
$root = "msix_prova"
Get-AppxPackage PdfPaper.Prova | Remove-AppxPackage -ErrorAction SilentlyContinue
if (Test-Path $root) { Remove-Item $root -Recurse -Force }
Copy-Item $Dist $root -Recurse
Copy-Item "msix\Assets" "$root\Assets" -Recurse
$ver = (Select-String version_info.txt -Pattern "ProductVersion', '([0-9.]+)'").Matches[0].Groups[1].Value
$xml = (Get-Content "msix\AppxManifest.xml" -Raw).Replace('__PUBLISHER_DISPLAY__', 'Giovanni Ciccarese')
$xml = $xml.Replace('__IDENTITY_NAME__', 'PdfPaper.Prova').Replace('__PUBLISHER__', 'CN=PdfPaperProva')
$xml = $xml.Replace('__VERSION__', $ver)
Set-Content "$root\AppxManifest.xml" $xml -Encoding UTF8
Add-AppxPackage -Register "$root\AppxManifest.xml"
Write-Host ""
Write-Host "PdfPaper $ver installato come pacchetto di prova: cercalo nel menu Start." -ForegroundColor Green
Write-Host "Prova: apertura di un PDF, OCR, salvataggio, colori omissis (vengono ricordati?), 'Apri con'."
Write-Host "Per rimuoverlo: Impostazioni > App, oppure  Get-AppxPackage PdfPaper.Prova | Remove-AppxPackage"
