"""Funzioni di supporto senza file PDF: intervalli di pagine, dimensioni, caselle dei moduli."""
import os

import pytest

import pdfpaper


# ---------------------------------------------------------------- intervalli di pagine
@pytest.mark.parametrize("text, n, expected", [
    ("1", 5, [0]),
    ("1-3", 5, [0, 1, 2]),
    ("1-3,5", 5, [0, 1, 2, 4]),
    ("4-", 6, [3, 4, 5]),
    ("-2", 6, [0, 1]),
    (" 2 , 2, 1 ", 3, [0, 1]),
])
def test_parse_ranges_validi(text, n, expected):
    assert pdfpaper.parse_ranges(text, n) == expected


@pytest.mark.parametrize("text", ["0", "6", "3-2", "", ",", "a", "1-9"])
def test_parse_ranges_non_validi(text):
    with pytest.raises(ValueError):
        pdfpaper.parse_ranges(text, 5)


def test_human_size():
    assert pdfpaper.human_size(512) == "512 B"
    assert pdfpaper.human_size(2048) == "2.0 KB"
    assert pdfpaper.human_size(5 * 1024 * 1024) == "5.0 MB"


# ---------------------------------------------------------------- caselle a carattere singolo
def comb(n, fixed=None):
    cells = [(10 + 12 * i, 10, 22 + 12 * i, 24) for i in range(n)]
    return dict(kind="comb", rect=(cells[0][0], 10, cells[-1][2], 24), cells=cells, fixed=fixed or {})


def test_comb_codice_fiscale():
    out = pdfpaper.comb_layout(comb(16), "rssmra80a01h501u")
    assert "".join(out[i] for i in range(16)) == "RSSMRA80A01H501U"


def test_comb_testo_corto_a_sinistra():
    out = pdfpaper.comb_layout(comb(10), "abc")
    assert out == {0: "A", 1: "B", 2: "C"}


def test_comb_testo_troppo_lungo_viene_troncato():
    out = pdfpaper.comb_layout(comb(3), "abcdef")
    assert out == {0: "A", 1: "B", 2: "C"}


def test_comb_data_con_barre_gia_stampate():
    f = comb(10, {2: "/", 5: "/"})
    for value in ("17/11/2026", "17112026"):
        out = pdfpaper.comb_layout(f, value)
        assert 2 not in out and 5 not in out
        assert "".join(out[i] for i in sorted(out)) == "17112026"


def test_comb_pod_con_lettere_fisse():
    f = comb(14, {0: "I", 1: "T", 5: "E"})
    out = pdfpaper.comb_layout(f, "IT001E12345678")
    assert set(out) & {0, 1, 5} == set()
    assert "".join(out[i] for i in sorted(out)) == "00112345678"


def test_comb_numero_con_virgola():
    f = comb(6, {3: ","})
    out = pdfpaper.comb_layout(f, "6,5")
    assert out == {2: "6", 4: "5"}


# ---------------------------------------------------------------- riconoscimento dei campi
def rect(x0, y0, x1, y1):
    return ("rect", x0, y0, x1, y1, False, True)


def test_detect_fields_riquadro_e_caselle():
    prims = [rect(100, 100, 300, 118)]                              # campo di testo
    prims += [rect(100 + 14 * i, 150, 114 + 14 * i, 166) for i in range(5)]  # 5 caselle
    words = [(40, 104, 90, 114, "Cognome"), (40, 153, 90, 163, "CAP")]
    fields = pdfpaper.detect_fields(prims, words, [])
    kinds = sorted(f["kind"] for f in fields)
    assert kinds == ["comb", "text"]
    text = next(f for f in fields if f["kind"] == "text")
    combf = next(f for f in fields if f["kind"] == "comb")
    assert text["label"] == "Cognome"
    assert len(combf["cells"]) == 5 and combf["label"] == "CAP"


def test_detect_fields_ignora_riquadro_con_testo_stampato():
    prims = [rect(100, 100, 300, 118)]
    words = [(110, 104, 200, 114, "Intestazione")]
    assert pdfpaper.detect_fields(prims, words, []) == []


def test_detect_fields_casella_di_spunta():
    words = [(115, 101, 150, 109, "Privato")]
    fields = pdfpaper.detect_fields([], words, [(100, 100, 109, 110)])
    assert len(fields) == 1 and fields[0]["kind"] == "check" and fields[0]["label"] == "Privato"


# ---------------------------------------------------------------- ordine dei file da unire
def test_ordine_naturale():
    names = ["file10.pdf", "File2.pdf", "file1.pdf", "allegato.pdf", "file2b.pdf"]
    assert sorted(names, key=pdfpaper.natural_key) == [
        "allegato.pdf", "file1.pdf", "File2.pdf", "file2b.pdf", "file10.pdf"]


def test_elenco_pdf_della_cartella(tmp_path):
    for name in ("b10.pdf", "b2.pdf", "a.PDF", "nota.txt"):
        (tmp_path / name).write_bytes(b"x")
    sub = tmp_path / "sotto"
    sub.mkdir()
    (sub / "c.pdf").write_bytes(b"x")
    (tmp_path / "cartella.pdf").mkdir()  # una cartella con nome .pdf non è un file
    names = [p.replace(str(tmp_path), "").lstrip("\\/") for p in pdfpaper.list_pdfs(str(tmp_path))]
    assert names == ["a.PDF", "b2.pdf", "b10.pdf"]
    deep = [os.path.basename(p) for p in pdfpaper.list_pdfs(str(tmp_path), recursive=True)]
    assert deep == ["a.PDF", "b2.pdf", "b10.pdf", "c.pdf"]
