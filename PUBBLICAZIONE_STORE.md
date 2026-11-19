# Pubblicare PdfPaper su Microsoft Store: passi da seguire

Tempo indicativo: un'ora la prima volta, poi l'esame di Microsoft (di solito pochi giorni lavorativi).
Microsoft firma il pacchetto al momento della pubblicazione: non serve comprare un certificato.

## 1. Account sviluppatore (gratuito)

1. Vai su **storedeveloper.microsoft.com** e scegli **Individual developer** (sviluppatore individuale).
2. Accedi con il tuo account Microsoft personale e completa la verifica d'identità.
3. Alla fine entri in **Partner Center**.

## 2. Riserva il nome

1. Partner Center > **App e giochi** > **Nuovo prodotto** > **App MSIX o PWA**.
2. Scrivi **PdfPaper** e controlla che sia disponibile. Se è già preso, prova **PdfPaper - Editor PDF**.
3. Conferma con **Riserva nome prodotto**.

## 3. Copia l'identità del pacchetto su GitHub

1. Nella pagina del prodotto: **Gestione prodotti** > **Identità prodotto**. Trovi tre valori:
   - `Package/Identity/Name` (es. `12345GiovanniCiccarese.PdfPaper`)
   - `Package/Identity/Publisher` (es. `CN=1A2B3C4D-5E6F-...`)
   - `Package/Properties/PublisherDisplayName` (es. `Giovanni Ciccarese`)
2. Su GitHub, nel repository: **Settings** > **Secrets and variables** > **Actions** > scheda **Variables**
   > **New repository variable**, e crea queste tre variabili, copiando i valori esattamente:

| Nome variabile | Valore |
|---|---|
| `MSIX_IDENTITY_NAME` | Package/Identity/Name |
| `MSIX_PUBLISHER` | Package/Identity/Publisher |
| `MSIX_PUBLISHER_DISPLAY_NAME` | Package/Properties/PublisherDisplayName |

## 4. Crea il pacchetto MSIX

1. Su GitHub: **Actions** > **Build PdfPaper** > **Run workflow** > **Run workflow** (ramo `main`).
2. Alla fine (spunta verde) apri l'esecuzione e scarica l'artefatto **PdfPaper-msix**.
3. Estrai lo zip: dentro c'è `PdfPaper-1.1.0.0-x64.msix`. È il file da caricare sullo Store.

**Prova facoltativa ma consigliata, prima di inviarlo.** Sul tuo PC attiva la Modalità sviluppatore
(Impostazioni > Sistema > Per sviluppatori), esegui `build.bat` e poi `prova_msix.bat`. PdfPaper viene
installato come lo installerebbe lo Store: controlla che si apra, che l'OCR funzioni, che i colori
dell'omissis vengano ricordati e che compaia in "Apri con" sui PDF.

## 5. Compila e invia la richiesta

Nella pagina del prodotto: **Avvia l'invio** (Start your submission). Le sezioni sono:

1. **Prezzi e disponibilità**: Gratuito, tutti i mercati, visibilità pubblica.
2. **Proprietà**: categoria Produttività, URL della privacy policy, sito web e contatto di assistenza
   (li trovi in `msix/SCHEDA_STORE.md`).
3. **Classificazioni per età**: compila il questionario con le risposte indicate nella scheda.
4. **Pacchetti**: trascina il file `.msix`. Partner Center controlla che l'identità coincida: se dà
   errore, ricontrolla le tre variabili del punto 3 e rifai il punto 4.
5. **Inserzioni nello Store**: aggiungi Italiano (e Inglese, se vuoi) e incolla testi, caratteristiche,
   termini di ricerca e copyright da `msix/SCHEDA_STORE.md`. Carica gli screenshot e i loghi di
   `msix/store/`.
6. **Opzioni di invio**: incolla le **note per la certificazione** e la **motivazione di runFullTrust**
   dalla scheda.
7. Premi **Invia allo Store**.

## 6. Dopo la pubblicazione

PdfPaper è pubblicato: https://apps.microsoft.com/detail/9MXW1DCLHC45


- Ricevi un'e-mail quando l'app supera l'esame. Copia il link della pagina dello Store e mandamelo:
  lo aggiungo al README e alla guida.
- Se l'app viene respinta, l'e-mail spiega il motivo: inoltramela e la sistemiamo.

## 7. Aggiornamenti futuri

1. Aumenta il numero di versione (ci penso io): `pdfpaper.py` e `version_info.txt`.
2. Carica i file su GitHub e crea la release con il tag corrispondente (es. `v1.2.0`).
3. Scarica l'artefatto **PdfPaper-msix** dall'esecuzione di Actions.
4. Partner Center > prodotto > **Aggiorna** > **Pacchetti**: carica il nuovo `.msix`, scrivi le novità
   in "Novità di questa versione" e invia.

Lo Store accetta solo versioni più alte della precedente. Gli utenti ricevono l'aggiornamento in
automatico.
