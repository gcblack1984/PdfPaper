"""Copia nella cartella di distribuzione i testi di licenza dei componenti inclusi.

Uso:  python tools/collect_licenses.py dist/PdfPaper/licenze
"""
import os
import shutil
import sys
from importlib import metadata

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
KEYS = ("LICEN", "COPYING", "NOTICE", "AUTHORS")


def copy_dist(dist_name, dest):
    try:
        dist = metadata.distribution(dist_name)
    except metadata.PackageNotFoundError:
        print(f"  ! {dist_name} non installato")
        return
    out = os.path.join(dest, f"{dist_name}-{dist.version}")
    n = 0
    for f in dist.files or []:
        if any(k in f.name.upper() for k in KEYS):
            os.makedirs(out, exist_ok=True)
            shutil.copy(f.locate(), os.path.join(out, f.name))
            n += 1
    print(f"  {dist_name} {dist.version}: {n} file")


def copy_file(src, dest, name):
    if os.path.isfile(src):
        shutil.copy(src, os.path.join(dest, name))
        print(f"  {name}")
    else:
        print(f"  ! non trovato: {src}")


def main():
    dest = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "dist", "PdfPaper", "licenze")
    os.makedirs(dest, exist_ok=True)
    print("Licenze dei componenti ->", dest)
    for d in ("PyMuPDF", "pillow", "pyinstaller"):
        copy_dist(d, dest)
    base = sys.base_prefix
    copy_file(os.path.join(base, "LICENSE.txt"), dest, "Python-LICENSE.txt")
    copy_file(os.path.join(base, "tcl", "tcl8.6", "license.terms"), dest, "Tcl-license.terms")
    copy_file(os.path.join(base, "tcl", "tk8.6", "license.terms"), dest, "Tk-license.terms")
    copy_file(os.path.join(ROOT, "third_party", "Apache-2.0.txt"), dest, "tessdata-Apache-2.0.txt")


if __name__ == "__main__":
    main()
