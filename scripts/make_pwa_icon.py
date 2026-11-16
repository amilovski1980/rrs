# Génère l'icône PWA 512x512 (marque carrée sur fond sombre, safe-zone maskable).
from PIL import Image

BG = (7, 7, 8)  # #070708, cohérent avec theme_color du manifest
SIZE = 512
PAD = int(SIZE * 0.14)  # safe zone maskable ~ 14% par bord

mark = Image.open("static/img/dark/mark.png").convert("RGBA")
canvas = Image.new("RGB", (SIZE, SIZE), BG)
inner = SIZE - PAD * 2
scaled = mark.resize((inner, inner), Image.LANCZOS)
canvas.paste(scaled, (PAD, PAD), scaled)
canvas.save("static/img/pwa-512.png", "PNG", optimize=True)
print("pwa-512:", canvas.size)
