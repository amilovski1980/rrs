# Patchs par ligne (fragments sans accents, robustes au mojibake console).
import os

# 1. help.html : lignes 21-22 remplacees
path = os.path.join("config", "templates", "companies", "help.html")
lines = open(path, encoding="utf-8", errors="replace").read().splitlines()
for i, line in enumerate(lines):
    if "Contactez le support" in line:
        lines[i] = (
            '  <p class="sub" style="margin:0">Support : <b>admin@roadrunner-solutions.fr</b>'
            " — réponse sous 24 à 48 h ouvrées, du lundi au vendredi (9 h – 18 h).</p>"
        )
    if "compl" in line and "propri" in line and "t" + "phone" in line:
        lines[i] = (
            '  <p class="sub">Escalade : réponse détaillée sous 3 jours ouvrés,'
            " puis rappel par un responsable du support.</p>"
        )
open(path, "w", encoding="utf-8").write(lines and "\n".join(lines) + "\n")
print("help.html corrige")

# 2. catalog.py : description Pro
path = os.path.join("billing", "catalog.py")
text = open(path, encoding="utf-8", errors="replace").read()
text = text.replace(
    "voix Aminia, tickets de caisse, tous les modeles",
    "voix Aminia (bientot), tickets de caisse, tous les modeles",
)
text = text.replace(
    "voix Aminia, tickets de caisse, tous les modèles",
    "voix Aminia (bientôt), tickets de caisse, tous les modèles",
)
open(path, "w", encoding="utf-8").write(text)
print("catalog.py corrige")
