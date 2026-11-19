"""Operazioni sui PDF: salvataggio, omissis, pulizia dei dati nascosti, moduli, compressione, OCR."""
import io
import os

import pytest
from PIL import Image

import pdfpaper
from conftest import page_text, reopen

SECRET = "MARIOROSSI1980"
PUBLIC = "TESTOPUBBLICO"


def new_doc(fitz, text_lines=()):
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    for i, t in enumerate(text_lines):
        page.insert_text((72, 100 + 40 * i), t, fontsize=14, fontname="helv")
    return doc


def all_objects(doc):
    return "\n".join(doc.xref_object(x) for x in range(1, doc.xref_length()))


# ---------------------------------------------------------------- salvataggio
def test_salvataggio_conserva_testo_e_pagine(fitz):
    doc = new_doc(fitz, [PUBLIC])
    doc.new_page()
    data = pdfpaper.pdf_bytes(doc)
    with reopen(data) as again:
        assert len(again) == 2
        assert PUBLIC in again[0].get_text()


# ---------------------------------------------------------------- omissis
def secret_rect(page):
    hits = page.search_for(SECRET)
    assert hits, "testo di prova non trovato"
    return hits[0] + (-2, -2, 2, 2)


@pytest.mark.parametrize("label", [False, True])
def test_omissis_elimina_davvero_il_testo(fitz, label):
    doc = new_doc(fitz, [SECRET, PUBLIC])
    page = doc[0]
    pdfpaper.redact_area(page, secret_rect(page), (0, 0, 0), label, (1, 1, 1))
    data = pdfpaper.pdf_bytes(doc)
    text = page_text(data)
    assert SECRET not in text
    assert PUBLIC in text
    # il testo non deve restare nemmeno nei dati grezzi del file
    with reopen(data) as again:
        streams = b"".join(again.xref_stream(x) or b"" for x in range(1, again.xref_length()))
        assert SECRET.encode() not in streams
        assert SECRET not in all_objects(again)
        if label:
            assert "OMISSIS" in again[0].get_text()


def test_omissis_cancella_i_pixel_delle_immagini(fitz):
    doc = fitz.open()
    page = doc.new_page(width=400, height=400)
    buf = io.BytesIO()
    Image.new("RGB", (200, 200), (255, 0, 0)).save(buf, "PNG")
    page.insert_image(fitz.Rect(100, 100, 300, 300), stream=buf.getvalue())
    pdfpaper.redact_area(page, fitz.Rect(150, 150, 250, 250), (0, 0, 0))
    data = pdfpaper.pdf_bytes(doc)
    with reopen(data) as again:
        imgs = again[0].get_images(full=True)
        assert imgs, "l'immagine fuori dall'area deve restare"
        pix = fitz.Pixmap(again, imgs[0][0])
        if pix.n - pix.alpha != 3:
            pix = fitz.Pixmap(fitz.csRGB, pix)
        im = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        assert im.getpixel((pix.width // 2, pix.height // 2)) != (255, 0, 0)   # centro cancellato
        assert im.getpixel((2, 2)) == (255, 0, 0)                                 # bordo intatto


# ---------------------------------------------------------------- pulizia dei dati nascosti
ALL_OPTS = dict(meta=True, attachments=True, bookmarks=True, annots=True, links=True,
                fields=True, js=True, hidden=True)


def dirty_doc(fitz):
    doc = new_doc(fitz, [PUBLIC])
    doc.new_page()
    doc.set_metadata({"author": SECRET, "title": "Titolo riservato", "subject": "Oggetto",
                      "keywords": "chiave", "creator": "Programma", "producer": "Produttore"})
    doc.set_xml_metadata(f"<x:xmpmeta xmlns:x='adobe:ns:meta/'><autore>{SECRET}</autore></x:xmpmeta>")
    doc.embfile_add("allegato.txt", f"dati {SECRET}".encode())
    doc.set_toc([[1, "Capitolo", 1], [1, "Seconda", 2]])
    page = doc[0]
    page.add_text_annot((300, 300), f"nota {SECRET}")
    page.insert_link({"kind": fitz.LINK_URI, "from": fitz.Rect(72, 200, 200, 220),
                      "uri": "https://example.invalid/"})
    return doc


def test_inspect_hidden_trova_i_dati(fitz):
    info = pdfpaper.inspect_hidden(dirty_doc(fitz))
    assert info["meta"] >= 1
    assert info["attachments"] == 1
    assert info["bookmarks"] == 2
    assert info["annots"] >= 1
    assert info["links"] == 1


def test_pulizia_rimuove_metadati_e_dati_nascosti(fitz):
    doc = dirty_doc(fitz)
    pdfpaper.sanitize_document(doc, ALL_OPTS)
    data = pdfpaper.pdf_bytes(doc)
    with reopen(data) as again:
        info = pdfpaper.inspect_hidden(again)
        assert info["meta"] == 0
        assert info["attachments"] == 0
        assert info["bookmarks"] == 0
        assert info["annots"] == 0
        assert info["links"] == 0
        assert PUBLIC in again[0].get_text()           # il contenuto visibile resta
        assert SECRET not in all_objects(again)
        streams = b"".join(again.xref_stream(x) or b"" for x in range(1, again.xref_length()))
        assert SECRET.encode() not in streams


def test_pulizia_parziale_lascia_cio_che_non_e_scelto(fitz):
    doc = dirty_doc(fitz)
    opts = dict.fromkeys(ALL_OPTS, False)
    opts["meta"] = True
    pdfpaper.sanitize_document(doc, opts)
    info = pdfpaper.inspect_hidden(doc)
    assert info["meta"] == 0
    assert info["attachments"] == 1 and info["bookmarks"] == 2


# ---------------------------------------------------------------- moduli disegnati
def form_doc(fitz):
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((40, 113), "Cognome", fontsize=9, fontname="helv")
    page.draw_rect(fitz.Rect(100, 100, 300, 118), color=(0, 0, 0), width=0.6)
    page.insert_text((62, 162), "CAP", fontsize=9, fontname="helv")
    for i in range(5):
        page.draw_rect(fitz.Rect(100 + 14 * i, 150, 114 + 14 * i, 166), color=(0, 0, 0), width=0.6)
    return doc


def test_modulo_campi_riconosciuti(fitz):
    fields = pdfpaper.page_form_fields(form_doc(fitz)[0])
    kinds = sorted(f["kind"] for f in fields)
    assert kinds == ["comb", "text"], fields
    combf = next(f for f in fields if f["kind"] == "comb")
    assert len(combf["cells"]) == 5


def test_modulo_compilazione_scrive_nei_campi(fitz):
    doc = form_doc(fitz)
    page = doc[0]
    fields = pdfpaper.page_form_fields(page)
    text = next(f for f in fields if f["kind"] == "text")
    combf = next(f for f in fields if f["kind"] == "comb")
    pdfpaper.draw_form_value(page, text, "Bianchi")
    pdfpaper.draw_form_value(page, combf, "73100")
    data = pdfpaper.pdf_bytes(doc)
    with reopen(data) as again:
        p = again[0]
        assert "Bianchi" in p.get_textbox(fitz.Rect(text["rect"]))
        for i, ch in enumerate("73100"):
            assert p.get_textbox(fitz.Rect(combf["cells"][i]) + (-1, -1, 1, 1)).strip() == ch


# ---------------------------------------------------------------- compressione
def noop_report(*_):
    pass


def test_compressione_riduce_e_conserva_le_pagine(fitz):
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    im = Image.effect_noise((2400, 2400), 60).convert("RGB")
    buf = io.BytesIO()
    im.save(buf, "PNG")
    page.insert_image(fitz.Rect(50, 50, 545, 545), stream=buf.getvalue())
    page.insert_text((72, 700), PUBLIC, fontsize=14, fontname="helv")
    data = doc.tobytes()
    out = pdfpaper.compress_worker(data, 150, 60)(noop_report, lambda: False)
    assert len(out) < len(data)
    with reopen(out) as again:
        assert len(again) == 1
        assert PUBLIC in again[0].get_text()
        assert again[0].get_images()


def test_compressione_annullata(fitz):
    data = new_doc(fitz, [PUBLIC]).tobytes()
    with pytest.raises(pdfpaper.Cancelled):
        pdfpaper.compress_worker(data, 0, 60)(noop_report, lambda: True)


# ---------------------------------------------------------------- OCR
TESSDATA = os.environ.get("PDFPAPER_TESSDATA", "")


@pytest.mark.skipif(not os.path.isfile(os.path.join(TESSDATA, "ita.traineddata")),
                    reason="dati lingua OCR non presenti (variabile PDFPAPER_TESSDATA)")
def test_ocr_rende_ricercabile_una_scansione(fitz):
    src = new_doc(fitz)
    src[0].insert_text((72, 200), "VERIFICA RICONOSCIMENTO", fontsize=28, fontname="helv")
    pix = src[0].get_pixmap(dpi=200)
    scan = fitz.open()
    p = scan.new_page(width=595, height=842)
    p.insert_image(p.rect, pixmap=pix)
    data = scan.tobytes()
    assert page_text(data).strip() == ""          # solo immagine, nessun testo
    opts = dict(pages="", only_missing=False, dpi=200, lang="ita")
    out, done = pdfpaper.ocr_worker(data, opts, TESSDATA)(noop_report, lambda: False)
    assert done == 1
    text = page_text(out).upper()
    assert "VERIFICA" in text and "RICONOSCIMENTO" in text


# ---------------------------------------------------------------- unione di più file
def make_pdf(fitz, path, label, pages, password=None):
    doc = fitz.open()
    for i in range(pages):
        doc.new_page().insert_text((72, 100), f"{label} pagina {i + 1}", fontsize=14, fontname="helv")
    if password:
        doc.save(str(path), encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw="proprietario", user_pw=password)
    else:
        doc.save(str(path))
    return str(path)


def test_unione_in_ordine_con_riepilogo(fitz, tmp_path):
    a = make_pdf(fitz, tmp_path / "a.pdf", "PRIMO", 2)
    b = make_pdf(fitz, tmp_path / "b.pdf", "SECONDO", 1)
    c = make_pdf(fitz, tmp_path / "c.pdf", "TERZO", 3, password="segreta")
    d = make_pdf(fitz, tmp_path / "d.pdf", "QUARTO", 1, password="segreta")
    bad = tmp_path / "rotto.pdf"
    bad.write_bytes(b"questo non e' un pdf")
    files = [(b, None), (a, None), (c, "segreta"), (d, None), (str(bad), None)]
    out, info = pdfpaper.merge_worker(files)(noop_report, lambda: False)
    with reopen(out) as doc:
        assert len(doc) == 1 + 2 + 3
        texts = [p.get_text() for p in doc]
        assert "SECONDO pagina 1" in texts[0]
        assert "PRIMO pagina 1" in texts[1] and "PRIMO pagina 2" in texts[2]
        assert "TERZO pagina 3" in texts[5]
        assert doc.get_toc() == []                      # segnalibri disattivati per default
    assert [n for n, _ in info["merged"]] == ["b.pdf", "a.pdf", "c.pdf"]
    skipped = dict(info["skipped"])
    assert skipped["d.pdf"] == "protetto da password"
    assert "rotto.pdf" in skipped


def test_unione_con_segnalibri(fitz, tmp_path):
    a = make_pdf(fitz, tmp_path / "relazione.pdf", "A", 2)
    b = make_pdf(fitz, tmp_path / "allegato 1.pdf", "B", 1)
    out, _ = pdfpaper.merge_worker([(a, None), (b, None)], True)(noop_report, lambda: False)
    with reopen(out) as doc:
        assert doc.get_toc() == [[1, "relazione", 1], [1, "allegato 1", 3]]


def test_unione_senza_file_validi(fitz, tmp_path):
    bad = tmp_path / "rotto.pdf"
    bad.write_bytes(b"niente")
    with pytest.raises(ValueError):
        pdfpaper.merge_worker([(str(bad), None)])(noop_report, lambda: False)


def test_unione_annullata(fitz, tmp_path):
    a = make_pdf(fitz, tmp_path / "a.pdf", "A", 1)
    with pytest.raises(pdfpaper.Cancelled):
        pdfpaper.merge_worker([(a, None), (a, None)])(noop_report, lambda: True)
