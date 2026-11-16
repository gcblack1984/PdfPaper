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
import sys
import threading
import time
import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox, simpledialog, ttk

APP_NAME = "PdfPaper"
APP_VERSION = "1.0.0"
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


FONTS = {"Helvetica": "helv", "Helvetica grassetto": "hebo",
         "Times": "tiro", "Times grassetto": "tibo",
         "Courier": "cour", "Courier grassetto": "cobo"}
ALIGNS = {"Sinistra": 0, "Centro": 1, "Destra": 2, "Giustificato": 3}


class TextDialog(BaseDialog):
    def __init__(self, master, title, text="", size=12.0, color=(0, 0, 0)):
        super().__init__(master, title)
        self.resizable(True, True)
        self.color = color
        self.txt = tk.Text(self.body, width=60, height=10, wrap="word",
                           font=("Segoe UI", 10), undo=True)
        self.txt.insert("1.0", text)
        self.txt.grid(row=0, column=0, columnspan=8, sticky="nsew")
        self.body.rowconfigure(0, weight=1)
        self.body.columnconfigure(7, weight=1)

        ttk.Label(self.body, text="Carattere").grid(row=1, column=0, pady=(8, 0), sticky="w")
        self.font = ttk.Combobox(self.body, values=list(FONTS), state="readonly", width=20)
        self.font.set("Helvetica")
        self.font.grid(row=1, column=1, pady=(8, 0), padx=4)
        ttk.Label(self.body, text="Dim.").grid(row=1, column=2, pady=(8, 0))
        self.size = ttk.Spinbox(self.body, from_=4, to=144, increment=0.5, width=6)
        self.size.set(round(size, 1))
        self.size.grid(row=1, column=3, pady=(8, 0), padx=4)
        ttk.Label(self.body, text="Allin.").grid(row=1, column=4, pady=(8, 0))
        self.align = ttk.Combobox(self.body, values=list(ALIGNS), state="readonly", width=11)
        self.align.set("Sinistra")
        self.align.grid(row=1, column=5, pady=(8, 0), padx=4)
        self.col_btn = tk.Button(self.body, text="  Colore  ", command=self._pick,
                                 relief="groove")
        self.col_btn.grid(row=1, column=6, pady=(8, 0), padx=4)
        self._paint_color()
        self.buttons()
        self.txt.focus_set()

    def _paint_color(self):
        r, g, b = (int(c * 255) for c in self.color)
        hexc = f"#{r:02x}{g:02x}{b:02x}"
        self.col_btn.config(bg=hexc, activebackground=hexc,
                            fg="white" if (r + g + b) < 380 else "black")

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
        self.result = dict(text=text, size=size, font=FONTS[self.font.get()],
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
        self.extra = None
        if extra:  # (etichetta, valore predefinito) per un campo testo aggiuntivo
            ttk.Label(self.body, text=extra[0]).grid(row=5, column=0, sticky="w", pady=(10, 0))
            self.extra = ttk.Entry(self.body, width=18)
            self.extra.insert(0, extra[1])
            self.extra.grid(row=5, column=1, sticky="w", padx=4, pady=(10, 0))
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
        ttk.Entry(self.body, textvariable=self.range, width=14).grid(row=4, column=1, sticky="w", padx=6, pady=(8, 0))
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


# ----------------------------------------------------------------------------
# Finestra principale
# ----------------------------------------------------------------------------
MODES = {
    "view": ("Sfoglia", "Scorri e consulta il documento"),
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
        self._drag = None
        self.mode = tk.StringVar(value="view")
        self.redact_label = tk.BooleanVar(value=True)

        root.title(APP_TITLE)
        root.geometry("1200x800")
        root.minsize(800, 500)
        self._build_menu()
        self._build_toolbar()
        self._build_body()
        self._bind_keys()
        root.protocol("WM_DELETE_WINDOW", self.quit)
        self.mode.trace_add("write", lambda *a: self._update_status())
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
        for key in ("text", "edit", "image", "redact"):
            e.add_radiobutton(label=MODES[key][0], variable=self.mode, value=key)
        e.add_separator()
        e.add_checkbutton(label="Scritta \"OMISSIS\" sulle aree omissate", variable=self.redact_label)
        m.add_cascade(label="Modifica", menu=e)

        p = tk.Menu(m, tearoff=False)
        p.add_command(label="Inserisci pagina vuota...", command=self.insert_blank)
        p.add_command(label="Inserisci pagine da altro PDF...", command=self.insert_from_pdf)
        p.add_command(label="Inserisci immagine come nuova pagina...", command=self.insert_image_page)
        p.add_separator()
        p.add_command(label="Elimina pagine...", accelerator="Canc", command=self.delete_pages)
        p.add_command(label="Ruota pagina corrente di 90°", command=lambda: self.rotate(90))
        p.add_command(label="Sposta pagina corrente...", command=self.move_page)
        m.add_cascade(label="Pagine", menu=p)

        t = tk.Menu(m, tearoff=False)
        t.add_command(label="OCR (rendi ricercabile)...", command=self.run_ocr)
        t.add_command(label="Comprimi...", command=self.compress)
        t.add_command(label="Estrai testo...", command=self.extract_text)
        m.add_cascade(label="Strumenti", menu=t)

        v = tk.Menu(m, tearoff=False)
        v.add_command(label="Zoom +", accelerator="Ctrl++", command=lambda: self.set_zoom(self.zoom * 1.2))
        v.add_command(label="Zoom -", accelerator="Ctrl+-", command=lambda: self.set_zoom(self.zoom / 1.2))
        v.add_command(label="Adatta larghezza", command=self.fit_width)
        m.add_cascade(label="Visualizza", menu=v)

        h = tk.Menu(m, tearoff=False)
        h.add_command(label="Informazioni", command=self.about)
        m.add_cascade(label="?", menu=h)
        self.root.config(menu=m)

    def _build_toolbar(self):
        tb = ttk.Frame(self.root, padding=(6, 4))
        tb.pack(side="top", fill="x")

        def btn(text, cmd):
            b = ttk.Button(tb, text=text, command=cmd)
            b.pack(side="left", padx=2)
            return b

        def sep():
            ttk.Separator(tb, orient="vertical").pack(side="left", fill="y", padx=6)

        btn("📂 Apri", self.open_file)
        btn("💾 Salva", self.save)
        btn("↶ Annulla", self.undo)
        sep()
        btn("◀", self.prev_page)
        self.page_var = tk.StringVar(value="0")
        ent = ttk.Entry(tb, textvariable=self.page_var, width=5, justify="center")
        ent.pack(side="left")
        ent.bind("<Return>", lambda e: self._goto_entry())
        self.page_total = ttk.Label(tb, text="/ 0")
        self.page_total.pack(side="left", padx=(2, 4))
        btn("▶", self.next_page)
        sep()
        btn("−", lambda: self.set_zoom(self.zoom / 1.2))
        self.zoom_lbl = ttk.Label(tb, text="125%", width=5, anchor="center")
        self.zoom_lbl.pack(side="left")
        btn("+", lambda: self.set_zoom(self.zoom * 1.2))
        btn("↔", self.fit_width)
        sep()
        for key, icon in (("view", "✋"), ("text", "T+"), ("edit", "✎"),
                          ("image", "🖼"), ("redact", "█")):
            ttk.Radiobutton(tb, text=f"{icon} {MODES[key][0]}", variable=self.mode,
                            value=key, style="Toolbutton").pack(side="left", padx=1)
        ttk.Checkbutton(tb, text="scritta OMISSIS", variable=self.redact_label).pack(side="left", padx=4)
        sep()
        btn("🔍 OCR", self.run_ocr)
        btn("🗜 Comprimi", self.compress)

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
        r.bind("<Control-z>", lambda e: self.undo())
        r.bind("<Control-plus>", lambda e: self.set_zoom(self.zoom * 1.2))
        r.bind("<Control-equal>", lambda e: self.set_zoom(self.zoom * 1.2))
        r.bind("<Control-minus>", lambda e: self.set_zoom(self.zoom / 1.2))
        r.bind("<Next>", lambda e: self.next_page())
        r.bind("<Prior>", lambda e: self.prev_page())
        r.bind("<Escape>", lambda e: self.mode.set("view"))
        self.pages_lb.bind("<Delete>", lambda e: self.delete_pages())

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
        self.refresh(rebuild_list=True)
        self.root.after(50, self.fit_width)

    def close_doc(self):
        if not self._confirm_discard():
            return
        self.doc, self.path, self.history, self.dirty = None, None, [], False
        self.pages_lb.delete(0, "end")
        self.page_total.config(text="/ 0")
        self.page_var.set("0")
        self._show_welcome()
        self.root.title(APP_TITLE)
        self._update_status()

    def _pdf_bytes(self):
        return self.doc.tobytes(garbage=3, deflate=True)

    def save(self):
        if not self._need_doc():
            return False
        if not self.path:
            return self.save_as()
        return self._write(self.path)

    def save_as(self):
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
        self.history.append(self.doc.tobytes())
        if len(self.history) > MAX_UNDO:
            self.history.pop(0)

    def _changed(self, rebuild_list=False):
        self.dirty = True
        self.refresh(rebuild_list=rebuild_list)

    def undo(self):
        if not self.doc or not self.history:
            return
        self.doc = fitz.open("pdf", self.history.pop())
        self.page_no = min(self.page_no, len(self.doc) - 1)
        self._changed(rebuild_list=True)

    # ---------------------------------------------------------------- visualizzazione
    def refresh(self, rebuild_list=False):
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
        self._img = tk.PhotoImage(data=pix.tobytes("ppm"))
        self.canvas.delete("all")
        cw = self.canvas.winfo_width()
        self._ox = max(10, (cw - pix.width) // 2)
        self._oy = 10
        self.canvas.create_rectangle(self._ox + 3, self._oy + 3, self._ox + pix.width + 3,
                                     self._oy + pix.height + 3, fill="#333", outline="")
        self.canvas.create_image(self._ox, self._oy, image=self._img, anchor="nw")
        self.canvas.config(scrollregion=(0, 0, pix.width + 2 * self._ox, pix.height + 20))
        self._update_status()

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
        self.refresh()

    def fit_width(self):
        if not self.doc:
            return
        cw = max(self.canvas.winfo_width() - 40, 200)
        self.set_zoom(cw / self.doc[self.page_no].rect.width)

    def _on_wheel(self, e):
        if e.state & 0x0004:  # Ctrl: zoom
            self.set_zoom(self.zoom * (1.1 if e.delta > 0 else 1 / 1.1))
        else:
            self.canvas.yview_scroll(int(-e.delta / 40) or (-1 if e.delta > 0 else 1), "units")

    # ---------------------------------------------------------------- selezione area
    def _on_press(self, e):
        if not self.doc:
            return
        x, y = self.canvas.canvasx(e.x), self.canvas.canvasy(e.y)
        if self.mode.get() == "view":
            self.canvas.scan_mark(e.x, e.y)
            self._drag = ("pan",)
            return
        color = {"redact": "#000000", "image": "#1565c0"}.get(self.mode.get(), "#d32f2f")
        rid = self.canvas.create_rectangle(x, y, x, y, outline=color, width=2, dash=(4, 2))
        self._drag = ("rect", x, y, rid)

    def _on_motion(self, e):
        if not self._drag:
            return
        if self._drag[0] == "pan":
            self.canvas.scan_dragto(e.x, e.y, gain=1)
            return
        _, x0, y0, rid = self._drag
        self.canvas.coords(rid, x0, y0, self.canvas.canvasx(e.x), self.canvas.canvasy(e.y))

    def _on_release(self, e):
        drag, self._drag = self._drag, None
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

    def _canvas_to_pdf(self, x0, y0, x1, y1):
        page = self.doc[self.page_no]
        r = fitz.Rect((min(x0, x1) - self._ox) / self.zoom, (min(y0, y1) - self._oy) / self.zoom,
                      (max(x0, x1) - self._ox) / self.zoom, (max(y0, y1) - self._oy) / self.zoom)
        r = r & page.rect  # limita alla pagina visibile
        if r.is_empty or r.width < 2 or r.height < 2:
            return None
        return (r * page.derotation_matrix).normalize()  # coordinate non ruotate

    # ---------------------------------------------------------------- strumenti di modifica
    @staticmethod
    def _insert_fit(page, rect, text, size, font, color, align):
        s = size
        while s >= 4:
            rc = page.insert_textbox(rect, text, fontsize=s, fontname=font, color=color,
                                     align=align, rotate=page.rotation)
            if rc >= 0:
                return s
            s -= 0.5
        big = fitz.Rect(rect.x0, rect.y0, rect.x1, page.mediabox.y1)  # allunga il riquadro
        page.insert_textbox(big, text, fontsize=4, fontname=font, color=color, align=align,
                            rotate=page.rotation)
        return 4

    def _do_add_text(self, rect):
        res = TextDialog(self.root, "Aggiungi testo").show()
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
        size, color = 11.0, (0, 0, 0)
        for block in page.get_text("dict", clip=rect).get("blocks", []):
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    if span["text"].strip():
                        size = span["size"]
                        c = span["color"]
                        color = (((c >> 16) & 255) / 255, ((c >> 8) & 255) / 255, (c & 255) / 255)
                        break
                else:
                    continue
                break
            else:
                continue
            break
        if not old:
            if not messagebox.askyesno(APP_NAME, "Nessun testo trovato nell'area (forse è una scansione: "
                                                 "esegui prima l'OCR).\nVuoi coprire l'area e scrivere testo nuovo?"):
                return
        res = TextDialog(self.root, "Modifica testo", text=old, size=size, color=color).show()
        if res is None:
            return
        # colore di sfondo campionato dall'angolo dell'area
        try:
            px = page.get_pixmap(clip=fitz.Rect(rect.x0, rect.y0, rect.x0 + 2, rect.y0 + 2),
                                 alpha=False).pixel(0, 0)
            fill = tuple(v / 255 for v in px[:3])
        except Exception:
            fill = (1, 1, 1)
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
            self.doc[self.page_no].insert_image(rect, filename=path, keep_proportion=keep)
        except Exception as exc:
            self.history.pop()
            messagebox.showerror(APP_NAME, f"Impossibile inserire l'immagine:\n\n{exc}")
            return
        self._changed()

    def _do_redact(self, rect):
        page = self.doc[self.page_no]
        self._checkpoint()
        if self.redact_label.get():
            fs = max(4, min(12, rect.height * 0.6))
            page.add_redact_annot(rect, text="OMISSIS", fontname="hebo", fontsize=fs,
                                  fill=(0, 0, 0), text_color=(1, 1, 1), align=fitz.TEXT_ALIGN_CENTER)
        else:
            page.add_redact_annot(rect, fill=(0, 0, 0))
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

        def done(res):
            data, count = res
            self.history.append(before)
            self.doc = fitz.open("pdf", data)
            self._changed(rebuild_list=True)
            messagebox.showinfo(APP_NAME, f"OCR completato su {count} pagina/e." if count else
                                "Nessuna pagina da elaborare: il testo era già presente.\n"
                                "Scegli 'Tutte le pagine' per forzare l'OCR.")

        Job(self.root, "OCR in corso", self._safe(ocr_worker(before, opts, tdir)), done)

    def compress(self):
        if not self._need_doc():
            return
        preset = CompressDialog(self.root).show()
        if not preset:
            return
        before = self.doc.tobytes()
        on_disk = self.path and os.path.exists(self.path) and not self.dirty
        ref_size = os.path.getsize(self.path) if on_disk else len(before)

        def done(data):
            if len(data) >= ref_size:
                messagebox.showinfo(APP_NAME, f"Il file non si riduce ulteriormente "
                                              f"({human_size(ref_size)} → {human_size(len(data))}).\n"
                                              f"Prova un livello più forte.")
                return
            self.history.append(before)
            self.doc = fitz.open("pdf", data)
            self._changed(rebuild_list=True)
            pct = 100 * (1 - len(data) / ref_size)
            messagebox.showinfo(APP_NAME, f"Compressione completata:\n{human_size(ref_size)} → "
                                          f"{human_size(len(data))}  (−{pct:.0f}%)\n\nRicorda di salvare.")

        Job(self.root, "Compressione in corso", self._safe(compress_worker(before, *preset)), done)

    @staticmethod
    def _safe(work):
        def wrapped(report, cancelled):
            try:
                return work(report, cancelled)
            except Cancelled:
                return None
        return wrapped

    def extract_text(self):
        if not self._need_doc():
            return
        text = "\n".join(f"===== Pagina {i + 1} =====\n{p.get_text('text')}" for i, p in enumerate(self.doc))
        win = tk.Toplevel(self.root)
        win.title("Testo estratto")
        win.geometry("700x600")
        t = tk.Text(win, wrap="word", font=("Consolas", 10))
        t.insert("1.0", text)
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
    main()
