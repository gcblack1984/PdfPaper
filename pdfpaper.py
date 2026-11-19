# -*- coding: utf-8 -*-
"""
PdfPaper - editor PDF portabile
  * OCR (PDF ricercabile) con motore Tesseract integrato in PyMuPDF
  * aggiunta / modifica testo, inserimento immagini
  * inserimento / eliminazione / rotazione pagine in un punto qualsiasi
  * compressione
  * omissis (redazione reale: il contenuto sotto l'area viene rimosso)

Dipendenze: PyMuPDF, Pillow (Tkinter incluso in Python per Windows).
"""
import io
import os
import queue
import re
import sys
import threading
import time
import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox, simpledialog, ttk

APP_NAME = "PdfPaper"
APP_VERSION = "1.2.0"
REPO_URL = "https://github.com/gcblack1984/PdfPaper"
APP_AUTHOR = "Creato da Giovanni CICCARESE"
APP_TITLE = f"{APP_NAME} - {APP_AUTHOR}"
SPLASH_MIN_SECONDS = 3.0
MAX_UNDO = 20

fitz = None  # caricato durante lo splash


# ----------------------------------------------------------------------------
# Percorsi (funziona sia da sorgente sia come exe PyInstaller --onedir)
# ----------------------------------------------------------------------------
def app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def resource(*parts):
    root = getattr(sys, "_MEIPASS", app_dir())
    return os.path.join(root, *parts)


def tessdata_dir():
    """Cartella 'tessdata' accanto all'exe (si possono aggiungere lingue)."""
    for cand in (os.path.join(app_dir(), "tessdata"), resource("tessdata"),
                 os.environ.get("TESSDATA_PREFIX", "")):
        if cand and os.path.isdir(cand) and any(
                f.endswith(".traineddata") for f in os.listdir(cand)):
            return cand
    return None


def _settings_paths():
    yield os.path.join(app_dir(), "pdfpaper_impostazioni.json")
    base = os.environ.get("APPDATA")
    if base:
        yield os.path.join(base, "PdfPaper", "impostazioni.json")


def load_settings():
    import json
    for path in _settings_paths():
        try:
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            continue
    return {}


def save_settings(data):
    """Salva accanto al programma; se la cartella non è scrivibile, nel profilo dell'utente."""
    import json
    for path in _settings_paths():
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
            return True
        except OSError:
            continue
    return False


def rgb_hex(c):
    return "#%02x%02x%02x" % tuple(int(round(v * 255)) for v in c)


def human_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def parse_ranges(text, n_pages):
    """'1-3,5,8-' -> [0,1,2,4,7,...] (indici 0-based, ordinati, unici)."""
    result = set()
    for part in text.replace(" ", "").split(","):
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            a = int(a) if a else 1
            b = int(b) if b else n_pages
        else:
            a = b = int(part)
        if a < 1 or b > n_pages or a > b:
            raise ValueError(f"Intervallo non valido: {part}")
        result.update(range(a - 1, b))
    if not result:
        raise ValueError("Nessuna pagina indicata")
    return sorted(result)


# ----------------------------------------------------------------------------
# Splash screen
# ----------------------------------------------------------------------------
class Splash(tk.Toplevel):
    BG = "#1f2430"

    def __init__(self, master, steps, on_finish):
        super().__init__(master)
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.configure(bg=self.BG, highlightthickness=1, highlightbackground="#3a4152")
        try:
            self._logo = tk.PhotoImage(file=resource("assets", "pdf_icon_128.png"))
            tk.Label(self, image=self._logo, bg=self.BG).pack(pady=(26, 6))
        except tk.TclError:
            tk.Label(self, text="PDF", fg="white", bg="#d32f2f",
                     font=("Segoe UI", 28, "bold"), padx=20).pack(pady=(40, 10))
        tk.Label(self, text=APP_NAME, fg="white", bg=self.BG,
                 font=("Segoe UI", 22, "bold")).pack()
        tk.Label(self, text="OCR · Modifica · Pagine · Compressione · Omissis",
                 fg="#aab2c5", bg=self.BG, font=("Segoe UI", 9)).pack(pady=(0, 16))

        self.bar = ttk.Progressbar(self, style="Splash.Horizontal.TProgressbar",
                                   length=400, mode="determinate", maximum=100)
        self.bar.pack()
        self.status = tk.Label(self, text="Avvio...", fg="#d0d5e0", bg=self.BG,
                               font=("Segoe UI", 9))
        self.status.pack(pady=(6, 0))
        tk.Label(self, text=APP_AUTHOR, fg="#ffffff", bg=self.BG,
                 font=("Segoe UI", 10, "italic")).pack(pady=(16, 0))
        tk.Label(self, text=f"versione {APP_VERSION}", fg="#6d7590", bg=self.BG,
                 font=("Segoe UI", 8)).pack(pady=(2, 10))

        # dimensione calcolata sul contenuto (corretta anche con zoom 125-150%)
        self.update_idletasks()
        w = max(480, self.winfo_reqwidth() + 60)
        h = self.winfo_reqheight()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")

        self.steps = steps
        self.on_finish = on_finish
        self.step_i = 0
        self.t0 = time.monotonic()
        self.value = 0.0
        self.after(150, self._run_step)
        self._tick()

    def _run_step(self):
        if self.step_i >= len(self.steps):
            return
        label, fn = self.steps[self.step_i]
        self.status.config(text=label)
        self.update_idletasks()
        try:
            fn()
        except Exception as exc:  # errore fatale in avvio
            self.destroy()
            messagebox.showerror(APP_NAME, f"Errore durante l'avvio:\n\n{exc}")
            self.master.destroy()
            return
        self.step_i += 1
        self.after(80, self._run_step)

    def _tick(self):
        if not self.winfo_exists():
            return
        elapsed = time.monotonic() - self.t0
        target = min(100.0 * self.step_i / len(self.steps),
                     100.0 * elapsed / SPLASH_MIN_SECONDS)
        self.value += (target - self.value) * 0.25 + (0.3 if target > self.value else 0)
        self.value = min(self.value, target)
        self.bar["value"] = self.value
        if self.step_i >= len(self.steps) and self.value >= 99.5:
            self.status.config(text="Pronto")
            self.after(250, self._finish)
            return
        self.after(30, self._tick)

    def _finish(self):
        self.destroy()
        self.on_finish()


# ----------------------------------------------------------------------------
# Finestre di dialogo
# ----------------------------------------------------------------------------
def attach_edit_menu(widget):
    """Menu del tasto destro (Taglia/Copia/Incolla/...) e Ctrl+A per caselle di testo e campi."""
    is_text = isinstance(widget, tk.Text)

    def has_sel():
        try:
            return bool(widget.tag_ranges("sel")) if is_text else widget.selection_present()
        except tk.TclError:
            return False

    def has_clip():
        try:
            return bool(widget.clipboard_get())
        except tk.TclError:
            return False

    def select_all(_e=None):
        if is_text:
            widget.tag_add("sel", "1.0", "end-1c")
            widget.mark_set("insert", "end-1c")
        else:
            widget.select_range(0, "end")
            widget.icursor("end")
        return "break"

    def popup(e):
        widget.focus_set()
        sel = "normal" if has_sel() else "disabled"
        m = tk.Menu(widget, tearoff=False)
        if is_text:
            m.add_command(label="Annulla", accelerator="Ctrl+Z", command=lambda: widget.event_generate("<<Undo>>"))
            m.add_command(label="Ripeti", accelerator="Ctrl+Y", command=lambda: widget.event_generate("<<Redo>>"))
            m.add_separator()
        m.add_command(label="✂  Taglia", accelerator="Ctrl+X", state=sel,
                      command=lambda: widget.event_generate("<<Cut>>"))
        m.add_command(label="❐  Copia", accelerator="Ctrl+C", state=sel,
                      command=lambda: widget.event_generate("<<Copy>>"))
        m.add_command(label="📋  Incolla", accelerator="Ctrl+V", state="normal" if has_clip() else "disabled",
                      command=lambda: widget.event_generate("<<Paste>>"))
        m.add_command(label="Elimina", accelerator="Canc", state=sel,
                      command=lambda: widget.event_generate("<<Clear>>"))
        m.add_separator()
        m.add_command(label="Seleziona tutto", accelerator="Ctrl+A", command=select_all)
        try:
            m.tk_popup(e.x_root, e.y_root)
        finally:
            m.grab_release()
        return "break"

    widget.bind("<Button-3>", popup, add="+")
    widget.bind("<Control-a>", select_all, add="+")
    widget.bind("<Control-A>", select_all, add="+")
    if is_text:
        widget.bind("<Control-y>", lambda e: (widget.event_generate("<<Redo>>"), "break")[1], add="+")


class BaseDialog(tk.Toplevel):
    def __init__(self, master, title):
        super().__init__(master)
        self.title(title)
        self.transient(master)
        self.resizable(False, False)
        self.result = None
        self.body = ttk.Frame(self, padding=12)
        self.body.pack(fill="both", expand=True)

    def buttons(self, ok_text="OK"):
        bar = ttk.Frame(self, padding=(12, 0, 12, 12))
        bar.pack(fill="x")
        ttk.Button(bar, text="Annulla", command=self.destroy).pack(side="right")
        ttk.Button(bar, text=ok_text, command=self._ok).pack(side="right", padx=6)
        self.bind("<Escape>", lambda e: self.destroy())

    def show(self):
        self.update_idletasks()
        m = self.master
        x = m.winfo_rootx() + (m.winfo_width() - self.winfo_width()) // 2
        y = m.winfo_rooty() + (m.winfo_height() - self.winfo_height()) // 3
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        self.grab_set()
        self.wait_window()
        return self.result

    def _ok(self):
        raise NotImplementedError


# ----------------------------------------------------------------------------
# Caratteri: corrispondenza con i font del documento e con quelli di Windows
# ----------------------------------------------------------------------------
class FontChoice:
    """Carattere da usare per scrivere: un font di Windows (file .ttf) o uno dei 14 font standard PDF."""

    def __init__(self, label, fontname, fontfile=None):
        self.label, self.fontname, self.fontfile = label, fontname, fontfile

    def __repr__(self):
        return f"FontChoice({self.label!r})"


BASE14 = {  # famiglia -> (normale, grassetto, corsivo, grassetto corsivo)
    "helvetica": ("helv", "hebo", "heit", "hebi"),
    "times": ("tiro", "tibo", "tiit", "tibi"),
    "courier": ("cour", "cobo", "coit", "cobi"),
}
STYLE_NAMES = ("", " grassetto", " corsivo", " grassetto corsivo")

# famiglia -> (nome mostrato, file regular/bold/italic/bolditalic in C:\Windows\Fonts, famiglia standard simile)
WIN_FONTS = {
    "arial": ("Arial", ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf"), "helvetica"),
    "times": ("Times New Roman", ("times.ttf", "timesbd.ttf", "timesi.ttf", "timesbi.ttf"), "times"),
    "courier": ("Courier New", ("cour.ttf", "courbd.ttf", "couri.ttf", "courbi.ttf"), "courier"),
    "calibri": ("Calibri", ("calibri.ttf", "calibrib.ttf", "calibrii.ttf", "calibriz.ttf"), "helvetica"),
    "verdana": ("Verdana", ("verdana.ttf", "verdanab.ttf", "verdanai.ttf", "verdanaz.ttf"), "helvetica"),
    "tahoma": ("Tahoma", ("tahoma.ttf", "tahomabd.ttf", None, None), "helvetica"),
    "segoeui": ("Segoe UI", ("segoeui.ttf", "segoeuib.ttf", "segoeuii.ttf", "segoeuiz.ttf"), "helvetica"),
    "trebuchet": ("Trebuchet MS", ("trebuc.ttf", "trebucbd.ttf", "trebucit.ttf", "trebucbi.ttf"), "helvetica"),
    "centurygothic": ("Century Gothic", ("GOTHIC.TTF", "GOTHICB.TTF", "GOTHICI.TTF", "GOTHICBI.TTF"), "helvetica"),
    "georgia": ("Georgia", ("georgia.ttf", "georgiab.ttf", "georgiai.ttf", "georgiaz.ttf"), "times"),
    "garamond": ("Garamond", ("GARA.TTF", "GARABD.TTF", "GARAIT.TTF", None), "times"),
    "bookantiqua": ("Book Antiqua", ("BKANT.TTF", "ANTQUAB.TTF", "ANTQUAI.TTF", "ANTQUABI.TTF"), "times"),
    "comicsans": ("Comic Sans MS", ("comic.ttf", "comicbd.ttf", "comici.ttf", "comicz.ttf"), "helvetica"),
}
FONT_ALIASES = {  # nomi come compaiono nei PDF (senza spazi, minuscoli) -> famiglia
    "arial": "arial", "arialmt": "arial", "helvetica": "arial", "helv": "arial", "arimo": "arial",
    "liberationsans": "arial", "nimbussans": "arial", "arialnarrow": "arial",
    "times": "times", "timesnewroman": "times", "timesnewromanps": "times", "timesroman": "times",
    "tinos": "times", "liberationserif": "times", "nimbusroman": "times", "tiro": "times",
    "courier": "courier", "couriernew": "courier", "couriernewps": "courier", "cousine": "courier",
    "liberationmono": "courier", "nimbusmono": "courier", "cour": "courier",
    "calibri": "calibri", "carlito": "calibri", "cambria": "times", "caladea": "times",
    "verdana": "verdana", "tahoma": "tahoma", "segoeui": "segoeui", "trebuchetms": "trebuchet",
    "centurygothic": "centurygothic", "georgia": "georgia", "garamond": "garamond",
    "bookantiqua": "bookantiqua", "comicsansms": "comicsans",
}


def _font_dirs():
    dirs = [os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")]
    local = os.environ.get("LOCALAPPDATA")
    if local:
        dirs.append(os.path.join(local, "Microsoft", "Windows", "Fonts"))
    return [d for d in dirs if os.path.isdir(d)]


_FONT_FILE_CACHE = {}


def find_font_file(name):
    if not name:
        return None
    key = name.lower()
    if key not in _FONT_FILE_CACHE:
        found = None
        for d in _font_dirs():
            try:
                for f in os.listdir(d):
                    if f.lower() == key:
                        found = os.path.join(d, f)
                        break
            except OSError:
                pass
            if found:
                break
        _FONT_FILE_CACHE[key] = found
    return _FONT_FILE_CACHE[key]


def make_font(family, bold=False, italic=False):
    """FontChoice per una famiglia (chiave di WIN_FONTS): file di Windows se c'è, altrimenti font standard."""
    idx = (1 if bold else 0) + (2 if italic else 0)
    disp, files, base = WIN_FONTS.get(family, ("Helvetica", (None,) * 4, "helvetica"))
    for i in (idx, idx & 1, 0) if files[idx] is None else (idx,):
        path = find_font_file(files[i])
        if path:
            return FontChoice(disp + STYLE_NAMES[i], f"pp{family}{i}", path)
    return FontChoice({"helvetica": "Helvetica", "times": "Times", "courier": "Courier"}[base] + STYLE_NAMES[idx],
                      BASE14[base][idx])


def font_from_pdf(fontname, flags=0):
    """Dal nome di un font nel PDF (es. 'ABCDEF+TimesNewRomanPS-BoldMT') al carattere più simile."""
    raw = fontname.split("+")[-1]
    low = raw.lower()
    bold = bool(flags & 16) or any(k in low for k in ("bold", "black", "heavy", "semibold", "demi"))
    italic = bool(flags & 2) or "italic" in low or "oblique" in low
    fam = re.split(r"[-,]", raw, maxsplit=1)[0].lower().replace(" ", "")
    for suf in ("psmt", "mt", "ps", "regular", "bold", "italic"):
        if fam.endswith(suf) and fam[:-len(suf)] in FONT_ALIASES:
            fam = fam[:-len(suf)]
            break
    family = FONT_ALIASES.get(fam)
    exact = family is not None
    if not family:
        family = "courier" if flags & 8 else "times" if flags & 4 else "arial"
    return make_font(family, bold, italic), exact, raw, family


def available_fonts():
    """Elenco dei caratteri da proporre: quelli di Windows presenti e i 14 standard."""
    out = []
    for fam in WIN_FONTS:
        for i in range(4):
            f = make_font(fam, bool(i & 1), bool(i & 2))
            if f.fontfile and f.label not in [o.label for o in out]:
                out.append(f)
    for base, disp in (("helvetica", "Helvetica"), ("times", "Times"), ("courier", "Courier")):
        for i in range(4):
            out.append(FontChoice(disp + STYLE_NAMES[i], BASE14[base][i]))
    return out


# ----------------------------------------------------------------------------
# Moduli "disegnati": riconoscimento dei campi (riquadri, caselle a carattere, caselle di spunta)
# ----------------------------------------------------------------------------
CHECK_CHARS = ("☐", "□", "❑", "◻", "▢")

THIN = 1.6          # spessore massimo di un "filo" (bordo disegnato come rettangolo pieno)
MIN_H, MAX_H = 7, 40  # altezza di un campo su una riga
TOL = 1.2


def _merge(segs, horizontal):
    """Unisce i segmenti allineati e contigui. segs: (pos, a, b) con a<b."""
    segs = sorted(segs)
    out = []
    for pos, a, b in segs:
        for s in out:
            if abs(s[0] - pos) <= TOL and a <= s[2] + 1.6 and b >= s[1] - 1.6:
                s[1], s[2] = min(s[1], a), max(s[2], b)
                s[0] = (s[0] + pos) / 2
                break
        else:
            out.append([pos, a, b])
    # seconda passata per unire catene
    changed = True
    while changed:
        changed = False
        for i in range(len(out)):
            for j in range(i + 1, len(out)):
                s, t = out[i], out[j]
                if abs(s[0] - t[0]) <= TOL and s[1] <= t[2] + 1.6 and s[2] >= t[1] - 1.6:
                    s[1], s[2] = min(s[1], t[1]), max(s[2], t[2])
                    out.pop(j)
                    changed = True
                    break
            if changed:
                break
    return out


def _grid_cells(hsegs, vsegs):
    """Celle formate da fili orizzontali e verticali (tabelle Word)."""
    cells = []
    hsegs = sorted(hsegs)
    for i, (ty, tx0, tx1) in enumerate(hsegs):
        for by, bx0, bx1 in hsegs[i + 1:]:
            dy = by - ty
            if dy < MIN_H:
                continue
            if dy > MAX_H:
                break
            x0, x1 = max(tx0, bx0), min(tx1, bx1)
            if x1 - x0 < 4:
                continue
            xs = sorted(vx for vx, vy0, vy1 in vsegs
                        if x0 - TOL <= vx <= x1 + TOL and vy0 <= ty + 1.5 and vy1 >= by - 1.5)
            dedup = []
            for x in xs:
                if not dedup or x - dedup[-1] > 1.5:
                    dedup.append(x)
            for a, b in zip(dedup, dedup[1:]):
                if b - a >= 4:
                    cells.append((a, ty, b, by))
    return cells


def _contains(outer, inner, m=0.6):
    return (outer[0] - m <= inner[0] and outer[1] - m <= inner[1] and
            outer[2] + m >= inner[2] and outer[3] + m >= inner[3])


def _area(r):
    return max(0, r[2] - r[0]) * max(0, r[3] - r[1])


def detect_fields(prims, words, check_rects, chars=None):
    boxes, hs, vs = [], [], []
    for p in prims:
        if p[0] == "rect":
            _, x0, y0, x1, y1, filled, stroked = p
            w, h = x1 - x0, y1 - y0
            if w <= THIN and h <= THIN:
                continue                      # puntini d'angolo
            if filled and h <= THIN:
                hs.append(((y0 + y1) / 2, x0, x1))
            elif filled and w <= THIN:
                vs.append(((x0 + x1) / 2, y0, y1))
            elif stroked:
                boxes.append((x0, y0, x1, y1))
                # anche i lati, per le tabelle fatte di rettangoli
                hs += [(y0, x0, x1), (y1, x0, x1)]
                vs += [(x0, y0, y1), (x1, y0, y1)]
        else:
            _, x0, y0, x1, y1 = p
            if abs(y1 - y0) <= THIN:
                hs.append(((y0 + y1) / 2, min(x0, x1), max(x0, x1)))
            elif abs(x1 - x0) <= THIN:
                vs.append(((x0 + x1) / 2, min(y0, y1), max(y0, y1)))
    hs = [s for s in _merge(hs, True) if s[2] - s[1] >= 3]
    vs = [s for s in _merge(vs, False) if s[2] - s[1] >= 3]
    cand = boxes + _grid_cells(hs, vs)
    # solo campi su una riga, non minuscoli
    cand = [r for r in cand if MIN_H <= r[3] - r[1] <= MAX_H and r[2] - r[0] >= 6]
    # niente duplicati; si tengono le celle più piccole (scarta i contenitori)
    uniq = []
    for r in sorted(cand, key=_area):
        if any(abs(r[0] - u[0]) < 1.5 and abs(r[1] - u[1]) < 1.5 and abs(r[2] - u[2]) < 1.5
               and abs(r[3] - u[3]) < 1.5 for u in uniq):
            continue
        if any(_contains(r, u) for u in uniq):
            continue
        uniq.append(r)

    def text_in(r):
        out = []
        for wx0, wy0, wx1, wy1, t in (chars if chars is not None else words):
            cx, cy = (wx0 + wx1) / 2, (wy0 + wy1) / 2
            if r[0] < cx < r[2] and r[1] < cy < r[3]:
                out.append((wx0, t))
        return "".join(t for _, t in sorted(out)).strip()

    cells = []
    for r in uniq:
        t = text_in(r)
        cells.append(dict(rect=r, text=t))
    # raggruppa le caselle a carattere singolo (stessa riga, adiacenti, strette)
    cells.sort(key=lambda c: (round(c["rect"][1]), c["rect"][0]))
    fields, used = [], set()
    for i, c in enumerate(cells):
        if i in used:
            continue
        r = c["rect"]
        w, h = r[2] - r[0], r[3] - r[1]
        group = [i]
        if w <= max(22, h * 1.5):
            last = r
            for j in range(i + 1, len(cells)):
                if j in used:
                    continue
                s = cells[j]["rect"]
                sw = s[2] - s[0]
                if (abs(s[1] - last[1]) <= 1.5 and abs(s[3] - last[3]) <= 1.5 and 0 <= s[0] - last[2] <= 2.5
                        and sw <= max(22, h * 1.5)):
                    group.append(j)
                    last = s
                elif s[1] - last[1] > 2:
                    break
        if len(group) >= 2:
            used.update(group)
            rs = [cells[k]["rect"] for k in group]
            fixed = {n: cells[k]["text"] for n, k in enumerate(group) if cells[k]["text"]}
            fields.append(dict(kind="comb", rect=(rs[0][0], min(x[1] for x in rs), rs[-1][2], max(x[3] for x in rs)),
                               cells=rs, fixed=fixed))
        else:
            used.add(i)
            if c["text"] and len(c["text"]) > 2:
                continue                       # riquadro con testo stampato: non è un campo vuoto
            fields.append(dict(kind="text", rect=r, cells=[r], fixed={}))
    for r in check_rects:
        if not any(_contains(f["rect"], r, 1) for f in fields):
            fields.append(dict(kind="check", rect=r, cells=[r], fixed={}))
    # etichetta: testo subito sotto (moduli Word) o subito a sinistra
    for f in fields:
        f["label"] = find_label(f["rect"], words, right=f["kind"] == "check")
    fields.sort(key=lambda f: (round(f["rect"][1] / 4), f["rect"][0]))
    return fields


def find_label(r, words, right=False):
    if right:  # casella di spunta: la descrizione è subito a destra
        toks = sorted((w[0], w[4]) for w in words
                      if abs((w[1] + w[3]) / 2 - (r[1] + r[3]) / 2) < 5 and 0 <= w[0] - r[2] <= 60)
        out = []
        last = r[2]
        for x, t in toks:
            if x - last > 12 or t in ("☐", "□"):
                break
            out.append(t)
            last = x + len(t) * 4
        return " ".join(out)[:60]
    below = [(w[0], w[4]) for w in words
             if 0 <= w[1] - r[3] <= 9 and w[0] >= r[0] - 2 and w[0] < r[2] - 2]
    if below:
        line_y = min(w[1] for w in words if 0 <= w[1] - r[3] <= 9 and r[0] - 2 <= w[0] < r[2] - 2)
        toks = sorted((w[0], w[4]) for w in words if abs(w[1] - line_y) < 2 and r[0] - 2 <= w[0] < r[2] - 2)
        return " ".join(t for _, t in toks)[:60]
    left = [(w[2], w[4]) for w in words
            if abs((w[1] + w[3]) / 2 - (r[1] + r[3]) / 2) < 6 and 0 <= r[0] - w[2] <= 40]
    if left:
        return max(left)[1][:60]
    return ""


def page_form_fields(page):
    """Campi del modulo su una pagina PyMuPDF (coordinate della pagina non ruotata)."""
    prims = []
    for path in page.get_drawings():
        kind = path.get("type") or ""
        filled = "f" in kind or (not kind and path.get("fill") is not None)
        stroked = "s" in kind or (not kind and path.get("color") is not None)
        for it in path.get("items", []):
            op = it[0]
            if op == "re":
                r = fitz.Rect(it[1])
                prims.append(("rect", r.x0, r.y0, r.x1, r.y1, filled, stroked))
            elif op == "qu":
                r = fitz.Quad(it[1]).rect
                prims.append(("rect", r.x0, r.y0, r.x1, r.y1, filled, stroked))
            elif op == "l":
                p1, p2 = it[1], it[2]
                prims.append(("line", p1.x, p1.y, p2.x, p2.y))
    words = [(w[0], w[1], w[2], w[3], w[4]) for w in page.get_text("words")]
    checks = []
    for ch in CHECK_CHARS:
        try:
            checks += [(r.x0, r.y0, r.x1, r.y1) for r in page.search_for(ch)]
        except Exception:
            pass
    words = [w for w in words if w[4] not in CHECK_CHARS]
    # caratteri singoli (posizione stimata dentro la parola) per riconoscere le caselle già stampate
    chars = []
    for x0, y0, x1, y1, t in words:
        cw = (x1 - x0) / max(len(t), 1)
        chars += [(x0 + k * cw, y0, x0 + (k + 1) * cw, y1, ch) for k, ch in enumerate(t)]
    return detect_fields(prims, words, checks, chars)


def comb_layout(field, value):
    """Distribuisce il testo nelle caselle di un campo a caratteri singoli.
    Restituisce {indice_casella: carattere} per le sole caselle libere."""
    cells, fixed = field["cells"], field["fixed"]
    n = len(cells)
    free = [i for i in range(n) if i not in fixed]
    val = value.strip().upper()
    seps = {i: c for i, c in fixed.items() if c in (",", ".")}
    if len(seps) == 1 and len(fixed) == 1:  # numero con virgola: interi a destra, decimali a sinistra
        k = next(iter(seps))
        v = val.replace(".", ",")
        if "," in v or len(v) <= k:
            ip, _, dp = v.partition(",")
            ip, dp = ip.replace(" ", ""), dp.replace(" ", "")
            out = {}
            for j, ch in enumerate(reversed(ip[-k:])):
                out[k - 1 - j] = ch
            for j, ch in enumerate(dp[:n - k - 1]):
                out[k + 1 + j] = ch
            return out
    if len(val) == n:  # testo completo, compresi i caratteri già stampati (es. IT001E..., 17/11/2026)
        return {i: val[i] for i in free if val[i] != " "}
    fixed_chars = set(fixed.values())
    chars = [c for c in val if c != " " and c not in fixed_chars] if len(val) > len(free) else \
        [c for c in val if c != " "] if len(val.replace(" ", "")) <= len(free) else list(val)
    return {free[j]: ch for j, ch in enumerate(chars[:len(free)])}


def draw_form_value(page, field, value):
    """Scrive il valore di un campo sulla pagina (coordinate non ruotate)."""
    if not value:
        return
    black = (0, 0, 0)
    if field["kind"] == "check":
        x0, y0, x1, y1 = field["rect"]
        m = (y1 - y0) * 0.2
        w = max(0.8, (y1 - y0) * 0.12)
        page.draw_line(fitz.Point(x0 + m, y0 + m), fitz.Point(x1 - m, y1 - m), color=black, width=w)
        page.draw_line(fitz.Point(x0 + m, y1 - m), fitz.Point(x1 - m, y0 + m), color=black, width=w)
        return
    if field["kind"] == "comb":
        for i, ch in comb_layout(field, value).items():
            x0, y0, x1, y1 = field["cells"][i]
            h, w = y1 - y0, x1 - x0
            size = min(12.0, h * 0.62, w * 1.0)
            tw = fitz.get_text_length(ch, fontname="helv", fontsize=size)
            page.insert_text(fitz.Point((x0 + x1) / 2 - tw / 2, y0 + (h + size * 0.7) / 2), ch,
                             fontsize=size, fontname="helv", color=black)
        return
    x0, y0, x1, y1 = field["rect"]
    h, w = y1 - y0, x1 - x0
    size = min(11.0, h * 0.62)
    while size > 4 and fitz.get_text_length(value, fontname="helv", fontsize=size) > w - 5:
        size -= 0.5
    page.insert_text(fitz.Point(x0 + 2.5, y0 + (h + size * 0.7) / 2), value, fontsize=size,
                     fontname="helv", color=black)


# ----------------------------------------------------------------------------
# Stima dello stile da un'immagine (pagine scansionate)
# ----------------------------------------------------------------------------
SCAN_DPI = 300
_DESC = set("gjpqy,;()[]{}|@$Q")
_LASC = set("bdfhklt'àèéìòù")


def _otsu(hist):
    total = sum(hist)
    sum_all = sum(i * h for i, h in enumerate(hist))
    wb = sb = 0
    best_t, best_v = 128, -1
    for t in range(256):
        wb += hist[t]
        if wb == 0:
            continue
        wf = total - wb
        if wf == 0:
            break
        sb += t * hist[t]
        mb, mf = sb / wb, (sum_all - sb) / wf
        v = wb * wf * (mb - mf) ** 2
        if v > best_v:
            best_v, best_t = v, t
    return best_t


def _tmean(v):
    """Media tra il 20° e il 70° percentile: robusta e meno "a scalini" della mediana."""
    if not v:
        return 0
    v = sorted(v)
    a = int(len(v) * 0.2)
    b = max(int(len(v) * 0.7), a + 1)
    part = v[a:b]
    return sum(part) / len(part)


def _median(v):
    v = sorted(v)
    return v[len(v) // 2] if v else None


def split_lines(img):
    """Divide un'immagine con più righe di testo in strisce, una per riga."""
    gray = img.convert("L")
    thr = _otsu(gray.histogram())
    ink = gray.point(lambda p: 255 if p < thr else 0)
    w, h = ink.size
    data = ink.tobytes()
    rows = [sum(1 for b in data[y * w:(y + 1) * w] if b) for y in range(h)]
    min_ink = max(1, w // 200)
    bands, start = [], None
    for y, n in enumerate(rows + [0]):
        if n >= min_ink and start is None:
            start = y
        elif n < min_ink and start is not None:
            if y - start >= 4:
                bands.append((start, y))
            start = None
    return [img.crop((0, max(0, a - 2), w, min(h, b + 2))) for a, b in bands]


def analyze_line(img, dpi=SCAN_DPI, text=None):
    """Analizza l'immagine di UNA riga di testo: dimensione, spessore aste, contrasto, colore."""
    gray = img.convert("L")
    hist = gray.histogram()
    thr = _otsu(hist)
    if thr < 40 or thr > 245:
        thr = 160
    # "morbidezza": quanti pixel grigi di bordo ci sono rispetto all'inchiostro pieno (scansione sfocata)
    soft = sum(hist[max(1, thr - 60):min(255, thr + 50)]) / max(sum(hist[:max(1, thr - 60)]), 1)
    ink = gray.point(lambda p: 255 if p < thr else 0)
    bbox = ink.getbbox()
    if not bbox:
        return None
    ink = ink.crop(bbox)
    w, h = ink.size
    if h < 4 or w < 4:
        return None
    data = ink.tobytes()
    if text:
        t = text.replace(" ", "")
        desc = any(c in _DESC for c in t)
        lasc = any(c in _LASC for c in t)
        caps = any(c.isupper() or c.isdigit() for c in t)
    else:
        desc = lasc = caps = True
    if desc:
        factor = 0.92 if lasc else 0.88 if caps else 0.73
    else:
        factor = 0.73 if lasc else 0.67 if caps else 0.52
    em = h / factor
    hruns = []
    for y in range(h):
        run = 0
        for b in data[y * w:(y + 1) * w]:
            if b:
                run += 1
            elif run:
                hruns.append(run)
                run = 0
        if run:
            hruns.append(run)
    vruns = []
    lim = 0.3 * em
    for x in range(w):
        run = 0
        for y in range(h):
            if data[y * w + x]:
                run += 1
            elif run:
                if run < lim:
                    vruns.append(run)
                run = 0
        if run and run < lim:
            vruns.append(run)
    stem = _tmean(hruns)
    horiz = _tmean(vruns)
    px = list(img.crop(bbox).getdata())
    gpx = list(gray.crop(bbox).getdata())
    dark = sorted(range(len(gpx)), key=lambda i: gpx[i])[:max(1, len(gpx) // 12)]
    r = sum(px[i][0] for i in dark) / len(dark)
    g = sum(px[i][1] for i in dark) / len(dark)
    b = sum(px[i][2] for i in dark) / len(dark)
    color = (0, 0, 0) if max(r, g, b) < 90 else (round(r / 255, 3), round(g / 255, 3), round(b / 255, 3))
    lower = bool(text) and sum(c.islower() for c in text) > len(text) * 0.4
    return dict(size=em * 72 / dpi, stem_em=stem / em, contrast=(horiz / stem) if stem else 1.0, soft=soft,
                width_ratio=(w / (len(text) * em)) if (text and lower) else None,
                color=color, caps_only=bool(text) and caps and not lasc and not desc,
                full=bool(text) and desc and (lasc or caps))


def combine_styles(results, page_stem=None):
    """Unisce le misure di più righe in uno stile: dimensione, grassetto, famiglia, colore."""
    results = [r for r in results if r]
    if not results:
        return None
    best = [r for r in results if r["full"]] or [r for r in results if not r["caps_only"]] or results
    size = _median([r["size"] for r in best])
    stem = _median([r["stem_em"] for r in results])
    contrast = _median([r["contrast"] for r in results])
    bold = stem > 1.2 * page_stem if page_stem else stem > 0.116
    soft = _median([r["soft"] for r in results])
    # rapporto tratti orizzontali/aste: basso nei caratteri con grazie. Nel testo normale la sfocatura
    # ingrossa i tratti sottili, quindi con scansioni molto "morbide" la soglia sale.
    serif = contrast < (0.64 if bold else max(0.72, 0.30 + 0.22 * soft))
    widths = [r["width_ratio"] for r in results if r["width_ratio"]]
    mono = bool(widths) and _median(widths) > 0.575
    colors = [r["color"] for r in results]
    color = max(set(colors), key=colors.count)
    if not serif and any(r["caps_only"] for r in best):  # le maiuscole dei caratteri senza grazie sono più alte
        size *= 0.67 / 0.72
    return dict(size=round(size * 2) / 2, bold=bold, family="courier" if mono else "times" if serif else "arial",
                color=color, stem=stem)


FONTS = {"Helvetica": "helv", "Helvetica grassetto": "hebo",
         "Times": "tiro", "Times grassetto": "tibo",
         "Courier": "cour", "Courier grassetto": "cobo"}
ALIGNS = {"Sinistra": 0, "Centro": 1, "Destra": 2, "Giustificato": 3}


class TextDialog(BaseDialog):
    """Testo da scrivere. 'style' = carattere, dimensione e colore proposti (rilevati dal documento)."""

    def __init__(self, master, title, text="", style=None):
        super().__init__(master, title)
        self.resizable(True, True)
        style = style or {}
        self.color = style.get("color", (0, 0, 0))
        self.txt = tk.Text(self.body, width=64, height=10, wrap="word", font=("Segoe UI", 10), undo=True)
        self.txt.insert("1.0", text)
        self.txt.edit_reset()
        attach_edit_menu(self.txt)
        self.txt.grid(row=0, column=0, columnspan=8, sticky="nsew")
        self.body.rowconfigure(0, weight=1)
        self.body.columnconfigure(7, weight=1)

        self.fonts = available_fonts()
        proposed = style.get("font")
        if proposed and proposed.label not in [f.label for f in self.fonts]:
            self.fonts.insert(0, proposed)
        self.by_label = {f.label: f for f in self.fonts}
        ttk.Label(self.body, text="Carattere").grid(row=1, column=0, pady=(8, 0), sticky="w")
        self.font = ttk.Combobox(self.body, values=[f.label for f in self.fonts], state="readonly", width=26)
        self.font.set(proposed.label if proposed else self.fonts[0].label)
        self.font.grid(row=1, column=1, pady=(8, 0), padx=4)
        ttk.Label(self.body, text="Dim.").grid(row=1, column=2, pady=(8, 0))
        self.size = ttk.Spinbox(self.body, from_=4, to=144, increment=0.5, width=6)
        self.size.set(f"{style.get('size', 11.0):g}")
        self.size.grid(row=1, column=3, pady=(8, 0), padx=4)
        ttk.Label(self.body, text="Allin.").grid(row=1, column=4, pady=(8, 0))
        self.align = ttk.Combobox(self.body, values=list(ALIGNS), state="readonly", width=11)
        self.align.set("Sinistra")
        self.align.grid(row=1, column=5, pady=(8, 0), padx=4)
        self.col_btn = tk.Button(self.body, text="  Colore  ", command=self._pick, relief="groove")
        self.col_btn.grid(row=1, column=6, pady=(8, 0), padx=4)
        self._paint_color()
        note = style.get("note")
        if note:
            ttk.Label(self.body, text=note, foreground="#1565c0", wraplength=560, justify="left").grid(
                row=2, column=0, columnspan=8, sticky="w", pady=(8, 0))
        self.buttons()
        self.txt.focus_set()

    def _paint_color(self):
        r, g, b = (int(c * 255) for c in self.color)
        hexc = f"#{r:02x}{g:02x}{b:02x}"
        self.col_btn.config(bg=hexc, activebackground=hexc, fg="white" if (r + g + b) < 380 else "black")

    def _pick(self):
        c = colorchooser.askcolor(parent=self)
        if c and c[0]:
            self.color = tuple(v / 255 for v in c[0])
            self._paint_color()

    def _ok(self):
        text = self.txt.get("1.0", "end-1c")
        try:
            size = float(self.size.get().replace(",", "."))
        except ValueError:
            messagebox.showwarning(APP_NAME, "Dimensione carattere non valida", parent=self)
            return
        self.result = dict(text=text, size=size, font=self.by_label[self.font.get()],
                           align=ALIGNS[self.align.get()], color=self.color)
        self.destroy()


class PositionDialog(BaseDialog):
    """Chiede dove inserire: prima/dopo la pagina corrente o in posizione N."""

    def __init__(self, master, title, current, n_pages, extra=None):
        super().__init__(master, title)
        self.n = n_pages
        self.cur = current
        self.mode = tk.StringVar(value="after")
        ttk.Radiobutton(self.body, text=f"Dopo la pagina corrente ({current + 1})",
                        variable=self.mode, value="after").grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Radiobutton(self.body, text=f"Prima della pagina corrente ({current + 1})",
                        variable=self.mode, value="before").grid(row=1, column=0, columnspan=2, sticky="w")
        ttk.Radiobutton(self.body, text="All'inizio del documento",
                        variable=self.mode, value="start").grid(row=2, column=0, columnspan=2, sticky="w")
        ttk.Radiobutton(self.body, text="Alla fine del documento",
                        variable=self.mode, value="end").grid(row=3, column=0, columnspan=2, sticky="w")
        ttk.Radiobutton(self.body, text="Come nuova pagina numero:",
                        variable=self.mode, value="num").grid(row=4, column=0, sticky="w")
        self.num = ttk.Spinbox(self.body, from_=1, to=n_pages + 1, width=6)
        self.num.set(current + 2)
        self.num.grid(row=4, column=1, sticky="w", padx=4)
        attach_edit_menu(self.num)
        self.extra = None
        if extra:  # (etichetta, valore predefinito) per un campo testo aggiuntivo
            ttk.Label(self.body, text=extra[0]).grid(row=5, column=0, sticky="w", pady=(10, 0))
            self.extra = ttk.Entry(self.body, width=18)
            self.extra.insert(0, extra[1])
            self.extra.grid(row=5, column=1, sticky="w", padx=4, pady=(10, 0))
            attach_edit_menu(self.extra)
        self.buttons()

    def _ok(self):
        m = self.mode.get()
        if m == "after":
            pos = self.cur + 1
        elif m == "before":
            pos = self.cur
        elif m == "start":
            pos = 0
        elif m == "end":
            pos = self.n
        else:
            try:
                pos = int(self.num.get()) - 1
            except ValueError:
                pos = -1
            if not 0 <= pos <= self.n:
                messagebox.showwarning(APP_NAME, f"Numero tra 1 e {self.n + 1}", parent=self)
                return
        self.result = (pos, self.extra.get() if self.extra else None)
        self.destroy()


class OcrDialog(BaseDialog):
    def __init__(self, master, langs):
        super().__init__(master, "OCR - rendi il PDF ricercabile")
        ttk.Label(self.body, text="Lingue del documento:").grid(row=0, column=0, sticky="nw")
        self.lb = tk.Listbox(self.body, selectmode="multiple", height=min(6, len(langs)),
                             exportselection=False)
        for i, l in enumerate(langs):
            self.lb.insert("end", l)
            if l in ("ita", "eng"):
                self.lb.selection_set(i)
        if not self.lb.curselection():
            self.lb.selection_set(0)
        self.lb.grid(row=0, column=1, sticky="w", padx=6)
        ttk.Label(self.body, text="Risoluzione:").grid(row=1, column=0, sticky="w", pady=(8, 0))
        self.dpi = ttk.Combobox(self.body, values=["150", "200", "300", "400"],
                                state="readonly", width=6)
        self.dpi.set("300")
        self.dpi.grid(row=1, column=1, sticky="w", padx=6, pady=(8, 0))
        self.scope = tk.StringVar(value="missing")
        ttk.Radiobutton(self.body, text="Solo pagine senza testo (scansioni)",
                        variable=self.scope, value="missing").grid(row=2, column=0, columnspan=2, sticky="w", pady=(8, 0))
        ttk.Radiobutton(self.body, text="Tutte le pagine",
                        variable=self.scope, value="all").grid(row=3, column=0, columnspan=2, sticky="w")
        self.range = tk.StringVar(value="")
        ttk.Label(self.body, text="Pagine (vuoto = tutte, es. 1-3,7):").grid(row=4, column=0, sticky="w", pady=(8, 0))
        rng = ttk.Entry(self.body, textvariable=self.range, width=14)
        rng.grid(row=4, column=1, sticky="w", padx=6, pady=(8, 0))
        attach_edit_menu(rng)
        ttk.Label(self.body, foreground="#777",
                  text="Le pagine elaborate diventano immagine + livello di testo invisibile.").grid(
            row=5, column=0, columnspan=2, sticky="w", pady=(10, 0))
        self.buttons("Avvia OCR")

    def _ok(self):
        langs = [self.lb.get(i) for i in self.lb.curselection()]
        if not langs:
            messagebox.showwarning(APP_NAME, "Seleziona almeno una lingua", parent=self)
            return
        self.result = dict(lang="+".join(langs), dpi=int(self.dpi.get()),
                           only_missing=self.scope.get() == "missing",
                           pages=self.range.get().strip())
        self.destroy()


COMPRESS_PRESETS = {
    "Leggera (immagini a 150 dpi, qualità 80)": (150, 80),
    "Media (immagini a 110 dpi, qualità 65)": (110, 65),
    "Forte (immagini a 72 dpi, qualità 50)": (72, 50),
    "Solo ottimizzazione senza perdita": (None, None),
}


class CompressDialog(BaseDialog):
    def __init__(self, master):
        super().__init__(master, "Comprimi PDF")
        self.var = tk.StringVar(value=list(COMPRESS_PRESETS)[1])
        for i, k in enumerate(COMPRESS_PRESETS):
            ttk.Radiobutton(self.body, text=k, variable=self.var, value=k).grid(row=i, column=0, sticky="w")
        self.buttons("Comprimi")

    def _ok(self):
        self.result = COMPRESS_PRESETS[self.var.get()]
        self.destroy()


SANITIZE_ITEMS = [  # chiave, descrizione, attivo di default
    ("meta", "Metadati: autore, titolo, oggetto, parole chiave, programma, date (anche XMP)", True),
    ("annots", "Commenti e annotazioni: note, evidenziazioni, timbri, disegni a mano", True),
    ("attachments", "File allegati incorporati nel PDF", True),
    ("bookmarks", "Segnalibri (indice laterale)", True),
    ("links", "Collegamenti a pagine web e ad altre parti del documento", True),
    ("js", "Codice JavaScript", True),
    ("fields", "Valori dei campi compilabili (i campi restano, vuoti)", False),
    ("hidden", "Testo invisibile, compreso il livello di testo creato dall'OCR", False),
]


def inspect_hidden(doc):
    """Conta i dati 'nascosti' presenti nel documento."""
    out = {}
    try:
        out["meta"] = sum(1 for k, v in (doc.metadata or {}).items()
                          if v and k not in ("format", "encryption")) + (1 if doc.get_xml_metadata() else 0)
    except Exception:
        out["meta"] = None
    try:
        out["attachments"] = doc.embfile_count()
    except Exception:
        out["attachments"] = None
    try:
        out["bookmarks"] = len(doc.get_toc())
    except Exception:
        out["bookmarks"] = None
    annots = links = fields = 0
    for page in doc:
        try:
            annots += sum(1 for _ in page.annots())
            links += len(page.get_links())
            fields += sum(1 for _ in page.widgets())
        except Exception:
            pass
    out.update(annots=annots, links=links, fields=fields)
    js = 0
    try:
        for x in range(1, min(doc.xref_length(), 200000)):
            obj = doc.xref_object(x, compressed=True)
            if "/JS" in obj or "/JavaScript" in obj:
                js += 1
    except Exception:
        js = None
    out["js"] = js
    out["hidden"] = None
    return out


def sanitize_document(doc, opts):
    """Rimuove i dati nascosti scelti. opts = {chiave: bool}."""
    kw = dict(attached_files=opts["attachments"], embedded_files=opts["attachments"],
              hidden_text=opts["hidden"], javascript=opts["js"], metadata=opts["meta"],
              redactions=False, remove_links=opts["links"], reset_fields=opts["fields"],
              reset_responses=opts["annots"], thumbnails=True, xml_metadata=opts["meta"],
              clean_pages=opts["hidden"])
    try:
        doc.scrub(**kw)
    except Exception:
        pass  # versioni diverse di PyMuPDF: si completa a mano qui sotto
    steps = []
    if opts["meta"]:
        steps.append(lambda: doc.set_metadata({}))
        steps.append(lambda: doc.del_xml_metadata())
    if opts["attachments"]:
        steps.append(lambda: [doc.embfile_del(n) for n in doc.embfile_names()])
    if opts["bookmarks"]:
        steps.append(lambda: doc.set_toc([]))
    for step in steps:
        try:
            step()
        except Exception:
            pass
    for page in doc:
        if opts["annots"]:
            try:
                a = page.first_annot
                while a:
                    a = page.delete_annot(a)
            except Exception:
                pass
        if opts["links"]:
            try:
                for ln in page.get_links():
                    page.delete_link(ln)
            except Exception:
                pass


class SanitizeDialog(BaseDialog):
    def __init__(self, master, found):
        super().__init__(master, "Rimuovi metadati e dati nascosti")
        ttk.Label(self.body, text="Elimina dal file i dati che non si vedono sulla pagina ma possono rivelare\n"
                                  "informazioni (consigliato prima di inviare un documento omissato).",
                  justify="left").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        self.vars = {}
        for r, (key, text, default) in enumerate(SANITIZE_ITEMS, start=1):
            n = found.get(key)
            var = tk.BooleanVar(value=default)
            self.vars[key] = var
            ttk.Checkbutton(self.body, text=text, variable=var).grid(row=r, column=0, sticky="w")
            if n is not None:
                ttk.Label(self.body, text="presenti: %d" % n if n else "nessuno",
                          foreground="#c62828" if n else "#888").grid(row=r, column=1, sticky="e", padx=(12, 0))
        ttk.Label(self.body, foreground="#666", justify="left",
                  text="Il testo invisibile resta selezionato solo se lo scegli: toglierlo rende di nuovo\n"
                       "non ricercabili le scansioni a cui hai fatto l'OCR.").grid(
            row=len(SANITIZE_ITEMS) + 1, column=0, columnspan=2, sticky="w", pady=(8, 0))
        self.buttons("Rimuovi")

    def _ok(self):
        self.result = {k: v.get() for k, v in self.vars.items()}
        self.destroy()


class Job:
    """Esegue un lavoro lungo in un thread con finestra di avanzamento modale."""

    def __init__(self, master, title, work, on_done):
        self.master, self.work, self.on_done = master, work, on_done
        self.q = queue.Queue()
        self.cancel = threading.Event()
        self.win = tk.Toplevel(master)
        self.win.title(title)
        self.win.transient(master)
        self.win.resizable(False, False)
        self.win.protocol("WM_DELETE_WINDOW", self.cancel.set)
        f = ttk.Frame(self.win, padding=14)
        f.pack()
        self.lbl = ttk.Label(f, text="Avvio...", width=50)
        self.lbl.pack(anchor="w")
        self.bar = ttk.Progressbar(f, length=360, maximum=100)
        self.bar.pack(pady=8)
        ttk.Button(f, text="Annulla", command=self.cancel.set).pack(anchor="e")
        self.win.update_idletasks()
        x = master.winfo_rootx() + (master.winfo_width() - self.win.winfo_width()) // 2
        y = master.winfo_rooty() + (master.winfo_height() - self.win.winfo_height()) // 3
        self.win.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        self.win.grab_set()
        threading.Thread(target=self._run, daemon=True).start()
        self._poll()

    def report(self, i, n, msg):
        self.q.put(("prog", i, n, msg))

    def _run(self):
        try:
            self.q.put(("done", self.work(self.report, self.cancel.is_set)))
        except Exception as exc:
            self.q.put(("error", exc))

    def _poll(self):
        try:
            while True:
                item = self.q.get_nowait()
                if item[0] == "prog":
                    _, i, n, msg = item
                    self.bar["value"] = 100 * i / max(n, 1)
                    self.lbl.config(text=msg)
                else:
                    self.win.grab_release()
                    self.win.destroy()
                    if item[0] == "error":
                        messagebox.showerror(APP_NAME, f"Operazione non riuscita:\n\n{item[1]}",
                                             parent=self.master)
                    elif item[1] is not None:
                        self.on_done(item[1])
                    return
        except queue.Empty:
            pass
        self.win.after(100, self._poll)


class Cancelled(Exception):
    pass


# ----------------------------------------------------------------------------
# Lavori pesanti (girano nel thread; la UI resta bloccata dalla finestra modale)
# ----------------------------------------------------------------------------
def ocr_worker(data, opts, tessdir):
    def work(report, cancelled):
        src = fitz.open("pdf", data)
        out = fitz.open()
        n = len(src)
        targets = set(parse_ranges(opts["pages"], n)) if opts["pages"] else set(range(n))
        done = 0
        for i in range(n):
            if cancelled():
                raise Cancelled()
            page = src[i]
            if i not in targets or (opts["only_missing"] and page.get_text("text").strip()):
                out.insert_pdf(src, from_page=i, to_page=i)
                continue
            report(i, n, f"OCR pagina {i + 1} di {n}...")
            pix = page.get_pixmap(dpi=opts["dpi"], alpha=False)
            pdf_bytes = pix.pdfocr_tobytes(compress=True, language=opts["lang"], tessdata=tessdir)
            with fitz.open("pdf", pdf_bytes) as ocr:
                newp = out.new_page(width=page.rect.width, height=page.rect.height)
                newp.show_pdf_page(newp.rect, ocr, 0)
            done += 1
        report(n, n, "Salvataggio...")
        result = out.tobytes(garbage=3, deflate=True)
        return result, done
    return work


def _manual_recompress(doc, dpi, quality, report, cancelled):
    """Ricomprime le immagini con Pillow (per versioni di PyMuPDF senza rewrite_images)."""
    from PIL import Image
    seen = set()
    n = len(doc)
    for pno, page in enumerate(doc):
        if cancelled():
            raise Cancelled()
        report(pno, n, f"Immagini pagina {pno + 1} di {n}...")
        for info in page.get_images(full=True):
            xref, smask = info[0], info[1]
            if xref in seen or smask:
                continue
            seen.add(xref)
            try:
                rects = page.get_image_rects(xref)
                pix = fitz.Pixmap(doc, xref)
                if pix.alpha or not rects:
                    continue
                if pix.n - pix.alpha > 3:  # CMYK -> RGB
                    pix = fitz.Pixmap(fitz.csRGB, pix)
                w_in = max(r.width for r in rects) / 72.0
                eff_dpi = pix.width / max(w_in, 0.01)
                mode = "L" if pix.n == 1 else "RGB"
                im = Image.frombytes(mode, (pix.width, pix.height), pix.samples)
                if eff_dpi > dpi * 1.1:
                    k = dpi / eff_dpi
                    im = im.resize((max(1, int(im.width * k)), max(1, int(im.height * k))),
                                   Image.LANCZOS)
                buf = io.BytesIO()
                im.save(buf, "JPEG", quality=quality, optimize=True)
                old_len = len(doc.xref_stream_raw(xref) or b"")
                if buf.tell() < old_len:
                    page.replace_image(xref, stream=buf.getvalue())
            except Exception:
                continue  # immagine non gestibile: la si lascia com'è


def compress_worker(data, dpi, quality):
    def work(report, cancelled):
        doc = fitz.open("pdf", data)
        if dpi:
            report(0, 1, "Ricompressione immagini...")
            done = False
            if hasattr(doc, "rewrite_images"):
                try:
                    doc.rewrite_images(dpi_threshold=int(dpi * 1.1), dpi_target=dpi, quality=quality)
                    done = True
                except Exception:
                    done = False
            if not done:
                _manual_recompress(doc, dpi, quality, report, cancelled)
        if cancelled():
            raise Cancelled()
        report(1, 1, "Ottimizzazione struttura e salvataggio...")
        opts = dict(garbage=4, deflate=True, deflate_images=True, deflate_fonts=True, clean=True)
        try:
            return doc.tobytes(use_objstms=1, **opts)
        except TypeError:
            return doc.tobytes(**opts)
    return work


def _proc_main(kind, in_path, out_path, args, q):
    """Eseguito in un processo separato: l'OCR blocca l'interprete Python per tutto il tempo del
    riconoscimento, quindi lo si tiene fuori dal processo della finestra, che resta reattiva."""
    global fitz
    try:
        try:
            import pymupdf as _f
        except ImportError:
            import fitz as _f
        fitz = _f
        with open(in_path, "rb") as fh:
            data = fh.read()
        work = ocr_worker(data, *args) if kind == "ocr" else compress_worker(data, *args)
        res = work(lambda i, n, msg: q.put(("prog", i, n, msg)), lambda: False)
        out, extra = res if kind == "ocr" else (res, None)
        with open(out_path, "wb") as fh:
            fh.write(out)
        q.put(("done", extra))
    except Exception as exc:
        q.put(("error", f"{type(exc).__name__}: {exc}"))


class ProcessJob:
    """Finestra con barra di avanzamento per un lavoro lungo eseguito in un processo separato."""

    def __init__(self, master, title, kind, data, args, on_done, start_msg="Avvio..."):
        import multiprocessing as mp
        import shutil
        import tempfile
        self.master, self.on_done, self._shutil = master, on_done, shutil
        self.tmp = tempfile.mkdtemp(prefix="pdfpaper_")
        self.in_path = os.path.join(self.tmp, "in.pdf")
        self.out_path = os.path.join(self.tmp, "out.pdf")
        with open(self.in_path, "wb") as fh:
            fh.write(data)
        ctx = mp.get_context("spawn")
        self.q = ctx.Queue()
        self.p = ctx.Process(target=_proc_main, args=(kind, self.in_path, self.out_path, args, self.q),
                             daemon=True)
        self.finished = False
        self.t0 = time.monotonic()

        self.win = tk.Toplevel(master)
        self.win.title(title)
        self.win.transient(master)
        self.win.resizable(False, False)
        self.win.protocol("WM_DELETE_WINDOW", self.cancel)
        f = ttk.Frame(self.win, padding=16)
        f.pack(fill="both", expand=True)
        self.lbl = ttk.Label(f, text=start_msg, width=52)
        self.lbl.pack(anchor="w")
        self.bar = ttk.Progressbar(f, length=380, mode="indeterminate")
        self.bar.pack(pady=(10, 4), fill="x")
        self.sub = ttk.Label(f, text="", foreground="#666")
        self.sub.pack(anchor="w")
        ttk.Button(f, text="Annulla", command=self.cancel).pack(anchor="e", pady=(8, 0))
        self.win.update_idletasks()
        x = master.winfo_rootx() + (master.winfo_width() - self.win.winfo_width()) // 2
        y = master.winfo_rooty() + (master.winfo_height() - self.win.winfo_height()) // 3
        self.win.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        self.bar.start(12)
        self.win.grab_set()
        self.win.update()
        self.p.start()
        self.win.after(100, self._poll)

    def _cleanup(self):
        self.finished = True
        try:
            self.win.grab_release()
            self.win.destroy()
        except tk.TclError:
            pass
        self._shutil.rmtree(self.tmp, ignore_errors=True)

    def cancel(self):
        if self.finished:
            return
        try:
            if self.p.is_alive():
                self.p.terminate()
        except Exception:
            pass
        self._cleanup()

    def _poll(self):
        if self.finished:
            return
        try:
            while True:
                item = self.q.get_nowait()
                if item[0] == "prog":
                    _, i, n, msg = item
                    if str(self.bar.cget("mode")) == "indeterminate":
                        self.bar.stop()
                        self.bar.config(mode="determinate", maximum=100)
                    self.bar["value"] = 100 * i / max(n, 1)
                    self.lbl.config(text=msg)
                    el = int(time.monotonic() - self.t0)
                    self.sub.config(text=f"Tempo trascorso: {el // 60}:{el % 60:02d}")
                elif item[0] == "done":
                    with open(self.out_path, "rb") as fh:
                        data = fh.read()
                    self._cleanup()
                    self.on_done(data, item[1])
                    return
                else:
                    self._cleanup()
                    messagebox.showerror(APP_NAME, f"Operazione non riuscita:\n\n{item[1]}", parent=self.master)
                    return
        except queue.Empty:
            pass
        except (EOFError, OSError):
            pass
        if not self.p.is_alive() and self.q.empty():
            code = self.p.exitcode
            self._cleanup()
            messagebox.showerror(APP_NAME, f"L'elaborazione si è interrotta inaspettatamente (codice {code}).",
                                 parent=self.master)
            return
        self.win.after(150, self._poll)


# ----------------------------------------------------------------------------
# Finestra principale
# ----------------------------------------------------------------------------
class ToolTip:
    """Suggerimento che compare tenendo il mouse fermo su un pulsante."""

    def __init__(self, widget, text, delay=450):
        self.w, self.text, self.delay = widget, text, delay
        self.tip = None
        self._after = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _e=None):
        self._cancel()
        self._after = self.w.after(self.delay, self._show)

    def _cancel(self):
        if self._after:
            self.w.after_cancel(self._after)
            self._after = None

    def _show(self):
        if self.tip or not self.w.winfo_exists():
            return
        x = self.w.winfo_rootx() + 8
        y = self.w.winfo_rooty() + self.w.winfo_height() + 4
        self.tip = tk.Toplevel(self.w)
        self.tip.overrideredirect(True)
        self.tip.attributes("-topmost", True)
        self.tip.geometry(f"+{x}+{y}")
        tk.Label(self.tip, text=self.text, bg="#ffffe1", fg="#222", relief="solid", bd=1,
                 font=("Segoe UI", 9), padx=6, pady=2, justify="left").pack()

    def _hide(self, _e=None):
        self._cancel()
        if self.tip:
            self.tip.destroy()
            self.tip = None


MODES = {
    "view": ("Sfoglia", "Scorri e consulta il documento"),
    "form": ("Compila modulo", "Clicca un campo del modulo e scrivi · Tab: campo successivo · Invio: conferma"),
    "select": ("Seleziona testo", "Trascina sul testo per selezionarlo · tasto destro: copia, taglia, incolla e altro"),
    "text": ("Aggiungi testo", "Clicca o trascina un riquadro dove inserire il testo"),
    "edit": ("Modifica testo", "Trascina un riquadro attorno al testo da sostituire (includi tutta la riga)"),
    "image": ("Immagine", "Trascina il riquadro in cui inserire l'immagine"),
    "redact": ("Omissis", "Trascina il riquadro da omissare: il contenuto sottostante viene eliminato"),
}


class PdfPaperApp:
    def __init__(self, root):
        self.root = root
        self.doc = None
        self.path = None
        self.page_no = 0
        self.zoom = 1.25
        self.dirty = False
        self.history = []
        self._img = None
        self._pix = None
        self._drag = None
        self._ox = self._oy = 10
        self.words = []          # parole della pagina (coordinate non ruotate)
        self._wrects = []        # rettangoli delle parole sul canvas
        self.sel = None          # (indice iniziale, indice finale) della selezione
        self._anchor = None
        self._ctx_pt = None      # punto (pagina visibile) dell'ultimo clic destro / sinistro
        self._hover = None       # posizione del mouse sul canvas
        self._clip_meta = None   # (testo, stile) dell'ultima copia da PdfPaper
        self._gen = 0            # aumenta a ogni modifica (per le cache)
        self.doc_font = None     # carattere scelto dall'utente per il documento aperto
        self.form = {}           # compilazione moduli: {pagina: {"base", "fields", "values", "gen"}}
        self._form_cache, self._form_cache_key = [], None
        self._form_entry = None  # casella di testo aperta sopra un campo
        self._form_commits = 0
        self.mode = tk.StringVar(value="view")
        self.settings = load_settings()
        self.redact_label = tk.BooleanVar(value=self.settings.get("omissis_scritta", True))
        self.redact_fill = tuple(self.settings.get("omissis_sfondo", (0, 0, 0)))
        self.redact_fg = tuple(self.settings.get("omissis_colore_scritta", (1, 1, 1)))
        self.redact_label.trace_add("write", lambda *a: self._save_redact_settings())

        root.title(APP_TITLE)
        root.geometry("1200x800")
        root.minsize(800, 500)
        self._build_menu()
        self._build_toolbar()
        self._build_body()
        self._bind_keys()
        root.protocol("WM_DELETE_WINDOW", self.quit)
        self.mode.trace_add("write", lambda *a: self._update_status())
        self.mode.trace_add("write", lambda *a: self._on_mode_change())
        self._update_status()

    # ---------------------------------------------------------------- UI
    def _build_menu(self):
        m = tk.Menu(self.root)
        f = tk.Menu(m, tearoff=False)
        f.add_command(label="Apri...", accelerator="Ctrl+O", command=self.open_file)
        f.add_command(label="Salva", accelerator="Ctrl+S", command=self.save)
        f.add_command(label="Salva con nome...", accelerator="Ctrl+Maiusc+S", command=self.save_as)
        f.add_separator()
        f.add_command(label="Chiudi documento", command=self.close_doc)
        f.add_command(label="Esci", command=self.quit)
        m.add_cascade(label="File", menu=f)

        e = tk.Menu(m, tearoff=False)
        e.add_command(label="Annulla", accelerator="Ctrl+Z", command=self.undo)
        e.add_separator()
        e.add_command(label="Copia", accelerator="Ctrl+C", command=self.copy_selection)
        e.add_command(label="Taglia", accelerator="Ctrl+X", command=self.cut_selection)
        e.add_command(label="Incolla", accelerator="Ctrl+V", command=self.paste)
        e.add_command(label="Elimina testo selezionato", accelerator="Canc", command=self.delete_selection)
        e.add_command(label="Seleziona tutto il testo della pagina", accelerator="Ctrl+A", command=self.select_all)
        e.add_separator()
        for key in ("select", "text", "edit", "form", "image", "redact"):
            e.add_radiobutton(label=MODES[key][0], variable=self.mode, value=key)
        e.add_separator()
        e.add_checkbutton(label="Scritta \"OMISSIS\" sulle aree omissate", variable=self.redact_label)
        e.add_command(label="Svuota i campi compilati della pagina", command=self.clear_form_page)
        e.add_command(label="Colore sfondo omissis...", command=self.choose_redact_fill)
        e.add_command(label="Colore scritta omissis...", command=self.choose_redact_fg)
        m.add_cascade(label="Modifica", menu=e)

        p = tk.Menu(m, tearoff=False)
        p.add_command(label="Inserisci pagina vuota...", command=self.insert_blank)
        p.add_command(label="Inserisci pagine da altro PDF...", command=self.insert_from_pdf)
        p.add_command(label="Inserisci immagine come nuova pagina...", command=self.insert_image_page)
        p.add_separator()
        p.add_command(label="Ruota a destra di 90°", accelerator="Ctrl+R", command=lambda: self.rotate(90))
        p.add_command(label="Ruota a sinistra di 90°", accelerator="Ctrl+Maiusc+R", command=lambda: self.rotate(-90))
        p.add_command(label="Ruota di 180°", command=lambda: self.rotate(180))
        p.add_separator()
        p.add_command(label="Elimina pagine...", accelerator="Canc", command=self.delete_pages)
        p.add_command(label="Sposta pagina corrente...", command=self.move_page)
        m.add_cascade(label="Pagine", menu=p)

        t = tk.Menu(m, tearoff=False)
        t.add_command(label="OCR (rendi ricercabile)...", command=self.run_ocr)
        t.add_command(label="Comprimi...", command=self.compress)
        t.add_command(label="Estrai testo...", command=self.extract_text)
        t.add_command(label="Rimuovi metadati e dati nascosti...", command=self.sanitize)
        m.add_cascade(label="Strumenti", menu=t)

        v = tk.Menu(m, tearoff=False)
        v.add_command(label="Zoom +", accelerator="Ctrl++", command=lambda: self.set_zoom(self.zoom * 1.2))
        v.add_command(label="Zoom -", accelerator="Ctrl+-", command=lambda: self.set_zoom(self.zoom / 1.2))
        v.add_command(label="Adatta larghezza", command=self.fit_width)
        v.add_command(label="Pagina intera", command=self.fit_page)
        m.add_cascade(label="Visualizza", menu=v)

        h = tk.Menu(m, tearoff=False)
        h.add_command(label="Informazioni", command=self.about)
        m.add_cascade(label="?", menu=h)
        self.root.config(menu=m)

    def _build_toolbar(self):
        """Barra dei pulsanti su tre righe, divisa in gruppi con titolo."""
        bar = ttk.Frame(self.root, padding=(6, 2, 6, 2))
        bar.pack(side="top", fill="x")
        rows = []
        for _ in range(3):
            r = ttk.Frame(bar)
            r.pack(side="top", fill="x", pady=1)
            rows.append(r)

        def group(row, title):
            g = ttk.LabelFrame(rows[row], text=f" {title} ", padding=(4, 0, 4, 3))
            g.pack(side="left", padx=(0, 6), fill="y")
            return g

        def btn(g, text, cmd, tip):
            b = ttk.Button(g, text=text, command=cmd)
            b.pack(side="left", padx=1)
            ToolTip(b, tip)
            return b

        def tool(g, key, text, tip):
            b = ttk.Radiobutton(g, text=text, variable=self.mode, value=key, style="Toolbutton")
            b.pack(side="left", padx=1, ipady=2)
            ToolTip(b, tip)

        # --- riga 1: file, navigazione, zoom, rotazione
        g = group(0, "File")
        btn(g, "📂 Apri", self.open_file, "Apri un PDF (Ctrl+O)")
        btn(g, "💾 Salva", self.save, "Salva il documento (Ctrl+S)")
        btn(g, "Salva con nome", self.save_as, "Salva in un nuovo file (Ctrl+Maiusc+S)")
        btn(g, "↶ Annulla", self.undo, "Annulla l'ultima operazione (Ctrl+Z)")

        g = group(0, "Pagina")
        btn(g, "◀", self.prev_page, "Pagina precedente (PagSu)")
        self.page_var = tk.StringVar(value="0")
        ent = ttk.Entry(g, textvariable=self.page_var, width=5, justify="center")
        ent.pack(side="left", padx=2)
        ent.bind("<Return>", lambda e: self._goto_entry())
        ToolTip(ent, "Scrivi il numero di pagina e premi Invio")
        attach_edit_menu(ent)
        self.page_total = ttk.Label(g, text="/ 0")
        self.page_total.pack(side="left", padx=(0, 4))
        btn(g, "▶", self.next_page, "Pagina successiva (PagGiù)")

        g = group(0, "Zoom")
        btn(g, "−", lambda: self.set_zoom(self.zoom / 1.2), "Riduci (Ctrl+-)")
        self.zoom_lbl = ttk.Label(g, text="125%", width=5, anchor="center")
        self.zoom_lbl.pack(side="left")
        btn(g, "+", lambda: self.set_zoom(self.zoom * 1.2), "Ingrandisci (Ctrl++)")
        btn(g, "↔ Larghezza", self.fit_width, "Adatta alla larghezza della finestra")
        btn(g, "▣ Intera", self.fit_page, "Mostra la pagina intera")

        g = group(0, "Ruota pagina")
        btn(g, "↺ 90°", lambda: self.rotate(-90), "Ruota la pagina corrente a sinistra di 90° (Ctrl+Maiusc+R)")
        btn(g, "↻ 90°", lambda: self.rotate(90), "Ruota la pagina corrente a destra di 90° (Ctrl+R)")
        btn(g, "⟲ 180°", lambda: self.rotate(180), "Capovolgi la pagina corrente (180°)")

        # --- riga 2: strumenti sulla pagina, appunti
        g = group(1, "Strumenti sulla pagina")
        tool(g, "view", "✋ Sfoglia", "Scorri la pagina trascinando (Esc)")
        tool(g, "select", "Aa Seleziona testo", "Trascina sul testo per selezionarlo")
        tool(g, "text", "T+ Aggiungi testo", "Clicca o trascina un riquadro dove scrivere")
        tool(g, "edit", "✎ Modifica testo", "Trascina un riquadro sul testo da sostituire")
        tool(g, "form", "☑ Compila modulo", "Riconosce i campi di un modulo (riquadri, caselle, spunte):\n"
                                           "clicca un campo e scrivi, Tab per passare al successivo")
        tool(g, "image", "🖼 Immagine", "Trascina il riquadro in cui inserire un'immagine")
        tool(g, "redact", "█ Omissis", "Trascina il riquadro da omissare (eliminazione definitiva)")

        g = group(1, "Omissis")
        cb = ttk.Checkbutton(g, text="scritta OMISSIS", variable=self.redact_label)
        cb.pack(side="left", padx=(2, 6))
        ToolTip(cb, "Scrive \"OMISSIS\" sulle aree omissate")
        self.btn_fill = tk.Button(g, text="Sfondo", width=7, relief="groove", cursor="hand2",
                                  command=self.choose_redact_fill)
        self.btn_fill.pack(side="left", padx=1, pady=1)
        ToolTip(self.btn_fill, "Colore di sfondo delle aree omissate")
        self.btn_fg = tk.Button(g, text="Scritta", width=7, relief="groove", cursor="hand2",
                                command=self.choose_redact_fg)
        self.btn_fg.pack(side="left", padx=1, pady=1)
        ToolTip(self.btn_fg, "Colore della scritta OMISSIS")
        self._paint_redact_buttons()

        # --- riga 3: gestione pagine, documento
        g = group(2, "Pagine")
        btn(g, "+ Pagina vuota", self.insert_blank, "Inserisci una o più pagine bianche")
        btn(g, "+ Da altro PDF", self.insert_from_pdf, "Inserisci pagine prese da un altro PDF")
        btn(g, "+ Immagine come pagina", self.insert_image_page, "Inserisci un'immagine come nuova pagina")
        btn(g, "✕ Elimina pagine", self.delete_pages, "Elimina una o più pagine")
        btn(g, "⇅ Sposta pagina", self.move_page, "Sposta la pagina corrente in un'altra posizione")

        g = group(2, "Documento")
        btn(g, "🔍 OCR", self.run_ocr, "Rendi ricercabile un PDF scansionato")
        btn(g, "🗜 Comprimi", self.compress, "Riduci il peso del file")
        btn(g, "📄 Estrai testo", self.extract_text, "Mostra e salva tutto il testo del documento")
        btn(g, "🧹 Pulisci", self.sanitize, "Rimuovi metadati, commenti, allegati e altri dati nascosti\n"
                                          "(consigliato prima di inviare un documento omissato)")
        g = group(2, "Appunti")
        btn(g, "❐ Copia", self.copy_selection, "Copia il testo selezionato (Ctrl+C)")
        btn(g, "✂ Taglia", self.cut_selection, "Copia il testo selezionato e lo elimina dalla pagina (Ctrl+X)")
        btn(g, "📋 Incolla", self.paste, "Incolla testo o immagine dagli appunti (Ctrl+V)\n"
                                         "nel punto dell'ultimo clic sulla pagina")

        ttk.Separator(self.root, orient="horizontal").pack(side="top", fill="x")

    def _build_body(self):
        pw = ttk.PanedWindow(self.root, orient="horizontal")
        pw.pack(fill="both", expand=True)

        left = ttk.Frame(pw, padding=(4, 0))
        ttk.Label(left, text="Pagine").pack(anchor="w")
        self.pages_lb = tk.Listbox(left, width=14, exportselection=False, activestyle="none")
        sb = ttk.Scrollbar(left, command=self.pages_lb.yview)
        self.pages_lb.config(yscrollcommand=sb.set)
        self.pages_lb.pack(side="left", fill="y", expand=True)
        sb.pack(side="left", fill="y")
        self.pages_lb.bind("<<ListboxSelect>>", self._on_list_select)
        pw.add(left, weight=0)

        center = ttk.Frame(pw)
        self.canvas = tk.Canvas(center, bg="#525659", highlightthickness=0)
        vs = ttk.Scrollbar(center, orient="vertical", command=self.canvas.yview)
        hs = ttk.Scrollbar(center, orient="horizontal", command=self.canvas.xview)
        self.canvas.config(yscrollcommand=vs.set, xscrollcommand=hs.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        vs.grid(row=0, column=1, sticky="ns")
        hs.grid(row=1, column=0, sticky="ew")
        center.rowconfigure(0, weight=1)
        center.columnconfigure(0, weight=1)
        pw.add(center, weight=1)

        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_motion)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Button-3>", self._on_right_click)
        self.canvas.bind("<Motion>", self._on_hover)
        self.canvas.bind("<MouseWheel>", self._on_wheel)
        self.canvas.bind("<Button-4>", lambda e: self.canvas.yview_scroll(-3, "units"))
        self.canvas.bind("<Button-5>", lambda e: self.canvas.yview_scroll(3, "units"))

        self.status = ttk.Label(self.root, relief="sunken", anchor="w", padding=(6, 2))
        self.status.pack(side="bottom", fill="x")
        self._show_welcome()

    def _bind_keys(self):
        r = self.root
        r.bind("<Control-o>", lambda e: self.open_file())
        r.bind("<Control-s>", lambda e: self.save())
        r.bind("<Control-S>", lambda e: self.save_as())
        r.bind("<Control-z>", lambda e: self._key(e, self.undo))
        r.bind("<Control-plus>", lambda e: self.set_zoom(self.zoom * 1.2))
        r.bind("<Control-equal>", lambda e: self.set_zoom(self.zoom * 1.2))
        r.bind("<Control-minus>", lambda e: self.set_zoom(self.zoom / 1.2))
        r.bind("<Next>", lambda e: self._key(e, self.next_page))
        r.bind("<Prior>", lambda e: self._key(e, self.prev_page))
        r.bind("<Escape>", lambda e: self._escape())
        r.bind("<Control-r>", lambda e: self.rotate(90))
        r.bind("<Control-R>", lambda e: self.rotate(-90))
        r.bind("<Control-c>", lambda e: self._key(e, self.copy_selection))
        r.bind("<Control-x>", lambda e: self._key(e, self.cut_selection))
        r.bind("<Control-v>", lambda e: self._key(e, lambda: self.paste(use_hover=True)))
        r.bind("<Control-a>", lambda e: self._key(e, self.select_all))
        r.bind("<Delete>", lambda e: self._key(e, self.delete_selection))
        self.pages_lb.bind("<Delete>", lambda e: (self.delete_pages(), "break")[1])

    def _show_welcome(self):
        self.canvas.delete("all")
        self.canvas.create_text(20, 20, anchor="nw", fill="#e0e0e0", font=("Segoe UI", 13),
                                text="Apri un PDF con  File → Apri  (Ctrl+O)")

    def _update_status(self):
        hint = MODES[self.mode.get()][1]
        if not self.doc:
            self.status.config(text=f"Nessun documento aperto · {hint}")
            return
        name = os.path.basename(self.path) if self.path else "(nuovo)"
        star = " *" if self.dirty else ""
        self.status.config(text=f"{name}{star} · pagina {self.page_no + 1}/{len(self.doc)} · "
                                f"zoom {self.zoom * 100:.0f}% · {hint}")
        self.root.title(f"{name}{star} - {APP_TITLE}")

    # ---------------------------------------------------------------- documento
    def _need_doc(self):
        if not self.doc:
            messagebox.showinfo(APP_NAME, "Apri prima un documento PDF.")
            return False
        return True

    def _confirm_discard(self):
        self._form_close_editor(True)
        if self.doc and self.dirty:
            r = messagebox.askyesnocancel(APP_NAME, "Il documento è stato modificato. Salvare le modifiche?")
            if r is None:
                return False
            if r:
                return self.save()
        return True

    def open_file(self, path=None):
        if not self._confirm_discard():
            return
        if not path:
            path = filedialog.askopenfilename(title="Apri PDF", filetypes=[("PDF", "*.pdf"), ("Tutti", "*.*")])
        if not path:
            return
        try:
            with open(path, "rb") as fh:  # in memoria: il file resta libero per il salvataggio
                doc = fitz.open("pdf", fh.read())
            if doc.needs_pass:
                pwd = simpledialog.askstring(APP_NAME, "Il PDF è protetto. Password:", show="*")
                if not pwd or not doc.authenticate(pwd):
                    messagebox.showerror(APP_NAME, "Password errata.")
                    return
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"Impossibile aprire il file:\n\n{exc}")
            return
        self.doc, self.path = doc, path
        self.page_no, self.history, self.dirty = 0, [], False
        self.doc_font, self._clip_meta = None, None
        self.form, self._form_entry = {}, None
        self._gen += 1
        self.refresh(rebuild_list=True)
        self.root.after(50, self.fit_width)

    def close_doc(self):
        if not self._confirm_discard():
            return
        self.doc, self.path, self.history, self.dirty = None, None, [], False
        self.doc_font, self._clip_meta = None, None
        self.form, self._form_entry = {}, None
        self.pages_lb.delete(0, "end")
        self.page_total.config(text="/ 0")
        self.page_var.set("0")
        self._show_welcome()
        self.root.title(APP_TITLE)
        self._update_status()

    def _pdf_bytes(self):
        data = self.doc.tobytes(garbage=3, deflate=True)
        try:  # su una copia: i caratteri di Windows inseriti vengono ridotti ai soli glifi usati
            tmp = fitz.open("pdf", data)
            tmp.subset_fonts()
            data = tmp.tobytes(garbage=3, deflate=True)
        except Exception:
            pass
        return data

    def save(self):
        self._form_close_editor(True)
        if not self._need_doc():
            return False
        if not self.path:
            return self.save_as()
        return self._write(self.path)

    def save_as(self):
        self._form_close_editor(True)
        if not self._need_doc():
            return False
        initial = os.path.splitext(os.path.basename(self.path or "documento.pdf"))[0] + "_modificato.pdf"
        path = filedialog.asksaveasfilename(title="Salva con nome", defaultextension=".pdf",
                                            initialfile=initial, filetypes=[("PDF", "*.pdf")])
        if not path:
            return False
        if self._write(path):
            self.path = path
            self._update_status()
            return True
        return False

    def _write(self, path):
        try:
            data = self._pdf_bytes()
            tmp = path + ".tmp"
            with open(tmp, "wb") as fh:
                fh.write(data)
            os.replace(tmp, path)
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"Salvataggio non riuscito:\n\n{exc}")
            return False
        self.dirty = False
        self._update_status()
        self.status.config(text=self.status.cget("text") + f" · salvato ({human_size(len(data))})")
        return True

    # ---------------------------------------------------------------- undo
    def _checkpoint(self):
        data = self.doc.tobytes(garbage=1) if self.form else self.doc.tobytes()
        self.history.append((data, self._form_snapshot()))
        if len(self.history) > MAX_UNDO:
            self.history.pop(0)

    def _changed(self, rebuild_list=False):
        self.dirty = True
        self._gen += 1
        if rebuild_list:  # pagine aggiunte/tolte o documento sostituito: i campi compilati restano fissati
            self.form = {}
        self.refresh(rebuild_list=rebuild_list)

    def undo(self):
        if not self.doc or not self.history:
            return
        entry = self.history.pop()
        data, fstate = entry if isinstance(entry, tuple) else (entry, None)
        self._form_close_editor(False)
        self.doc = fitz.open("pdf", data)
        self.page_no = min(self.page_no, len(self.doc) - 1)
        self._changed(rebuild_list=True)
        self.form = fstate or {}
        for st in self.form.values():
            st["gen"] = self._gen
        self._draw_form_overlay()

    # ---------------------------------------------------------------- visualizzazione
    def refresh(self, rebuild_list=False):
        if self._form_entry is not None:
            self._form_close_editor(True)  # salva il campo in modifica prima di ridisegnare
        if not self.doc:
            return
        n = len(self.doc)
        self.page_no = max(0, min(self.page_no, n - 1))
        if rebuild_list or self.pages_lb.size() != n:
            self.pages_lb.delete(0, "end")
            for i in range(n):
                self.pages_lb.insert("end", f"  Pagina {i + 1}")
        self.pages_lb.selection_clear(0, "end")
        self.pages_lb.selection_set(self.page_no)
        self.pages_lb.see(self.page_no)
        self.page_var.set(str(self.page_no + 1))
        self.page_total.config(text=f"/ {n}")
        self.zoom_lbl.config(text=f"{self.zoom * 100:.0f}%")

        page = self.doc[self.page_no]
        pix = page.get_pixmap(matrix=fitz.Matrix(self.zoom, self.zoom), alpha=False)
        self._pix = pix
        self._img = tk.PhotoImage(data=pix.tobytes("ppm"))
        self.canvas.delete("all")
        cw = self.canvas.winfo_width()
        self._ox = max(10, (cw - pix.width) // 2)
        self._oy = 10
        self.canvas.create_rectangle(self._ox + 3, self._oy + 3, self._ox + pix.width + 3,
                                     self._oy + pix.height + 3, fill="#333", outline="")
        self.canvas.create_image(self._ox, self._oy, image=self._img, anchor="nw")
        self.canvas.config(scrollregion=(0, 0, pix.width + 2 * self._ox, pix.height + 20))
        self._load_words(page)
        self._update_status()
        if self.mode.get() == "form":
            self._draw_form_overlay()

    def goto(self, n):
        if self.doc and 0 <= n < len(self.doc):
            self.page_no = n
            self.refresh()
            self.canvas.yview_moveto(0)

    def next_page(self):
        if self.doc:
            self.goto(self.page_no + 1)

    def prev_page(self):
        if self.doc:
            self.goto(self.page_no - 1)

    def _goto_entry(self):
        try:
            self.goto(int(self.page_var.get()) - 1)
        except ValueError:
            pass

    def _on_list_select(self, _e):
        sel = self.pages_lb.curselection()
        if sel and sel[0] != self.page_no:
            self.goto(sel[0])

    def set_zoom(self, z):
        self.zoom = max(0.2, min(6.0, z))
        keep = self.sel
        self.refresh()
        if keep and keep[1] < len(self.words):  # lo zoom non cancella la selezione
            self._set_selection(keep)

    def fit_width(self):
        if not self.doc:
            return
        cw = max(self.canvas.winfo_width() - 40, 200)
        self.set_zoom(cw / self.doc[self.page_no].rect.width)

    def fit_page(self):
        if not self.doc:
            return
        r = self.doc[self.page_no].rect
        cw = max(self.canvas.winfo_width() - 40, 200)
        ch = max(self.canvas.winfo_height() - 30, 200)
        self.set_zoom(min(cw / r.width, ch / r.height))

    def _on_wheel(self, e):
        if e.state & 0x0004:  # Ctrl: zoom
            self.set_zoom(self.zoom * (1.1 if e.delta > 0 else 1 / 1.1))
        else:
            self.canvas.yview_scroll(int(-e.delta / 40) or (-1 if e.delta > 0 else 1), "units")

    # ---------------------------------------------------------------- mouse
    def _on_press(self, e):
        if not self.doc:
            return
        self._form_close_editor(True)
        self.canvas.focus_set()
        x, y = self.canvas.canvasx(e.x), self.canvas.canvasy(e.y)
        self._ctx_pt = self._canvas_to_vis(x, y)
        mode = self.mode.get()
        if mode == "form":
            self._form_click(x, y)
            return
        if mode == "view":
            self.canvas.scan_mark(e.x, e.y)
            self._drag = ("pan",)
            return
        if mode == "select":
            i = self._nearest_word(x, y, strict=True)
            if i is None:
                self._set_selection(None)
                self._drag = ("sel-empty",)
                return
            self._anchor = i
            self._set_selection((i, i))
            self._drag = ("sel",)
            return
        color = {"redact": "#000000", "image": "#1565c0"}.get(mode, "#d32f2f")
        rid = self.canvas.create_rectangle(x, y, x, y, outline=color, width=2, dash=(4, 2))
        self._drag = ("rect", x, y, rid)

    def _on_motion(self, e):
        if not self._drag:
            return
        kind = self._drag[0]
        x, y = self.canvas.canvasx(e.x), self.canvas.canvasy(e.y)
        if kind == "pan":
            self.canvas.scan_dragto(e.x, e.y, gain=1)
        elif kind == "sel-empty" and self.words:
            # trascinamento iniziato fuori dal testo: si parte dalla parola più vicina
            self._anchor = self._nearest_word(x, y)
            self._drag = ("sel",)
        elif kind == "sel" and self._anchor is not None:
            i = self._nearest_word(x, y)
            if i is not None:
                self._set_selection((min(self._anchor, i), max(self._anchor, i)))
        elif kind == "rect":
            _, x0, y0, rid = self._drag
            self.canvas.coords(rid, x0, y0, x, y)

    def _on_release(self, e):
        drag, self._drag = self._drag, None
        if drag and drag[0] == "sel":
            n = self._sel_count()
            if n:
                self.status.config(text=f"{n} parole selezionate · Ctrl+C copia · tasto destro per altre operazioni")
            return
        if not drag or drag[0] != "rect":
            return
        _, x0, y0, rid = drag
        x1, y1 = self.canvas.canvasx(e.x), self.canvas.canvasy(e.y)
        small = abs(x1 - x0) < 6 and abs(y1 - y0) < 6
        mode = self.mode.get()
        if small:
            if mode != "text":
                self.canvas.delete(rid)
                return
            x1, y1 = x0 + 260 * self.zoom, y0 + 60 * self.zoom  # riquadro predefinito
        rect = self._canvas_to_pdf(x0, y0, x1, y1)
        if rect is None:
            self.canvas.delete(rid)
            return
        handler = {"text": self._do_add_text, "edit": self._do_edit_text,
                   "image": self._do_add_image, "redact": self._do_redact}[mode]
        handler(rect)
        self.canvas.delete(rid)

    def _on_hover(self, e):
        self._hover = (self.canvas.canvasx(e.x), self.canvas.canvasy(e.y))

    def _escape(self):
        self._set_selection(None)
        self.mode.set("view")

    def _key(self, e, action):
        """Scorciatoie degli appunti: nei campi di testo lascia il comportamento normale."""
        if isinstance(e.widget, (tk.Entry, ttk.Entry, tk.Text, ttk.Spinbox, ttk.Combobox, tk.Listbox)):
            return None
        action()
        return "break"

    def _canvas_to_pdf(self, x0, y0, x1, y1):
        page = self.doc[self.page_no]
        r = fitz.Rect((min(x0, x1) - self._ox) / self.zoom, (min(y0, y1) - self._oy) / self.zoom,
                      (max(x0, x1) - self._ox) / self.zoom, (max(y0, y1) - self._oy) / self.zoom)
        r = r & page.rect  # limita alla pagina visibile
        if r.is_empty or r.width < 2 or r.height < 2:
            return None
        return (r * page.derotation_matrix).normalize()  # coordinate non ruotate

    def _canvas_to_vis(self, x, y):
        """Punto del canvas -> punto sulla pagina come la si vede (None se fuori pagina)."""
        if not self.doc:
            return None
        p = fitz.Point((x - self._ox) / self.zoom, (y - self._oy) / self.zoom)
        return p if p in self.doc[self.page_no].rect else None

    def _vis_rect_to_canvas(self, r):
        return (r.x0 * self.zoom + self._ox, r.y0 * self.zoom + self._oy,
                r.x1 * self.zoom + self._ox, r.y1 * self.zoom + self._oy)

    # ---------------------------------------------------------------- selezione del testo
    def _load_words(self, page):
        """Parole della pagina; le coordinate di PyMuPDF sono riferite alla pagina NON ruotata."""
        try:
            self.words = page.get_text("words", sort=True)
        except Exception:
            self.words = []
        rot = page.rotation_matrix
        self._wrects = [self._vis_rect_to_canvas(fitz.Rect(w[:4]) * rot) for w in self.words]
        self.sel = None
        self._anchor = None

    def _nearest_word(self, x, y, strict=False):
        if not self._wrects:
            return None
        best, best_d = None, None
        for i, (x0, y0, x1, y1) in enumerate(self._wrects):
            dx = max(x0 - x, 0, x - x1)
            dy = max(y0 - y, 0, y - y1)
            if dx == 0 and dy == 0:
                return i
            d = dx + dy * 4  # preferisce le parole sulla stessa riga
            if best_d is None or d < best_d:
                best, best_d = i, d
        if strict and best_d > 8:
            return None
        return best

    def _sel_count(self):
        return 0 if not self.sel else self.sel[1] - self.sel[0] + 1

    def _set_selection(self, sel):
        self.sel = sel
        self.canvas.delete("sel")
        if not sel:
            return
        for i in range(sel[0], sel[1] + 1):
            x0, y0, x1, y1 = self._wrects[i]
            if sys.platform == "darwin":  # macOS non supporta il retino: solo bordo
                self.canvas.create_rectangle(x0 - 1, y0, x1 + 2, y1, outline="#3d8ef0", tags="sel")
            else:
                self.canvas.create_rectangle(x0 - 1, y0, x1 + 2, y1, fill="#3d8ef0", stipple="gray50",
                                             outline="", tags="sel")

    def _selected_words(self):
        return [] if not self.sel else self.words[self.sel[0]:self.sel[1] + 1]

    def _selected_text(self):
        out, last = [], None
        for w in self._selected_words():
            key = (w[5], w[6])
            if last is not None:
                out.append("\n" if key != last else " ")
            out.append(w[4])
            last = key
        return "".join(out)

    def _selection_line_rects(self):
        """Un rettangolo (coordinate non ruotate) per ogni riga selezionata."""
        lines = {}
        for w in self._selected_words():
            key = (w[5], w[6])
            r = fitz.Rect(w[:4])
            lines[key] = lines[key] | r if key in lines else r
        return list(lines.values())

    def select_all(self):
        if not self.doc or not self.words:
            self.status.config(text="Nessun testo in questa pagina (se è una scansione, esegui l'OCR)")
            return
        if self.mode.get() != "select":
            self.mode.set("select")
        self._set_selection((0, len(self.words) - 1))
        self.status.config(text=f"Selezionate tutte le {len(self.words)} parole della pagina")

    def _need_selection(self):
        if self._sel_count():
            return True
        self.status.config(text="Nessun testo selezionato: usa lo strumento 'Seleziona testo'")
        return False

    def copy_selection(self):
        if not self.doc or not self._need_selection():
            return False
        text = self._selected_text()
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        rects = self._selection_line_rects()
        self._clip_meta = (text, self._detect_style(rects[0]))
        self.status.config(text=f"Copiato negli appunti: {len(text)} caratteri")
        return True

    def cut_selection(self):
        if self.copy_selection():
            self.delete_selection(status="Testo tagliato: ora puoi incollarlo")

    def delete_selection(self, status="Testo eliminato"):
        if not self.doc or not self._need_selection():
            return
        page = self.doc[self.page_no]
        rects = self._selection_line_rects()
        fill = self._bg_color(rects[0])
        self._checkpoint()
        for r in rects:
            # riquadro leggermente ridotto per non toccare le righe vicine
            h = r.height
            page.add_redact_annot(fitz.Rect(r.x0 + 0.3, r.y0 + h * 0.2, r.x1 - 0.3, r.y1 - h * 0.2), fill=fill)
        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
        self._changed()
        self.status.config(text=status)

    def edit_selection(self):
        if not self.doc or not self._need_selection():
            return
        rects = self._selection_line_rects()
        union = rects[0]
        for r in rects[1:]:
            union |= r
        self._do_edit_text(union + (-1, -1, 1, 1))

    def redact_selection(self):
        if not self.doc or not self._need_selection():
            return
        page = self.doc[self.page_no]
        self._checkpoint()
        for r in self._selection_line_rects():
            self._add_redaction(page, r + (-1, -1, 1, 1))
        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_PIXELS)
        self._changed()

    def _bg_color(self, rect):
        """Colore dello sfondo appena fuori dall'angolo dell'area, letto dall'immagine mostrata."""
        try:
            page = self.doc[self.page_no]
            vr = fitz.Rect(rect) * page.rotation_matrix
            pix = self._pix
            x = min(max(int(vr.x0 * self.zoom) - 2, 0), pix.width - 1)
            y = min(max(int(vr.y0 * self.zoom) - 2, 0), pix.height - 1)
            return tuple(v / 255 for v in pix.pixel(x, y)[:3])
        except Exception:
            return (1, 1, 1)

    # ---------------------------------------------------------------- incolla
    def _paste_point(self, use_hover=False):
        """Dove incollare: con Ctrl+V il punto del mouse sulla pagina; poi l'ultimo clic; poi in alto a sinistra."""
        if use_hover and self._hover:
            p = self._canvas_to_vis(*self._hover)
            if p is not None:
                return p
        if self._ctx_pt is not None:
            return self._ctx_pt
        return fitz.Point(36, 36)

    def paste(self, at=None, use_hover=False):
        if not self._need_doc():
            return
        pt = at if at is not None else self._paste_point(use_hover)
        # 1) immagine negli appunti (screenshot, immagine copiata) o file immagine copiati
        try:
            from PIL import ImageGrab
            data = ImageGrab.grabclipboard()
        except Exception:
            data = None
        if data is not None:
            if isinstance(data, list):
                imgs = [f for f in data if os.path.splitext(f)[1].lower() in
                        (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff")]
                if imgs:
                    self._insert_image_at(pt, filename=imgs[0])
                    return
            else:
                buf = io.BytesIO()
                data.convert("RGBA" if data.mode in ("RGBA", "LA", "P") else "RGB").save(buf, "PNG")
                self._insert_image_at(pt, stream=buf.getvalue(), px_size=data.size)
                return
        # 2) testo
        try:
            text = self.root.clipboard_get()
        except tk.TclError:
            text = ""
        if not text.strip():
            self.status.config(text="Gli appunti sono vuoti")
            return
        page = self.doc[self.page_no]
        if self._clip_meta and self._clip_meta[0] == text:
            style = self._clip_meta[1]
        else:
            probe = (fitz.Rect(pt.x, pt.y, pt.x + 50, pt.y + 12) * page.derotation_matrix).normalize()
            style = self._detect_style(probe, near=True)
        size, color, font = style["size"], style["color"], style["font"]
        W, H = page.rect.width, page.rect.height
        x = min(pt.x, W - 80)
        vis = fitz.Rect(x, pt.y, W - 18, H - 10)
        if vis.height < size * 1.5:
            vis.y0 = max(10, H - 10 - size * 3)
        rect = (vis * page.derotation_matrix).normalize()
        self._checkpoint()
        used = self._insert_fit(page, rect, text, size, font, color, 0)
        self._changed()
        msg = "Testo incollato"
        if used < size:
            msg += f" (ridotto a {used} pt per entrare nella pagina)"
        self.status.config(text=msg + " · per cambiarlo usa 'Modifica testo'")

    def _insert_image_at(self, pt, filename=None, stream=None, px_size=None):
        page = self.doc[self.page_no]
        W, H = page.rect.width, page.rect.height
        try:
            if px_size is None:
                pm = fitz.Pixmap(filename) if filename else fitz.Pixmap(stream)
                px_size = (pm.width, pm.height)
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"Immagine non leggibile:\n\n{exc}")
            return
        w, h = px_size[0] * 0.75, px_size[1] * 0.75  # pixel a 96 dpi -> punti
        x, y = pt.x, pt.y
        if W - x - 18 < 60:
            x = max(18, W - 18 - w)
        k = min(1.0, (W - x - 18) / w, (H - y - 18) / h) if w and h else 1.0
        if k <= 0.05:
            y = max(18, H - 18 - h)
            k = min(1.0, (W - x - 18) / w, (H - y - 18) / h)
        vis = fitz.Rect(x, y, x + w * k, y + h * k)
        rect = (vis * page.derotation_matrix).normalize()
        self._checkpoint()
        try:
            page.insert_image(rect, filename=filename, stream=stream, keep_proportion=True,
                              rotate=page.rotation)
        except Exception as exc:
            self.history.pop()
            messagebox.showerror(APP_NAME, f"Impossibile inserire l'immagine:\n\n{exc}")
            return
        self._changed()
        self.status.config(text="Immagine incollata · Ctrl+Z per annullare")

    # ---------------------------------------------------------------- menu del tasto destro
    def _on_right_click(self, e):
        if not self.doc:
            return
        self.canvas.focus_set()
        x, y = self.canvas.canvasx(e.x), self.canvas.canvasy(e.y)
        pt = self._canvas_to_vis(x, y)
        if pt is not None:
            self._ctx_pt = pt
        has_sel = bool(self._sel_count())
        on = "normal" if has_sel else "disabled"
        m = tk.Menu(self.root, tearoff=False)
        if self.mode.get() == "form":
            self._form_close_editor(True)
            fi = self._form_field_at(x, y)
            if fi is not None:
                fname = self._form_fields_current()[fi].get("label") or "campo"
                m.add_command(label=f"✎  Scrivi in «{fname}»", command=lambda: self._form_click(x, y))
                m.add_command(label=f"✕  Svuota «{fname}»", state="normal" if self._form_value(fi) else "disabled",
                              command=lambda: self._form_set(fi, ""))
                m.add_separator()
        m.add_command(label="❐  Copia", accelerator="Ctrl+C", state=on, command=self.copy_selection)
        m.add_command(label="✂  Taglia", accelerator="Ctrl+X", state=on, command=self.cut_selection)
        m.add_command(label="📋  Incolla qui", accelerator="Ctrl+V",
                      command=lambda: self.paste(at=pt if pt is not None else self._ctx_pt))
        m.add_command(label="Elimina testo selezionato", accelerator="Canc", state=on,
                      command=self.delete_selection)
        m.add_command(label="Seleziona tutto il testo della pagina", accelerator="Ctrl+A",
                      command=self.select_all)
        m.add_separator()
        m.add_command(label="✎  Modifica testo selezionato...", state=on, command=self.edit_selection)
        m.add_command(label="█  Omissis sul testo selezionato", state=on, command=self.redact_selection)
        if pt is not None:
            m.add_command(label="T+  Aggiungi testo qui...", command=lambda: self._add_text_at(pt))
            m.add_command(label="🖼  Inserisci immagine qui...", command=lambda: self._add_image_at(pt))
        m.add_separator()
        m.add_command(label="↻  Ruota pagina a destra di 90°", accelerator="Ctrl+R",
                      command=lambda: self.rotate(90))
        m.add_command(label="↺  Ruota pagina a sinistra di 90°", accelerator="Ctrl+Maiusc+R",
                      command=lambda: self.rotate(-90))
        m.add_command(label="⟲  Ruota pagina di 180°", command=lambda: self.rotate(180))
        m.add_separator()
        m.add_command(label="+  Inserisci pagina vuota dopo questa", command=self._blank_after)
        m.add_command(label="✕  Elimina questa pagina", command=self._delete_current)
        try:
            m.tk_popup(e.x_root, e.y_root)
        finally:
            m.grab_release()

    def _add_text_at(self, pt):
        page = self.doc[self.page_no]
        vis = fitz.Rect(pt.x, pt.y, min(pt.x + 260, page.rect.width - 10), min(pt.y + 60, page.rect.height - 5))
        if vis.width > 10 and vis.height > 5:
            self._do_add_text((vis * page.derotation_matrix).normalize())

    def _add_image_at(self, pt):
        path = filedialog.askopenfilename(title="Scegli immagine", filetypes=[
            ("Immagini", "*.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff"), ("Tutti", "*.*")])
        if path:
            self._insert_image_at(pt, filename=path)

    def _blank_after(self):
        ref = self.doc[self.page_no].rect
        self._checkpoint()
        self.doc.new_page(pno=self.page_no + 1, width=ref.width, height=ref.height)
        self.page_no += 1
        self._changed(rebuild_list=True)

    def _delete_current(self):
        if len(self.doc) <= 1:
            messagebox.showwarning(APP_NAME, "Non puoi eliminare l'unica pagina del documento.")
            return
        if not messagebox.askyesno(APP_NAME, f"Eliminare la pagina {self.page_no + 1}?"):
            return
        self._checkpoint()
        self.doc.delete_page(self.page_no)
        self.page_no = min(self.page_no, len(self.doc) - 1)
        self._changed(rebuild_list=True)

    # ---------------------------------------------------------------- stile del testo (carattere, dimensione, colore)
    def _word_lines(self, page, area):
        """Righe di testo nell'area: [(rettangolo, testo)] in coordinate non ruotate."""
        groups = {}
        for w in page.get_text("words", clip=area):
            key = (w[5], w[6])
            r = fitz.Rect(w[:4])
            if key in groups:
                groups[key][0] |= r
                groups[key][1].append(w[4])
            else:
                groups[key] = [r, [w[4]]]
        return [(r, " ".join(t)) for r, t in groups.values()]

    def _scan_crop(self, page, rect):
        """Immagine (PIL, 300 dpi) di un'area della pagina come la si vede."""
        from PIL import Image
        if page.rotation == 0:
            pix = page.get_pixmap(dpi=SCAN_DPI, clip=rect, alpha=False)
            return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        key = (self._gen, self.page_no)
        if getattr(self, "_scan_key", None) != key:
            pix = page.get_pixmap(dpi=SCAN_DPI, alpha=False)
            self._scan_img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            self._scan_key = key
        k = SCAN_DPI / 72
        vr = fitz.Rect(rect) * page.rotation_matrix
        return self._scan_img.crop((int(vr.x0 * k), int(vr.y0 * k), int(vr.x1 * k) + 1, int(vr.y1 * k) + 1))

    def _analyze_lines(self, page, lines):
        out = []
        for r, text in lines[:10]:
            try:
                out.append(analyze_line(self._scan_crop(page, r + (-2, -2, 2, 2)), SCAN_DPI, text))
            except Exception:
                pass
        return out

    def _page_stem(self, page):
        """Spessore tipico delle aste nel testo della pagina (riferimento per riconoscere il grassetto)."""
        key = (self._gen, self.page_no)
        if getattr(self, "_stem_key", None) != key:
            lines = self._word_lines(page, page.rect * page.derotation_matrix)
            lines = [ln for ln in lines if len(ln[1]) >= 12]
            step = max(1, len(lines) // 12)
            res = [r for r in self._analyze_lines(page, lines[::step][:12]) if r]
            self._stem_val = _median([r["stem_em"] for r in res]) if len(res) >= 3 else None
            self._stem_key = key
        return self._stem_val

    def _detect_style(self, rect, near=False):
        """Stile da proporre per scrivere in 'rect'.
        PDF digitali: carattere vero del documento. Scansioni: stima dall'immagine (dimensione, grassetto,
        famiglia con/senza grazie, colore). Con near=True cerca le righe vicine (per il testo nuovo)."""
        default = dict(font=self.doc_font or make_font("arial"), size=11.0, color=(0, 0, 0), note=None)
        if not self.doc:
            return default
        page = self.doc[self.page_no]
        prect = page.rect * page.derotation_matrix
        area = fitz.Rect(prect.x0, rect.y0 - 70, prect.x1, rect.y1 + 70) & prect if near else fitz.Rect(rect)
        try:
            spans = []
            for block in page.get_text("dict", clip=area).get("blocks", []):
                for line in block.get("lines", []):
                    for sp in line.get("spans", []):
                        if sp["text"].strip():
                            spans.append(sp)
        except Exception:
            spans = []
        native = [sp for sp in spans if "glyphless" not in sp["font"].lower()]
        center = fitz.Point((rect.x0 + rect.x1) / 2, rect.y0)
        if native:
            if near:
                sp = min(native, key=lambda s: abs(fitz.Rect(s["bbox"]).y0 - center.y) +
                         0.2 * abs(fitz.Rect(s["bbox"]).x0 - center.x))
            else:  # lo stile con più caratteri nell'area
                count = {}
                for s in native:
                    k = (s["font"], round(s["size"], 1), s["color"], s["flags"])
                    count[k] = count.get(k, 0) + len(s["text"])
                k = max(count, key=count.get)
                sp = next(s for s in native if (s["font"], round(s["size"], 1), s["color"], s["flags"]) == k)
            fc, exact, raw, family = font_from_pdf(sp["font"], sp["flags"])
            c = sp["color"]
            size = round(sp["size"] * 2) / 2
            if self.doc_font:
                fc = self.doc_font
            if fc.fontfile or (exact and family in ("arial", "times", "courier")):
                note = f"Stile del documento: {raw}, {size:g} pt."
            else:
                note = f"Stile del documento: {raw}, {size:g} pt (carattere non presente sul PC: proposto il più simile)."
            return dict(font=fc, size=size, note=note,
                        color=(((c >> 16) & 255) / 255, ((c >> 8) & 255) / 255, (c & 255) / 255))
        # scansione: righe dal livello OCR, oppure divise dall'immagine
        lines = self._word_lines(page, area)
        if near and lines:
            lines.sort(key=lambda ln: abs(ln[0].y0 - center.y))
            lines = lines[:4]
        if lines:
            results = self._analyze_lines(page, lines)
        elif not near:
            try:
                results = [analyze_line(img) for img in split_lines(self._scan_crop(page, rect))[:10]]
            except Exception:
                results = []
        else:
            results = []
        st = combine_styles(results, self._page_stem(page) if results else None)
        if not st:
            return default
        names = {"times": "con grazie (tipo Times)", "arial": "senza grazie (tipo Arial)",
                 "courier": "a spaziatura fissa (tipo Courier)"}
        fc = self.doc_font or make_font(st["family"], st["bold"])
        chosen = " · carattere scelto da te per questo documento" if self.doc_font else ""
        note = (f"Stima dalla scansione: {st['size']:g} pt, {'grassetto' if st['bold'] else 'normale'}, "
                f"carattere {names[st['family']]}{chosen}. Controlla e correggi se serve: la tua scelta del "
                f"carattere verrà ricordata per questo documento.")
        return dict(font=fc, size=st["size"], color=st["color"], note=note)

    def _remember_font(self, style, res):
        """Se l'utente cambia il carattere proposto, lo ricorda per il resto del documento."""
        if res and style.get("font") is not None and res["font"].label != style["font"].label:
            self.doc_font = res["font"]

    # ---------------------------------------------------------------- compilazione dei moduli
    def _form_fields_current(self):
        pno = self.page_no
        st = self.form.get(pno)
        if st:
            return st["fields"]
        key = (self._gen, pno)
        if self._form_cache_key != key:
            try:
                self._form_cache = page_form_fields(self.doc[pno])
            except Exception:
                self._form_cache = []
            self._form_cache_key = key
        return self._form_cache

    def _form_value(self, i):
        return self.form.get(self.page_no, {}).get("values", {}).get(i, "")

    def _field_canvas_rect(self, r):
        page = self.doc[self.page_no]
        return self._vis_rect_to_canvas(fitz.Rect(r) * page.rotation_matrix)

    def _on_mode_change(self):
        self._form_close_editor(True)
        if self.mode.get() == "form" and self.doc:
            self._draw_form_overlay()
        else:
            self.canvas.delete("form")

    def _draw_form_overlay(self):
        self.canvas.delete("form")
        if not self.doc or self.mode.get() != "form":
            return
        fields = self._form_fields_current()
        colors = {"text": "#1e88e5", "comb": "#43a047", "check": "#fb8c00"}
        for i, f in enumerate(fields):
            col = colors[f["kind"]]
            empty = not self._form_value(i)
            for n, c in enumerate(f["cells"]):
                if f["kind"] == "comb" and n in f["fixed"]:
                    continue
                x0, y0, x1, y1 = self._field_canvas_rect(c)
                if empty and sys.platform != "darwin":
                    self.canvas.create_rectangle(x0, y0, x1, y1, outline=col, width=1.5, fill=col,
                                                 stipple="gray12", tags="form")
                else:
                    self.canvas.create_rectangle(x0, y0, x1, y1, outline=col, width=1, tags="form")
        if fields:
            done = sum(1 for i in range(len(fields)) if self._form_value(i))
            self.status.config(text=f"Modulo: {len(fields)} campi riconosciuti in questa pagina ({done} compilati) · "
                                    f"clicca un campo per scrivere · Tab: campo successivo · Invio: conferma")
        else:
            self.status.config(text="Nessun campo da compilare riconosciuto in questa pagina")

    def _form_field_at(self, x, y):
        for i, f in enumerate(self._form_fields_current()):
            x0, y0, x1, y1 = self._field_canvas_rect(f["rect"])
            if x0 - 2 <= x <= x1 + 2 and y0 - 2 <= y <= y1 + 2:
                return i
        return None

    def _form_click(self, x, y):
        i = self._form_field_at(x, y)
        if i is None:
            return
        f = self._form_fields_current()[i]
        if f["kind"] == "check":
            self._form_set(i, "" if self._form_value(i) else "X")
        else:
            self._form_open_editor(i)

    def _field_hint(self, f):
        name = f.get("label") or {"text": "campo di testo", "comb": "caselle", "check": "casella"}[f["kind"]]
        if f["kind"] == "comb":
            free = len(f["cells"]) - len(f["fixed"])
            extra = ""
            if f["fixed"]:
                extra = " · già stampati: " + " ".join(f["fixed"][k] for k in sorted(f["fixed"]))
            return f"{name} · {free} caselle{extra}"
        return name

    def _ensure_visible(self, y0, y1):
        top = self.canvas.canvasy(0)
        h = self.canvas.winfo_height()
        sr = self.canvas.cget("scrollregion").split()
        total = float(sr[3]) if len(sr) == 4 else 0
        if total and (y0 < top or y1 > top + h):
            self.canvas.yview_moveto(max(0.0, (y0 - h / 3) / total))

    def _form_open_editor(self, i):
        self._form_close_editor(True)
        fields = self._form_fields_current()
        if not 0 <= i < len(fields):
            return
        f = fields[i]
        x0, y0, x1, y1 = self._field_canvas_rect(f["rect"])
        self._ensure_visible(y0, y1)
        h = max(y1 - y0, 16)
        var = tk.StringVar(value=self._form_value(i))
        ent = tk.Entry(self.canvas, textvariable=var, font=("Segoe UI", -max(10, int(h * 0.6))),
                       relief="solid", bd=1, bg="#fffde7", highlightthickness=2,
                       highlightcolor="#1565c0", highlightbackground="#1565c0")
        win = self.canvas.create_window(x0, y0, anchor="nw", window=ent, width=max(x1 - x0, 70), height=h,
                                        tags="formedit")
        self._form_entry = (ent, win, i, var)
        ent.bind("<Return>", lambda e: (self._form_close_editor(True), "break")[1])
        ent.bind("<KP_Enter>", lambda e: (self._form_close_editor(True), "break")[1])
        ent.bind("<Tab>", lambda e: (self._form_next(1), "break")[1])
        ent.bind("<Shift-Tab>", lambda e: (self._form_next(-1), "break")[1])
        ent.bind("<ISO_Left_Tab>", lambda e: (self._form_next(-1), "break")[1])
        ent.bind("<Escape>", lambda e: (self._form_close_editor(False), "break")[1])
        attach_edit_menu(ent)
        ent.focus_set()
        ent.select_range(0, "end")
        ent.icursor("end")
        self.status.config(text=f"✎ {self._field_hint(f)} · Invio: conferma · Tab: successivo · Esc: annulla")

    def _form_close_editor(self, commit=True):
        if not self._form_entry:
            return
        ent, win, i, var = self._form_entry
        self._form_entry = None
        value = var.get().strip()
        try:
            self.canvas.delete(win)
            ent.destroy()
        except tk.TclError:
            pass
        if commit and self.doc and value != self._form_value(i):
            self._form_set(i, value)

    def _form_next(self, step):
        if not self._form_entry:
            return
        i = self._form_entry[2]
        self._form_close_editor(True)
        fields = self._form_fields_current()
        j = i + step
        while 0 <= j < len(fields) and fields[j]["kind"] == "check":
            j += step
        if 0 <= j < len(fields):
            self._form_open_editor(j)

    def _form_snapshot(self):
        return {p: dict(st, values=dict(st["values"])) for p, st in self.form.items()}

    def _form_set(self, i, value):
        """Imposta il valore di un campo: la pagina viene ricostruita dall'originale e riscritta con
        tutti i valori, così un campo si può correggere o svuotare senza lasciare tracce."""
        pno = self.page_no
        fields = self._form_fields_current()
        st = self.form.get(pno)
        if st is None or st["gen"] != self._gen:
            if st is not None and st["values"]:
                self.status.config(text="Il documento è stato modificato: i campi compilati finora sono stati "
                                        "fissati nella pagina")
            tmp = fitz.open()
            tmp.insert_pdf(self.doc, from_page=pno, to_page=pno)
            st = {"base": tmp.tobytes(), "fields": fields, "values": {}, "gen": self._gen}
            self.form[pno] = st
        if (st["values"].get(i) or "") == value:
            return
        self._checkpoint()
        if value:
            st["values"][i] = value
        else:
            st["values"].pop(i, None)
        self._form_render(pno, st)
        self._form_commits += 1
        if self._form_commits % 10 == 0:  # elimina le copie inutilizzate della pagina
            self.doc = fitz.open("pdf", self.doc.tobytes(garbage=1))
        self._changed()
        st["gen"] = self._gen

    def _form_render(self, pno, st):
        base = fitz.open("pdf", st["base"])
        self.doc.delete_page(pno)
        self.doc.insert_pdf(base, from_page=0, to_page=0, start_at=pno if pno < len(self.doc) else -1)
        page = self.doc[pno]
        for i, val in st["values"].items():
            try:
                draw_form_value(page, st["fields"][i], val)
            except Exception:
                pass

    def clear_form_page(self):
        st = self.form.get(self.page_no)
        if not st or not st["values"] or st["gen"] != self._gen:
            self.status.config(text="Nessun campo compilato da svuotare in questa pagina")
            return
        if not messagebox.askyesno(APP_NAME, "Svuotare tutti i campi compilati in questa pagina?"):
            return
        self._checkpoint()
        st["values"].clear()
        self._form_render(self.page_no, st)
        self._changed()
        st["gen"] = self._gen

    # ---------------------------------------------------------------- strumenti di modifica
    @staticmethod
    def _insert_fit(page, rect, text, size, font, color, align):
        if isinstance(font, FontChoice):
            fkw = dict(fontname=font.fontname, fontfile=font.fontfile) if font.fontfile else dict(fontname=font.fontname)
        else:
            fkw = dict(fontname=font)
        s = size
        while s >= 4:
            rc = page.insert_textbox(rect, text, fontsize=s, color=color, align=align,
                                     rotate=page.rotation, **fkw)
            if rc >= 0:
                return s
            s -= 0.5
        big = fitz.Rect(rect.x0, rect.y0, rect.x1, page.mediabox.y1)  # allunga il riquadro
        page.insert_textbox(big, text, fontsize=4, color=color, align=align, rotate=page.rotation, **fkw)
        return 4

    def _do_add_text(self, rect):
        style = self._detect_style(rect, near=True)
        res = TextDialog(self.root, "Aggiungi testo", style=style).show()
        self._remember_font(style, res)
        if not res or not res["text"].strip():
            return
        self._checkpoint()
        page = self.doc[self.page_no]
        used = self._insert_fit(page, rect, res["text"], res["size"], res["font"], res["color"], res["align"])
        self._changed()
        if used < res["size"]:
            self.status.config(text=f"Testo ridotto a {used} pt per entrare nel riquadro")

    def _do_edit_text(self, rect):
        page = self.doc[self.page_no]
        old = page.get_textbox(rect).strip()
        style = self._detect_style(rect)
        if not old:
            if not messagebox.askyesno(APP_NAME, "Nessun testo trovato nell'area (forse è una scansione: "
                                                 "esegui prima l'OCR).\nVuoi coprire l'area e scrivere testo nuovo?"):
                return
        res = TextDialog(self.root, "Modifica testo", text=old, style=style).show()
        self._remember_font(style, res)
        if res is None:
            return
        fill = self._bg_color(rect)  # colore di sfondo appena fuori dall'area
        self._checkpoint()
        page.add_redact_annot(rect, fill=fill)
        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
        if res["text"].strip():
            self._insert_fit(page, rect, res["text"], res["size"], res["font"], res["color"], res["align"])
        self._changed()

    def _do_add_image(self, rect):
        path = filedialog.askopenfilename(title="Scegli immagine", filetypes=[
            ("Immagini", "*.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff"), ("Tutti", "*.*")])
        if not path:
            return
        keep = messagebox.askyesno(APP_NAME, "Mantenere le proporzioni dell'immagine?")
        self._checkpoint()
        try:
            page = self.doc[self.page_no]
            page.insert_image(rect, filename=path, keep_proportion=keep, rotate=page.rotation)
        except Exception as exc:
            self.history.pop()
            messagebox.showerror(APP_NAME, f"Impossibile inserire l'immagine:\n\n{exc}")
            return
        self._changed()

    # ---------------------------------------------------------------- colori dell'omissis
    def _paint_redact_buttons(self):
        for btn, col in ((self.btn_fill, self.redact_fill), (self.btn_fg, self.redact_fg)):
            fg = "white" if sum(col) < 1.5 else "black"
            btn.config(bg=rgb_hex(col), activebackground=rgb_hex(col), fg=fg, activeforeground=fg)
        # anteprima: la scritta del pulsante "Scritta" su sfondo del colore scelto per l'omissis
        self.btn_fg.config(bg=rgb_hex(self.redact_fill), activebackground=rgb_hex(self.redact_fill),
                           fg=rgb_hex(self.redact_fg), activeforeground=rgb_hex(self.redact_fg))

    def _save_redact_settings(self):
        self.settings.update(omissis_scritta=bool(self.redact_label.get()),
                             omissis_sfondo=list(self.redact_fill), omissis_colore_scritta=list(self.redact_fg))
        save_settings(self.settings)

    def _pick_color(self, title, current):
        c = colorchooser.askcolor(color=rgb_hex(current), title=title, parent=self.root)
        return tuple(round(v / 255, 4) for v in c[0]) if c and c[0] else None

    def choose_redact_fill(self):
        c = self._pick_color("Colore di sfondo dell'omissis", self.redact_fill)
        if c:
            self.redact_fill = c
            self._paint_redact_buttons()
            self._save_redact_settings()

    def choose_redact_fg(self):
        c = self._pick_color("Colore della scritta OMISSIS", self.redact_fg)
        if c:
            self.redact_fg = c
            self._paint_redact_buttons()
            self._save_redact_settings()
            if not self.redact_label.get():
                self.redact_label.set(True)

    def _add_redaction(self, page, rect):
        if self.redact_label.get():
            fs = max(4, min(12, rect.height * 0.6))
            page.add_redact_annot(rect, text="OMISSIS", fontname="hebo", fontsize=fs,
                                  fill=self.redact_fill, text_color=self.redact_fg, align=fitz.TEXT_ALIGN_CENTER)
        else:
            page.add_redact_annot(rect, fill=self.redact_fill)

    def _do_redact(self, rect):
        page = self.doc[self.page_no]
        self._checkpoint()
        self._add_redaction(page, rect)
        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_PIXELS)
        self._changed()

    # ---------------------------------------------------------------- pagine
    def insert_blank(self):
        if not self._need_doc():
            return
        res = PositionDialog(self.root, "Inserisci pagina vuota", self.page_no, len(self.doc),
                             extra=("Quante pagine:", "1")).show()
        if not res:
            return
        pos, count = res
        try:
            count = max(1, int(count))
        except ValueError:
            count = 1
        ref = self.doc[self.page_no].rect
        self._checkpoint()
        for k in range(count):
            self.doc.new_page(pno=pos + k, width=ref.width, height=ref.height)
        self.page_no = pos
        self._changed(rebuild_list=True)

    def insert_from_pdf(self):
        if not self._need_doc():
            return
        path = filedialog.askopenfilename(title="PDF da cui inserire", filetypes=[("PDF", "*.pdf")])
        if not path:
            return
        try:
            with open(path, "rb") as fh:
                src = fitz.open("pdf", fh.read())
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"Impossibile aprire il file:\n\n{exc}")
            return
        res = PositionDialog(self.root, f"Inserisci da {os.path.basename(path)} ({len(src)} pag.)",
                             self.page_no, len(self.doc),
                             extra=("Pagine da inserire:", f"1-{len(src)}")).show()
        if not res:
            return
        pos, rng = res
        try:
            pages = parse_ranges(rng, len(src))
        except ValueError as exc:
            messagebox.showwarning(APP_NAME, str(exc))
            return
        self._checkpoint()
        for k, p in enumerate(pages):
            self.doc.insert_pdf(src, from_page=p, to_page=p, start_at=pos + k)
        self.page_no = pos
        self._changed(rebuild_list=True)

    def insert_image_page(self):
        if not self._need_doc():
            return
        path = filedialog.askopenfilename(title="Immagine da inserire come pagina", filetypes=[
            ("Immagini", "*.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff")])
        if not path:
            return
        res = PositionDialog(self.root, "Inserisci immagine come pagina", self.page_no, len(self.doc)).show()
        if not res:
            return
        pos = res[0]
        ref = self.doc[self.page_no].rect
        self._checkpoint()
        try:
            page = self.doc.new_page(pno=pos, width=ref.width, height=ref.height)
            page.insert_image(page.rect + (18, 18, -18, -18), filename=path, keep_proportion=True)
        except Exception as exc:
            self.undo()
            messagebox.showerror(APP_NAME, f"Impossibile inserire l'immagine:\n\n{exc}")
            return
        self.page_no = pos
        self._changed(rebuild_list=True)

    def delete_pages(self):
        if not self._need_doc():
            return
        rng = simpledialog.askstring(APP_NAME, f"Pagine da eliminare (es. 3 oppure 2-5,8)\n"
                                               f"Documento di {len(self.doc)} pagine:",
                                     initialvalue=str(self.page_no + 1), parent=self.root)
        if not rng:
            return
        try:
            pages = parse_ranges(rng, len(self.doc))
        except ValueError as exc:
            messagebox.showwarning(APP_NAME, str(exc))
            return
        if len(pages) >= len(self.doc):
            messagebox.showwarning(APP_NAME, "Non puoi eliminare tutte le pagine.")
            return
        if not messagebox.askyesno(APP_NAME, f"Eliminare {len(pages)} pagina/e?"):
            return
        self._checkpoint()
        self.doc.delete_pages(pages)
        self.page_no = min(pages[0], len(self.doc) - 1)
        self._changed(rebuild_list=True)

    def rotate(self, deg):
        if not self._need_doc():
            return
        self._checkpoint()
        page = self.doc[self.page_no]
        page.set_rotation((page.rotation + deg) % 360)
        self._changed()
        verso = {90: "a destra di 90°", -90: "a sinistra di 90°", 180: "di 180°"}.get(deg, f"di {deg}°")
        self.status.config(text=f"Pagina {self.page_no + 1} ruotata {verso} · Ctrl+Z per annullare")

    def move_page(self):
        if not self._need_doc():
            return
        n = simpledialog.askinteger(APP_NAME, f"Spostare la pagina {self.page_no + 1} alla posizione (1-{len(self.doc)}):",
                                    minvalue=1, maxvalue=len(self.doc), parent=self.root)
        if not n or n - 1 == self.page_no:
            return
        self._checkpoint()
        target = n - 1
        to = target if target < self.page_no else target + 1
        self.doc.move_page(self.page_no, -1 if to >= len(self.doc) else to)
        self.page_no = target
        self._changed(rebuild_list=True)

    # ---------------------------------------------------------------- strumenti
    def run_ocr(self):
        if not self._need_doc():
            return
        tdir = tessdata_dir()
        if not tdir:
            messagebox.showerror(APP_NAME, "Dati lingua OCR non trovati.\n\nCrea la cartella 'tessdata' accanto "
                                           "al programma e copiaci ita.traineddata / eng.traineddata\n"
                                           "(da github.com/tesseract-ocr/tessdata_fast).")
            return
        langs = sorted(f[:-12] for f in os.listdir(tdir) if f.endswith(".traineddata") and f != "osd.traineddata")
        opts = OcrDialog(self.root, langs).show()
        if not opts:
            return
        if opts["pages"]:
            try:
                parse_ranges(opts["pages"], len(self.doc))
            except ValueError as exc:
                messagebox.showwarning(APP_NAME, str(exc))
                return
        before = self.doc.tobytes()

        def done(data, count):
            self.history.append((before, self._form_snapshot()))
            self.doc = fitz.open("pdf", data)
            self._changed(rebuild_list=True)
            messagebox.showinfo(APP_NAME, f"OCR completato su {count} pagina/e." if count else
                                "Nessuna pagina da elaborare: il testo era già presente.\n"
                                "Scegli 'Tutte le pagine' per forzare l'OCR.")

        ProcessJob(self.root, "OCR in corso", "ocr", before, (opts, tdir), done,
                   start_msg="Avvio del motore OCR...")

    def compress(self):
        if not self._need_doc():
            return
        preset = CompressDialog(self.root).show()
        if not preset:
            return
        before = self.doc.tobytes()
        on_disk = self.path and os.path.exists(self.path) and not self.dirty
        ref_size = os.path.getsize(self.path) if on_disk else len(before)

        def done(data, _extra):
            if len(data) >= ref_size:
                messagebox.showinfo(APP_NAME, f"Il file non si riduce ulteriormente "
                                              f"({human_size(ref_size)} → {human_size(len(data))}).\n"
                                              f"Prova un livello più forte.")
                return
            self.history.append((before, self._form_snapshot()))
            self.doc = fitz.open("pdf", data)
            self._changed(rebuild_list=True)
            pct = 100 * (1 - len(data) / ref_size)
            messagebox.showinfo(APP_NAME, f"Compressione completata:\n{human_size(ref_size)} → "
                                          f"{human_size(len(data))}  (−{pct:.0f}%)\n\nRicorda di salvare.")

        ProcessJob(self.root, "Compressione in corso", "compress", before, tuple(preset), done,
                   start_msg="Preparazione della compressione...")

    @staticmethod
    def _safe(work):
        def wrapped(report, cancelled):
            try:
                return work(report, cancelled)
            except Cancelled:
                return None
        return wrapped

    def sanitize(self):
        if not self._need_doc():
            return
        self._form_close_editor(True)
        found = inspect_hidden(self.doc)
        opts = SanitizeDialog(self.root, found).show()
        if not opts or not any(opts.values()):
            return
        self._checkpoint()
        try:
            sanitize_document(self.doc, opts)
        except Exception as exc:
            self.undo()
            messagebox.showerror(APP_NAME, f"Pulizia non riuscita:\n\n{exc}")
            return
        self._changed(rebuild_list=True)
        after = inspect_hidden(self.doc)
        names = {"meta": "metadati", "annots": "commenti e annotazioni", "attachments": "allegati",
                 "bookmarks": "segnalibri", "links": "collegamenti", "js": "elementi JavaScript",
                 "fields": "campi compilabili"}
        lines = []
        for key, label in names.items():
            if opts.get(key) and found.get(key):
                left = after.get(key) or 0
                if key == "fields":
                    lines.append(f"• {label}: svuotati")
                else:
                    lines.append(f"• {label}: {found[key] - left} rimossi" + (f" ({left} non rimovibili)" if left else ""))
        if opts.get("hidden"):
            lines.append("• testo invisibile: rimosso")
        msg = "\n".join(lines) if lines else "Il documento non conteneva dati nascosti tra quelli scelti."
        messagebox.showinfo(APP_NAME, "Pulizia completata.\n\n" + msg +
                            "\n\nRicorda di salvare: PdfPaper riscrive il file da zero, quindi nel file salvato non "
                            "restano copie precedenti dei dati eliminati.")

    def extract_text(self):
        if not self._need_doc():
            return
        text = "\n".join(f"===== Pagina {i + 1} =====\n{p.get_text('text')}" for i, p in enumerate(self.doc))
        win = tk.Toplevel(self.root)
        win.title("Testo estratto")
        win.geometry("700x600")
        t = tk.Text(win, wrap="word", font=("Consolas", 10), undo=True)
        t.insert("1.0", text)
        attach_edit_menu(t)
        t.pack(fill="both", expand=True)

        def save_txt():
            p = filedialog.asksaveasfilename(parent=win, defaultextension=".txt", filetypes=[("Testo", "*.txt")])
            if p:
                with open(p, "w", encoding="utf-8") as fh:
                    fh.write(t.get("1.0", "end-1c"))
        ttk.Button(win, text="Salva come .txt", command=save_txt).pack(pady=4)
        if not text.replace("=", "").replace("Pagina", "").strip(" \n0123456789"):
            messagebox.showinfo(APP_NAME, "Nessun testo trovato: probabilmente è una scansione, esegui l'OCR.",
                                parent=win)

    def about(self):
        tdir = tessdata_dir() or "non trovata"
        messagebox.showinfo(f"Informazioni su {APP_NAME}", f"{APP_NAME} {APP_VERSION}\n{APP_AUTHOR}\n\n"
                                      f"Software libero con licenza GNU AGPL v3.\nCodice sorgente: {REPO_URL}\n"
                                      f"Il programma non trasmette dati in rete.\n\nPyMuPDF {fitz.VersionBind}\n"
                                      f"Dati OCR: {tdir}\nCartella programma: {app_dir()}")

    def quit(self):
        if self._confirm_discard():
            self.root.destroy()


# ----------------------------------------------------------------------------
# Avvio
# ----------------------------------------------------------------------------
def main():
    if sys.platform.startswith("win"):
        try:  # nitidezza su schermi ad alta risoluzione + icona nella barra applicazioni
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("PdfPaper.App")
        except Exception:
            pass
    root = tk.Tk()
    root.withdraw()
    try:  # icona finestra
        if sys.platform.startswith("win"):
            root.iconbitmap(default=resource("assets", "pdf_icon.ico"))
        root.iconphoto(True, tk.PhotoImage(file=resource("assets", "pdf_icon.png")))
    except tk.TclError:
        pass
    style = ttk.Style(root)
    native = "vista" if "vista" in style.theme_names() else None
    style.theme_use("clam")  # 'clam' permette la barra colorata dello splash
    style.configure("Splash.Horizontal.TProgressbar", troughcolor="#2b3140",
                    background="#e53935", bordercolor="#2b3140", lightcolor="#ef5350",
                    darkcolor="#c62828", thickness=10)

    state = {}

    def load_engine():
        global fitz
        try:
            import pymupdf as _f
        except ImportError:
            import fitz as _f
        fitz = _f

    def check_ocr():
        state["tess"] = tessdata_dir()

    def load_pillow():
        try:
            import PIL.Image  # noqa: F401  (usato dalla compressione)
        except ImportError:
            pass

    def prepare():
        os.environ.setdefault("TESSDATA_PREFIX", state.get("tess") or "")

    steps = [
        ("Inizializzazione interfaccia...", lambda: None),
        ("Caricamento motore PDF...", load_engine),
        ("Verifica dati OCR...", check_ocr),
        ("Caricamento moduli immagine...", load_pillow),
        ("Preparazione area di lavoro...", prepare),
    ]

    def start_main():
        if native:
            style.theme_use(native)  # aspetto nativo Windows per la finestra principale
        app = PdfPaperApp(root)
        root.update_idletasks()
        w, h = 1200, 800
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        root.geometry(f"{min(w, sw - 40)}x{min(h, sh - 80)}+{max((sw - w) // 2, 0)}+{max((sh - h) // 2 - 20, 0)}")
        root.deiconify()
        if sys.platform.startswith("win"):
            root.state("zoomed")
        args = [a for a in sys.argv[1:] if a.lower().endswith(".pdf") and os.path.isfile(a)]
        if args:
            root.after(200, lambda: app.open_file(args[0]))

    Splash(root, steps, start_main)
    root.mainloop()


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()  # necessario per i processi separati nell'exe
    main()
