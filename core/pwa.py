"""Socle PWA : service worker servi à la racine (scope "/") et page hors-ligne.

Le SW est volontairement minuscule et prudent :
- jamais de page authentifiée en cache (sessions signées + CSRF) ;
- /static/ en stale-while-revalidate (cache d'abord, rafraîchi en fond) ;
- navigation par défaut = réseau, repli sur la page hors-ligne.
"""
import re

from django.http import HttpResponse
from django.views.decorators.cache import cache_page

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

self.addEventListener("message", function (event) {
  if (event.data === "skip-waiting") self.skipWaiting();
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


@cache_page(3600)
def serve_service_worker(request):
    """Fournit /sw.js à la racine (scope obligatoire — pas /static)."""
    return HttpResponse(
        SW_SOURCE,
        content_type="application/javascript; charset=utf-8",
        headers={"Service-Worker-Allowed": "/", "X-Robots-Tag": "noindex"},
    )


#: petite garde de santé pour les tests : version bien formée
_sw_version_ok = re.search(r"rrs-pwa-\d", SW_SOURCE) is not None
