"""Socle PWA : service worker servi à la racine (scope "/") et page hors-ligne.

Le SW est volontairement minuscule et prudent :
- jamais de page authentifiée en cache (sessions signées + CSRF) ;
- /static/ en stale-while-revalidate (cache d'abord, rafraîchi en fond) ;
- navigation par défaut = réseau, repli sur la page hors-ligne.
"""
import json
import re
from pathlib import Path

from django.http import HttpResponse
from django.views.decorators.cache import cache_control

from core.public_theme import is_dark

SW_SOURCE = r"""
/* Road Runner Solutions — service worker minimal.
   SCOPE: / — ne rien élargir sans relecture (sécurité). */
"use strict";

var VERSION = "rrs-pwa-2026.11.16.1";
var CORE = ["offline"];
var OFFLINE_URL = "/static/pwa/offline.html";

self.addEventListener("install", function (event) {
  event.waitUntil(
    caches
      .open(VERSION)
      .then(function (cache) { return cache.addAll([OFFLINE_URL]); })
      .then(function () { return self.skipWaiting(); })
  );
});

self.addEventListener("activate", function (event) {
  event.waitUntil(
    caches
      .keys()
      .then(function (keys) {
        return Promise.all(
          keys
            .filter(function (key) { return key !== VERSION; })
            .map(function (key) { return caches.delete(key); })
        );
      })
      .then(function () { return self.clients.claim(); })
  );
});



self.addEventListener("fetch", function (event) {
  var request = event.request;
  if (request.method !== "GET") return;

  var url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  // Pages : réseau d'abord, page hors-ligne en repli.
  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request).catch(function () {
        return caches.match(OFFLINE_URL);
      })
    );
    return;
  }

  // Ressources statiques : cache d'abord, mise à jour silencieuse.
  if (url.pathname.indexOf("/static/") === 0) {
    event.respondWith(
      caches.open(VERSION).then(function (cache) {
        return cache.match(request).then(function (cached) {
          var network = fetch(request)
            .then(function (response) {
              if (response && response.status === 200) {
                cache.put(request, response.clone());
              }
              return response;
            })
            .catch(function () { return cached; });
          return cached || network;
        });
      })
    );
    return;
  }

  // Tout le reste : laisser le réseau décider (jamais de cache app).
});
"""


@cache_control(max_age=3600)
def serve_service_worker(request):
    """Fournit /sw.js à la racine (scope obligatoire — pas /static)."""
    return HttpResponse(
        SW_SOURCE,
        content_type="application/javascript; charset=utf-8",
        headers={"Service-Worker-Allowed": "/", "X-Robots-Tag": "noindex"},
    )


#: petite garde de santé pour les tests : version bien formée
_sw_version_ok = re.search(r"rrs-pwa-\d", SW_SOURCE) is not None

#: Thèmes du manifeste : start_url, couleurs et icônes suivent l'écran
#: depuis lequel l'app est installée (le mode dark, monté sous /dark,
#: doit rester sombre une fois posé sur l'écran d'accueil).
MANIFEST_THEMES = {
    False: {
        "start_url": "/cockpit/",
        "theme_color": "#ffffff",
        "background_color": "#ffffff",
        "icons_extra": [],
    },
    True: {
        "start_url": "/dark/cockpit/",
        "theme_color": "#070708",
        "background_color": "#070708",
        "icons_extra": [
            {
                "src": "/static/img/dark/mark.png",
                "sizes": "512x512",
                "type": "image/png",
            },
        ],
    },
}


def _static_manifest() -> dict:
    path = Path(__file__).resolve().parent.parent / "static" / "site.webmanifest"
    return json.loads(path.read_text(encoding="utf-8"))


def serve_manifest(request):
    """Manifeste PWA dynamique : le thème de la page d'installation suit
    l'utilisateur. Installé depuis /dark, l'app s'ouvre /dark/cockpit/.
    """
    dark = is_dark(request)
    theme = MANIFEST_THEMES[bool(dark)]
    data = _static_manifest()
    data["start_url"] = theme["start_url"]
    data["theme_color"] = theme["theme_color"]
    data["background_color"] = theme["background_color"]
    icons = list(theme["icons_extra"]) + list(data.get("icons", []))
    data["icons"] = icons
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    return HttpResponse(
        payload,
        content_type="application/manifest+json; charset=utf-8",
        headers={"Vary": "Cookie", "X-Robots-Tag": "noindex"},
    )
