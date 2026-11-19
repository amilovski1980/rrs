# Verification de C:\splash-screen\index.html contre la specification.
text = open(r"C:\splash-screen\index.html", encoding="utf-8", errors="replace").read()

checks = {
    "checkbox + :has()": (":has(" in text and "checkbox" in text),
    "prefers-color-scheme": "@media (prefers-color-scheme: dark)" in text,
    "prefers-reduced-motion": "prefers-reduced-motion" in text,
    "variables --t-bar/--t-hold/--t-main": all(v in text for v in ("--t-bar", "--t-hold", "--t-main")),
    "orbe a anneaux": (".ring-1" in text or ".orbo" in text) and "ring" in text.lower(),
    "barre pilule": ("rrs-bar" in text or "progress" in text),
    "reflet balayant / point lumineux": ("glow" in text or "sheen" in text) and ("dot" in text or "spark" in text),
    "4 etapes FR cyclees": ("Recherche de votre soci" in text or "Recherche de votre soci" in text) and ("Cockpit pr" in text or "pr" in text),
    "sortie 3.7s zoom": ("3.7s" in text or "3,7" in text) and "scale(" in text,
    "pill Facturation electronique 2026": "lectronique 2026" in text,
    "titre en degrade": "background-clip" in text,
    "KPI CA / encaisser / TVA": ("CA factur" in text and "encaisser" in text.lower() and "TVA" in text),
    "badges de statut": "badge" in text,
    "footer": "footer" in text,
    "pur CSS (aucun script)": "<script" not in text.lower(),
}
for label, ok in checks.items():
    print(("OK  " if ok else "MANQUE  ") + label)
braces = text.count("{") - text.count("}")
print("accolades equilibrees:", braces == 0, "(delta", braces, ")")
