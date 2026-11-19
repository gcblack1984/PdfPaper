"""Impostazioni comuni dei test di PdfPaper.

I test girano senza rete: ogni tentativo di aprire una connessione fa fallire il test.
"""
import os
import socket
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

try:
    import pymupdf
except ImportError:  # versioni vecchie di PyMuPDF
    import fitz as pymupdf

import pdfpaper  # noqa: E402

# nel programma il motore PDF viene caricato durante lo splash
pdfpaper.fitz = pymupdf


class NetworkBlocked(RuntimeError):
    pass


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Durante i test qualsiasi connessione di rete è vietata."""
    def blocked(*args, **kwargs):
        raise NetworkBlocked("tentativo di connessione di rete durante i test")
    monkeypatch.setattr(socket, "socket", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket, "getaddrinfo", blocked)


@pytest.fixture
def fitz():
    return pymupdf


def reopen(data):
    return pymupdf.open("pdf", data)


def page_text(data, pno=0):
    with reopen(data) as doc:
        return doc[pno].get_text("text")
