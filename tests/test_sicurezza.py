"""Verifiche statiche sul codice sorgente: nessuna comunicazione di rete, nessuna esecuzione di comandi."""
import ast
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(ROOT, "pdfpaper.py")

# librerie che permettono di comunicare in rete o di aprire pagine web
NETWORK = {"socket", "ssl", "http", "urllib", "urllib3", "requests", "httpx", "aiohttp", "ftplib",
           "smtplib", "poplib", "imaplib", "telnetlib", "xmlrpc", "websocket", "websockets",
           "webbrowser", "asyncio", "socketserver", "paramiko"}
# librerie o funzioni che eseguono altri programmi o codice arbitrario
EXEC_MODULES = {"subprocess", "pty", "pickle", "marshal", "shelve"}
# ctypes è ammesso solo per queste due impostazioni di Windows (nitidezza su schermi ad alta
# risoluzione e icona nella barra delle applicazioni)
CTYPES_ALLOWED = {"ctypes.windll.shcore.SetProcessDpiAwareness",
                  "ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID"}
EXEC_CALLS = {"eval", "exec", "compile", "__import__"}
OS_CALLS = {"system", "popen", "startfile", "execv", "execl", "spawnv", "spawnl"}


def tree():
    with open(SOURCE, encoding="utf-8") as fh:
        return ast.parse(fh.read(), SOURCE)


def imported_modules():
    mods = set()
    for node in ast.walk(tree()):
        if isinstance(node, ast.Import):
            mods.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module.split(".")[0])
    return mods


def test_nessuna_libreria_di_rete():
    found = imported_modules() & NETWORK
    assert not found, f"librerie di rete nel codice: {sorted(found)}"


def test_nessuna_esecuzione_di_programmi_esterni():
    found = imported_modules() & EXEC_MODULES
    assert not found, f"librerie per eseguire programmi o codice: {sorted(found)}"
    bad = []
    for node in ast.walk(tree()):
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Name) and f.id in EXEC_CALLS:
                bad.append(f"{f.id} (riga {node.lineno})")
            elif (isinstance(f, ast.Attribute) and f.attr in OS_CALLS
                  and isinstance(f.value, ast.Name) and f.value.id == "os"):
                bad.append(f"os.{f.attr} (riga {node.lineno})")
    assert not bad, f"chiamate non ammesse: {bad}"


def dotted(node):
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def test_ctypes_solo_per_impostazioni_di_windows():
    uses = set()
    for node in ast.walk(tree()):
        if isinstance(node, ast.Call):
            name = dotted(node.func)
            if name and name.startswith("ctypes"):
                uses.add(name)
    assert uses <= CTYPES_ALLOWED, f"uso di ctypes non previsto: {sorted(uses - CTYPES_ALLOWED)}"
    # ctypes non deve essere usato in altri modi (passato a funzioni, assegnato, ecc.)
    refs = sum(1 for n in ast.walk(tree()) if isinstance(n, ast.Name) and n.id == "ctypes")
    assert refs == len(uses), "ctypes usato fuori dalle chiamate ammesse"


def test_dipendenze_dichiarate():
    """Solo le librerie dichiarate: PyMuPDF, Pillow, tkinterdnd2 e la libreria standard di Python."""
    import sys
    allowed = {"pymupdf", "fitz", "PIL", "tkinterdnd2"} | set(sys.stdlib_module_names)
    extra = imported_modules() - allowed
    assert not extra, f"librerie non dichiarate: {sorted(extra)}"
