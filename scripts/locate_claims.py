# Localisation des formulations a corriger (conformite, mentions legales).
import glob
import os

patterns = [
    "conformes 2026",
    "facturation électronique",
    "facturation électronique",
    "Hébergé en France",
    "Hébergement en France",
    "Voix Aminia",
    "À compléter",
    "à compléter",
    "FR17",
    "100 408 517",
    "100408517",
]
seen = set()
for path in glob.glob(os.path.join("config", "templates", "**", "*.html"), recursive=True) + glob.glob(
    os.path.join("billing", "templates", "**", "*.html"), recursive=True
) + glob.glob(os.path.join("core", "**", "*.py"), recursive=True):
    try:
        text = open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        continue
    lines = text.splitlines()
    for i, line in enumerate(lines):
        for pattern in patterns:
            if pattern in line:
                key = (path, i + 1)
                if key in seen:
                    continue
                seen.add(key)
                print(
                    os.path.relpath(path)
                    + " L"
                    + str(i + 1)
                    + ": "
                    + line.strip()[:86]
                )
                break
