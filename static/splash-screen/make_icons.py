"""Génère icon-512.png et icon-180.png depuis les MÊMES coordonnées
vectorielles que icon.svg / icon-maskable.svg (make_icons.py).

Degrade diagonal (#2563eb -> #004192 -> #ca1c60) calcule pixel par pixel
avec numpy, eclair blanc trace aux coordonnees du gabarit SVG :
  - icon-512.png  : fond plein + eclair a 62 % (zone sure maskable)
  - icon-180.png  : carre plein (iOS applique ses propres coins)
Usage :  python make_icons.py
"""
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

SIZE = 512
OUT = Path(__file__).resolve().parent

# Palette officielle du site (vitrine claire)
C0 = (0x25, 0x63, 0xEB)  # bleu-2  #2563eb        (0 %)
C1 = (0x00, 0x41, 0x92)  # bleu institutionnel #004192  (50 %)
C2 = (0xCA, 0x1C, 0x60)  # rose   #ca1c60        (100 %)

STOPS = [(0.0, C0), (0.5, C1), (1.0, C2)]


def diagonal_gradient(size: int) -> np.ndarray:
    x = np.linspace(0.0, 1.0, size, dtype=np.float32)
    y = np.linspace(0.0, 1.0, size, dtype=np.float32)
    xx, yy = np.meshgrid(x, y)
    t = np.clip((xx + yy) / 2.0, 0.0, 1.0)  # progression sur la diagonale
    img = np.zeros((size, size, 3), dtype=np.uint8)
    for channel in range(3):
        plane = np.zeros_like(t)
        for (t0, c0), (t1, c1) in zip(STOPS, STOPS[1:]):
            span = np.clip((t - t0) / (t1 - t0), 0.0, 1.0)
            plane += span * (c1[channel] - c0[channel])
            plane += c0[channel] * np.where((t >= t0) & (t < t1), 1.0, 0.0) * 0
        # interpolation exacte entre paliers
        plane = np.zeros_like(t)
        for idx in range(len(STOPS) - 1):
            (t0, c0), (t1, c1) = STOPS[idx], STOPS[idx + 1]
            zone = (t >= t0) & (t <= t1)
            span = (t - t0) / (t1 - t0)
            plane = np.where(zone, c0[channel] + span * (c1[channel] - c0[channel]), plane)
        img[:, :, channel] = np.round(np.clip(plane, 0, 255)).astype(np.uint8)
    return img


def draw_bolt(draw: ImageDraw.ImageDraw, scale: float, offset: tuple = (0, 0),
              color=(255, 255, 255)) -> None:
    """Eclair blanc, coordonnees a l echelle du gabarit SVG 512x512.
    Coordonnees identiques a icon-maskable.svg : le centre du pictogramme
    tombe a ~62 % de la hauteur (zone sure maskable)."""
    points = [
        (272, 96), (172, 330), (246, 330), (212, 484),
        (398, 234), (308, 234), (358, 96),
    ]
    pts = [(x * scale + offset[0] * scale / 512.0,
            y * scale + offset[1] * scale / 512.0)
           for (x, y) in points]
    draw.polygon(pts, fill=color)


def make_full_bleed(png_path: Path, size: int) -> None:
    """icon-512.png / icon-180.png : fond plein + eclair a 62 % (maskable)."""
    grad = Image.fromarray(diagonal_gradient(SIZE), mode="RGB")
    canvas = grad.resize((size, size), Image.LANCZOS)
    draw = ImageDraw.Draw(canvas)
    draw_bolt(draw, scale=size / 512.0)
    canvas.save(png_path, "PNG", optimize=True)
    print(png_path.name, canvas.size)


def make_180() -> None:
    make_full_bleed(OUT / "icon-180.png", 180)


def make_512() -> None:
    size = 512
    grad = Image.fromarray(diagonal_gradient(size), mode="RGB")
    canvas = grad.filter(ImageFilter.GaussianBlur(0.4))
    draw = ImageDraw.Draw(canvas)
    draw_bolt(draw, scale=size / 512.0)
    canvas = canvas.convert("RGB")
    canvas.save(OUT / "icon-512.png", "PNG", optimize=True)
    print("icon-512.png", canvas.size)


if __name__ == "__main__":
    make_512()
    make_180()
