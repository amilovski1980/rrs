"""Audit design mobile — script local (facultatif, nécessite Playwright).

Usage :
    1. Lancer le serveur    : .venv\\Scripts\\python.exe manage.py runserver 127.0.0.1:8001
    2. Installer si absent  : pip install playwright && playwright install chromium
    3. Auditer              : .venv\\Scripts\\python.exe scripts\\mobile_design_audit.py http://127.0.0.1:8001

Ce que le script vérifie sur chaque page × chaque viewport :
- débordement horizontal (scrollWidth > innerWidth) ;
- textes visibles sous 11px (lisibilité) ;
- boutons/liens interactifs sous 40px de haut (cible tactile ~44px) ;
- erreurs console JavaScript ;
- présence du shell mobile (m-header / m-footer) ;
- viewport meta sans `user-scalable=no`.

Chaque page est capturée dans screenshots/mobile-audit/.

Prérequis : la session « démo » doit être ouverte dans le contexte :
le script passe par /compte/demo/ avant le balayage (lecture seule).
"""
import json
import sys
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
SHOTS = BASE / "screenshots" / "mobile-audit"

PAGES = [
    "/",
    "/cockpit/",
    "/factures/",
    "/factures/liste/",
    "/factures/nouvelle/",
    "/factures/clients/",
    "/compta/grand-livre/",
    "/compta/balance/",
    "/achats/",
    "/tresorerie/",
]

VIEWPORTS = [
    {"width": 320, "height": 690},   # petit Android
    {"width": 360, "height": 740},   # Android classique
    {"width": 390, "height": 844},   # iPhone 14/15
    {"width": 768, "height": 1024},  # tablette portrait (frontière du layout)
]

TAP_MIN = 40          # px, tolérance sous les 44px de la CSS (--tap)
FONT_MIN = 11.0       # px, plancher de lisibilité


def run(base_url: str) -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print(
            "Playwright absent. Installez :\n"
            "  pip install playwright\n"
            "  playwright install chromium",
            file=sys.stderr,
        )
        return 2

    SHOTS.mkdir(parents=True, exist_ok=True)
    problems = []

    with sync_playwright() as p:
        browser = p.chromium.launch()
        for vp in VIEWPORTS:
            tag = f"{vp['width']}x{vp['height']}"
            context = browser.new_context(
                viewport=vp,
                device_scale_factor=2,
                is_mobile=vp["width"] < 700,
                has_touch=vp["width"] < 700,
                locale="fr-FR",
            )
            page = context.new_page()
            console_errors = []
            page.on(
                "console",
                lambda m: console_errors.append(m.text)
                if m.type == "error"
                else None,
            )

            # session démo (lecture seule) puis balayage
            page.goto(f"{base_url}/compte/demo/", wait_until="load")

            for path in PAGES:
                console_errors.clear()
                page.goto(f"{base_url}{path}", wait_until="load")
                page.wait_for_timeout(700)

                result = page.evaluate(
                    """(cfg) => {
                        const doc = document.scrollingElement;
                        const out = {
                            overflowX: doc.scrollWidth > innerWidth + 1,
                            scrollW: doc.scrollWidth,
                            header: !!document.querySelector('[data-m-header]'),
                            footer: !!document.querySelector('[data-m-footer]'),
                            smallFonts: [],
                            smallTargets: [],
                        };
                        const seen = new Set();
                        document.querySelectorAll('body *').forEach(el => {
                            const cs = getComputedStyle(el);
                            if (cs.display === 'none' || cs.visibility === 'hidden') return;
                            const r = el.getBoundingClientRect();
                            if (r.width === 0 || r.height === 0) return;
                            const txt = (el.textContent || '').trim();
                            const fs = parseFloat(cs.fontSize);
                            if (txt && fs < cfg.FONT_MIN && r.width > 0) {
                                out.smallFonts.push({ cls: (el.className + '').slice(0, 50), fs });
                            }
                            const interactive = /^(A|BUTTON|SELECT)$/.test(el.tagName)
                                || (el.tagName === 'INPUT' && !/^(checkbox|radio|hidden)$/.test(el.type || ''));
                            if (interactive && !seen.has(el)) {
                                seen.add(el);
                                const h = Math.round(r.height);
                                if (h && h < cfg.TAP_MIN) {
                                    out.smallTargets.push({ cls: (el.className + '').slice(0, 50), h });
                                }
                            }
                        });
                        const vp = document.querySelector('meta[name=viewport]');
                        out.viewportZoomLocked = vp ? /user-scalable=no|maximum-scale=/.test(vp.content) : false;
                        return out;
                    }""",
                    {"FONT_MIN": FONT_MIN, "TAP_MIN": TAP_MIN},
                )

                shots_page = SHOTS / tag
                shots_page.mkdir(parents=True, exist_ok=True)
                page.screenshot(
                    path=str(shots_page / (path.strip("/") or "landing").replace("/", "_") + ".png"),
                    full_page=True,
                )

                slug = f"{tag} {path}"
                if result["overflowX"]:
                    problems.append(f"{slug} : débordement horizontal ({result['scrollW']}px)")
                if not result["header"] and path != "/":
                    problems.append(f"{slug} : m-header absent")
                if not result["footer"] and path != "/":
                    problems.append(f"{slug} : m-footer absent")
                if result["viewportZoomLocked"]:
                    problems.append(f"{slug} : zoom bloqué (viewport user-scalable=no)")
                if console_errors:
                    problems.append(f"{slug} : {len(console_errors)} erreur(s) console JS")
                for s in result["smallFonts"][:6]:
                    problems.append(f"{slug} : texte {s['fs']}px < {FONT_MIN}px [{s['cls']}]")
                for t in result["smallTargets"][:6]:
                    problems.append(f"{slug} : cible tactile {t['h']}px < {TAP_MIN}px [{t['cls']}]")

            context.close()
        browser.close()

    report = {
        "date": datetime.now().isoformat(timespec="seconds"),
        "base_url": base_url,
        "problems": problems,
    }
    out = SHOTS / "rapport-mobile.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    if problems:
        print(f"⚠ {len(problems)} point(s) à revoir :")
        for pr in problems:
            print(f"  - {pr}")
        print(f"→ rapport complet + captures : {out}")
        return 1
    print(f"✅ Aucun problème mobile détecté. Rapport : {out}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)
    sys.exit(run(sys.argv[1].rstrip("/")))
