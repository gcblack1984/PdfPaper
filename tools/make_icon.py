"""Genera le icone: assets/pdf_icon.ico (16-256 px), assets/pdf_icon*.png e le immagini per
Microsoft Store in msix/Assets (riquadri dell'app) e msix/store (logo della scheda)."""
import os
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "assets")
os.makedirs(OUT, exist_ok=True)

S = 1024
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)

# ombra
d.rounded_rectangle((200, 90, 860, 980), radius=60, fill=(0, 0, 0, 60))
# foglio con angolo piegato
fold = 200
page = [(170, 60), (830 - fold, 60), (830, 60 + fold), (830, 950), (170, 950)]
d.polygon(page, fill=(250, 250, 250, 255), outline=(170, 170, 170, 255))
d.line(page + [page[0]], fill=(150, 150, 150, 255), width=14, joint="curve")
d.polygon([(830 - fold, 60), (830 - fold, 60 + fold), (830, 60 + fold)], fill=(215, 215, 215, 255))
d.line([(830 - fold, 60), (830 - fold, 60 + fold), (830, 60 + fold)], fill=(150, 150, 150, 255), width=14)
# righe di testo
for y in (330, 400, 470):
    d.rounded_rectangle((260, y, 740, y + 30), radius=15, fill=(200, 200, 200, 255))
# fascia rossa "PDF"
d.rounded_rectangle((90, 560, 760, 850), radius=50, fill=(211, 47, 47, 255))
try:
    font = ImageFont.truetype("DejaVuSans-Bold.ttf", 230)
except OSError:
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 230)
d.text((425, 705), "PDF", font=font, fill="white", anchor="mm")

png = img.resize((256, 256), Image.LANCZOS)
png.save(os.path.join(OUT, "pdf_icon.png"))
img.resize((128, 128), Image.LANCZOS).save(os.path.join(OUT, "pdf_icon_128.png"))
png.save(os.path.join(OUT, "pdf_icon.ico"),
         sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])

# --- Microsoft Store (MSIX): riquadri dell'app e logo per la scheda
MSIX = os.path.join(HERE, "..", "msix", "Assets")
STORE = os.path.join(HERE, "..", "msix", "store")
os.makedirs(MSIX, exist_ok=True)
os.makedirs(STORE, exist_ok=True)


def square(size, pad=0.0):
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    inner = max(1, int(round(size * (1 - 2 * pad))))
    ic = img.resize((inner, inner), Image.LANCZOS)
    canvas.paste(ic, ((size - inner) // 2, (size - inner) // 2), ic)
    return canvas


for name, size, pad in (("Square44x44Logo.png", 44, 0.0), ("Square150x150Logo.png", 150, 0.12),
                        ("StoreLogo.png", 50, 0.0), ("Square71x71Logo.png", 71, 0.08)):
    square(size, pad).save(os.path.join(MSIX, name))
wide = Image.new("RGBA", (310, 150), (0, 0, 0, 0))
ic = img.resize((110, 110), Image.LANCZOS)
wide.paste(ic, (18, 20), ic)
try:
    wf = ImageFont.truetype("DejaVuSans-Bold.ttf", 27)
except OSError:
    wf = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 27)
ImageDraw.Draw(wide).text((136, 75), "PdfPaper", font=wf, fill=(211, 47, 47, 255), anchor="lm")
wide.save(os.path.join(MSIX, "Wide310x150Logo.png"))
# logo per la scheda dello Store (sfondo pieno, 300x300 e 1080x1080)
for size in (300, 1080):
    bg = Image.new("RGBA", (size, size), (31, 36, 48, 255))
    sq = square(size, 0.14)
    bg.paste(sq, (0, 0), sq)
    bg.convert("RGB").save(os.path.join(STORE, f"logo_{size}.png"))
# logo verticale 2:3 (poster) per la scheda dello Store
poster = Image.new("RGBA", (720, 1080), (31, 36, 48, 255))
pic = square(460)
poster.paste(pic, (130, 250), pic)
try:
    pf = ImageFont.truetype("DejaVuSans-Bold.ttf", 76)
except OSError:
    pf = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 76)
pd = ImageDraw.Draw(poster)
pd.text((360, 820), "PdfPaper", font=pf, fill="white", anchor="mm")
pd.rectangle((260, 880, 460, 886), fill=(211, 47, 47, 255))
poster.convert("RGB").save(os.path.join(STORE, "poster_720x1080.png"))
print("Icone create in", os.path.abspath(OUT), "e", os.path.abspath(MSIX))
