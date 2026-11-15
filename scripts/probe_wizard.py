# Diagnostic : occurrences du hook wizard et des étapes dans les JS et templates.
import re

paths = [
    r"static/js/mobile-wizard.js",
    r"static/js/invoice-lines.js",
    r"config/templates/documents/invoice_form.html",
    r"config/templates/documents/quote_form.html",
]
for path in paths:
    try:
        text = open(path, encoding="utf-8", errors="replace").read()
    except FileNotFoundError:
        print(path, ": absent")
        continue
    print("==", path, len(text), "caractères ==")
    lines = text.splitlines()
    for index, line in enumerate(lines):
        lowered = line.lower()
        if (
            "wizard:final" in lowered
            or "wizard-sheet" in lowered
            or "fillrecap(" in lowered
            or "data-step-label" in lowered
            or "apercu" in lowered
        ):
            print(f"  L{index + 1}: {line.strip()[:110]}")
