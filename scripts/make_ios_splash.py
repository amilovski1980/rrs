"""Generere les images de lancement iOS (apple-touch-startup-image).

Fonds clair (theme vitrine) et sombre (theme /dark), logo reel compose au
centre + fine barre de chargement. PNG nommes au format Apple :
  apple-splash-<L>x<H>.png   (pixels reels du device)
Usage : python make_ios_splash.py
"""
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "static" / "img" / "splash" / "ios"
OUT.mkdir(parents=True, exist_ok=True)

DARK_LOGO = ROOT / "static" / "img" / "dark" / "mark.png"
LIGHT_LOGO = ROOT / "static" / "img" / "logo-96.png"

DARK_BG = (7, 7, 8)      # #070708
LIGHT_BG = (246, 248, 251)  # #f6f8fb

# Devices courants : (largeur_px, hauteur_px, echelle_logique)
DEVICES = [
    (1290, 2796),  # iPhone 15/16 Pro Max (@3x)
    (1179, 2556),  # iPhone 15/16 / Pro (@3x)
    (1125, 2436),  # iPhone X/11 Pro/12 mini (@3x)
    (750, 1624),   # iPhone 12/13 mini (@2x)
    (1284, 2778),  # iPhone 12/13/14 Plus (@2x+3x var.)
    (750, 1334),   # iPhone SE 2/3 / 7/8 (@2x)
    (640, 1136),   # iPhone SE 1er gen (@2x)
    (2048, 2732),  # iPad Pro 12.9
    (1668, 2388),  # iPad Pro 11 / Air
    (1488, 2266),  # iPad mini (@2x)
]


def draw(width: int, height: int, theme: str) -> Image.Image:
    bg = DARK_BG if theme == "dark" else LIGHT_BG
    canvas = Image.new("RGB", (width, height), bg)
    logo_path = DARK_LOGO if theme == "dark" else LIGHT_LOGO
    logo = Image.open(logo_path).convert("RGBA")

    # logo ~26 % du cote
    side = int(min(width, height) * 0.26)
    logo = logo.resize((side, side), Image.LANCZOS)
    margin_top = int(height * 0.30)
    x = (width - side) // 2
    canvas.paste(logo, (x, margin_top), logo)

    # fine barre de progression : 34 % de large, sous le logo
    bar_w = int(width * 0.34)
    bar_h = max(4, int(width * 0.006))
    bar_y = margin_top + side + int(height * 0.05)
    bar_x = (width - bar_w) // 2
    track = tuple(min(255, c + 26) for c in bg) if theme == "dark" else (226, 232, 240)
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle([bar_x, bar_y, bar_x + bar_w, bar_y + bar_h], bar_h, track)
    accent = (61, 220, 106) if theme == "dark" else (37, 99, 235)
    filled = int(bar_w * 0.62)
    draw.rounded_rectangle([bar_x, bar_y, bar_x + filled, bar_y + bar_h], bar_h, accent)
    return canvas


for theme in ("light", "dark"):
    for (w, h) in DEVICES:
        image = draw(w, h, theme)
        name = f"apple-splash-{theme}-{w}x{h}.png"
        image.save(OUT / name, "PNG", optimize=True)
        print(name)
