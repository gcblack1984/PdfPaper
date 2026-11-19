# Novità / Changelog

## 1.3.1 (novembre 2026)

- La schermata di avvio elenca anche le nuove funzioni (Unisci PDF, compilazione moduli, pulizia dei dati,
  apertura trascinando i file).
- Rapporto delle verifiche automatiche: la versione è indicata nella forma breve (1.3.1).

## 1.3.0 (novembre 2026)

- **Trascinamento dei file**: con PdfPaper aperto si può trascinare un PDF da Esplora file dentro la finestra
  per aprirlo, senza passare da File → Apri. Se il documento aperto ha modifiche non salvate, il programma
  chiede prima se salvarle.
- **Unisci PDF** (pulsante nel gruppo Documento e menu File): unisce più PDF in un documento nuovo.
  Si possono scegliere più file insieme o aggiungere tutti i PDF di una cartella (anche delle sottocartelle),
  sistemare l'ordine (Su/Giù, Ordina per nome con ordine naturale: "allegato 2" prima di "allegato 10") e,
  a scelta, aggiungere un segnalibro per ogni file. Per i file protetti viene chiesta la password; quelli
  illeggibili vengono saltati e indicati nel riepilogo. Trascinando più PDF o una cartella nella finestra si
  apre Unisci PDF con i file già in elenco.
- **Testo da posizionare**: il testo aggiunto, modificato o incollato compare prima in un riquadro
  tratteggiato spostabile, con il suo carattere vero. Si allinea trascinandolo con il mouse o con le frecce
  (Maiusc: passi di 10 punti) e si conferma con Invio o un clic; Esc lo annulla. Nella modifica il testo
  originale appare già coperto e resta intatto se si annulla.
- Verifiche automatiche a ogni versione (test delle funzioni, analisi di sicurezza del codice con Bandit,
  vulnerabilità note delle librerie con pip-audit), con rapporto scaricabile da GitHub.

## 1.2.0 (novembre 2026)

- Nuovo strumento **Compila modulo**: riconosce da solo gli spazi dei moduli PDF "disegnati" (per esempio
  quelli creati con Word), anche quando non hanno campi compilabili:
  - **riquadri di testo**: il testo viene centrato in altezza e ridotto se è troppo lungo;
  - **caselle a carattere singolo** (codice fiscale, CAP, POD, date, importi): ogni carattere va nella sua
    casella, saltando quelle già stampate (es. "IT" ed "E" del POD, le barre della data); nei numeri con
    virgola gli interi si allineano prima della virgola e i decimali dopo;
  - **caselle di spunta** (☐): si segnano e si tolgono con un clic.
- Si scrive direttamente sopra il campo; Tab passa al campo successivo, Invio conferma, Esc annulla.
  Un campo si può correggere o svuotare in qualsiasi momento senza lasciare tracce; Ctrl+Z annulla.
- Con il tasto destro su un campo: Scrivi / Svuota. Nel menu Modifica: "Svuota i campi compilati della pagina".
- Nuova funzione **Pulisci** (Strumenti → Rimuovi metadati e dati nascosti): elimina dal file metadati
  (autore, titolo, programma, date, XMP), commenti e annotazioni, allegati, segnalibri, collegamenti e
  JavaScript; a scelta svuota i campi compilabili e toglie il testo invisibile. Mostra prima quanti dati
  di ogni tipo sono presenti. Consigliata prima di inviare un documento omissato.

## 1.1.0 (novembre 2026)

- Nuovo strumento **Seleziona testo**: si seleziona il testo trascinando sulla pagina, con evidenziazione.
- **Appunti**: Copia (Ctrl+C), Taglia (Ctrl+X), Incolla (Ctrl+V) di testo e immagini
  (screenshot, immagini copiate, file immagine copiati da Esplora risorse), Seleziona tutto (Ctrl+A),
  Elimina testo selezionato (Canc).
- **Menu del tasto destro** sulla pagina: appunti, modifica e omissis del testo selezionato,
  aggiungi testo o immagine nel punto cliccato, rotazioni, inserisci/elimina pagina.
- **Rotazione** di 90° a destra, 90° a sinistra e 180° con pulsanti dedicati, menu e scorciatoie
  (Ctrl+R, Ctrl+Maiusc+R).
- **Barra dei pulsanti** riorganizzata su tre righe a gruppi (File, Pagina, Zoom, Ruota pagina,
  Strumenti sulla pagina, Appunti, Pagine, Documento), con suggerimenti al passaggio del mouse.
- **Stile automatico del testo**: aggiungendo, modificando o incollando testo, PdfPaper propone lo stesso
  carattere, dimensione e colore del documento. Nei PDF digitali legge il carattere vero e usa il font di
  Windows corrispondente (Arial, Times New Roman, Calibri, Verdana…); nelle scansioni lo stima
  dall'immagine (dimensione, grassetto, carattere con o senza grazie, colore). Se si sceglie un altro
  carattere, viene ricordato per tutto il documento.
- **Omissis a colori**: si possono scegliere il colore di sfondo e quello della scritta (ricordati tra
  una sessione e l'altra).
- OCR e compressione girano in un processo separato: **barra di avanzamento** sempre aggiornata e
  annullamento immediato.
- **Menu del tasto destro** (Taglia, Copia, Incolla, Seleziona tutto, Annulla) nelle caselle di testo.
- Nuovo zoom **Pagina intera**.
- Testo e immagini inseriti su pagine ruotate restano dritti.

## 1.0.0 (novembre 2026)

- Prima versione: OCR, aggiunta e modifica testo, immagini, gestione pagine, compressione, omissis.
