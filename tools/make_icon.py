"""Genera assets/pdf_icon.ico (16-256 px) e assets/pdf_icon.png (256 px)."""
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
print("Icone create in", os.path.abspath(OUT))
