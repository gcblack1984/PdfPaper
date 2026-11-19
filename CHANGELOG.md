# Novità / Changelog

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
