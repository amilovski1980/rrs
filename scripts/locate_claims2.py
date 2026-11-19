# Recherche complementaire : pret pour la facturation + forfaits voix.
import glob
import os

patterns = ["prêt pour", "prêt pour la facturation", "Voix Aminia", "voix amínia", "bientôt", "voix"]
seen = set()
for path in (
    glob.glob(os.path.join("billing", "**", "*.py"), recursive=True)
    + glob.glob(os.path.join("config", "templates", "landing.html"))
    + glob.glob(os.path.join("config", "templates", "dark", "landing.html"))
    + glob.glob(os.path.join("core", "*.py"))
    + glob.glob(os.path.join("companies", "templates", "**", "*.html"), recursive=True)
):
    try:
        text = open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        continue
    for i, line in enumerate(text.splitlines()):
        low = line.lower()
        if "prêt pour" in low or "voix aminia" in low or "voix aminia" in low:
            key = (path, i + 1)
            if key not in seen:
                seen.add(key)
                print(os.path.relpath(path), "L" + str(i + 1) + ":", line.strip()[:96])
