# Nettoyage des règles verre legacy qui surchargent le matériau glass-panel.
import re

path = r"static/css/app.css"
text = open(path, encoding="utf-8", errors="replace").read()
removed = 0

# Règles sombres du panneau résultats (fond/bord/ombre) -> matériau.
patterns = [
    r'html\[data-theme="dark"\] \.agent-results-card \{[^}]*\}\n',
    r'html\[data-theme="dark"\] \.agent-result-row \{[^}]*\}\n',
    r'html\[data-theme="dark"\] \.live-invoice \.card \{[^}]*\}\n',
    r'\.live-invoice \.card \{\n\s*background: rgba\(255, 255, 255, \.9\);[^}]*\}\n',
]
for pattern in patterns:
    new_text, count = re.subn(pattern, "", text, flags=re.S)
    if count:
        text = new_text
        removed += count
open(path, "w", encoding="utf-8").write(text)
print("règles retirées:", removed)
