# Appends the Liquid Glass material section to app.css if not already there.
text = open(r"static/css/app.css", encoding="utf-8", errors="replace").read()
if "Liquid Glass" in text:
    print("déjà présent")
    raise SystemExit
material = r"""
/* ==================================================================
   Matériau « Liquid Glass » (iOS 26) pour les panneaux Aminia
   Voile translucide, rim-light, reflet supérieur, ombre douce.
   ================================================================== */
:root {
  --glass-blur: blur(22px) saturate(180%);
  --glass-bg: rgba(255, 255, 255, .68);
  --glass-bg-strong: rgba(255, 255, 255, .78);
  --glass-rim: rgba(255, 255, 255, .55);
  --glass-rim-line: rgba(15, 23, 42, .07);
  --glass-specular: linear-gradient(180deg, rgba(255, 255, 255, .34), rgba(255, 255, 255, .06) 38%, rgba(255, 255, 255, 0) 60%);
  --glass-shadow:
    0 1px 0 rgba(255, 255, 255, .32) inset,
    0 28px 70px -30px rgba(8, 24, 48, .40),
    0 8px 22px -12px rgba(8, 24, 48, .18);
  --glass-radius: 20px;
}
html[data-theme="dark"] {
  --glass-bg: rgba(18, 18, 21, .58);
  --glass-bg-strong: rgba(24, 24, 28, .66);
  --glass-rim: rgba(255, 255, 255, .14);
  --glass-rim-line: rgba(255, 255, 255, .06);
  --glass-specular: linear-gradient(180deg, rgba(255, 255, 255, .12), rgba(255, 255, 255, .02) 40%, rgba(255, 255, 255, 0) 60%);
  --glass-shadow:
    0 1px 0 rgba(255, 255, 255, .08) inset,
    0 30px 70px -28px rgba(0, 0, 0, .72),
    0 8px 24px -12px rgba(0, 0, 0, .45);
}

/* Panneau de verre : voile, reflet, bord brillant, ombres doubles. */
.glass-panel {
  position: relative;
  border-radius: var(--glass-radius);
  border: 1px solid var(--glass-rim-line);
  background-color: var(--glass-bg);
  background-image: var(--glass-specular);
  -webkit-backdrop-filter: var(--glass-blur);
  backdrop-filter: var(--glass-blur);
  box-shadow: var(--glass-shadow);
  isolation: isolate;
}
/* Trait lumineux en haut du panneau (rim-light Apple) */
.glass-panel::before {
  content: "";
  position: absolute;
  inset: 0;
  border-radius: inherit;
  padding: 1px;
  background: linear-gradient(180deg, var(--glass-rim), rgba(255, 255, 255, 0) 42%);
  -webkit-mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
  -webkit-mask-composite: xor;
  mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
  mask-composite: exclude;
  pointer-events: none;
}
@supports not ((backdrop-filter: blur(1px)) or (-webkit-backdrop-filter: blur(1px))) {
  .glass-panel {
    background-color: var(--surface);
    background-image: none;
  }
}"""
open(r"static/css/app.css", "a", encoding="utf-8").write(material)
print("OK", len(material), "caractères ajoutés")
