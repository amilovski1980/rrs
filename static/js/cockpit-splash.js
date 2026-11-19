(function () {
  "use strict";

  window.__rrsCockpitSplashStarted = true;

  /* Durée du chargement cosmétique. Seule valeur à changer. */
  var SPLASH_MS = 10000;

  var FADE_MS = 560;
  var READY_AT = 0.86;
  var MESSAGES = [
    "« Chargement des factures… »",
    "« Chargement des clients… »",
    "« Chargement du bureau… »",
    "« Préparation de votre cockpit… »",
    "« Prêt ! »"
  ];

  var root = document.getElementById("cockpit-splash");
  if (!root || !document.documentElement.classList.contains("cockpit-splash-on")) {
    if (root) root.remove();
    return;
  }

  var reduced = !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  if (reduced) root.classList.add("is-reduced");

  var statusEl = document.getElementById("cockpit-splash-status");
  var bar = root.querySelector("[data-splash-bar]");
  var progress = root.querySelector("[data-splash-progress]");
  var lastStep = -1;
  var start = 0;
  var closed = false;

  function lockPage() {
    var nodes = document.body ? document.body.children : [];
    var i;
    for (i = 0; i < nodes.length; i += 1) {
      var el = nodes[i];
      if (el === root || el.tagName === "SCRIPT") continue;
      if (el.hasAttribute("data-splash-locked")) continue;
      el.setAttribute("inert", "");
      el.setAttribute("aria-hidden", "true");
      el.setAttribute("data-splash-locked", "");
    }
  }

  function unlockPage() {
    var locked = document.querySelectorAll("[data-splash-locked]");
    var i;
    for (i = 0; i < locked.length; i += 1) {
      locked[i].removeAttribute("inert");
      locked[i].removeAttribute("aria-hidden");
      locked[i].removeAttribute("data-splash-locked");
    }
  }

  function stepFor(t) {
    var last = MESSAGES.length - 1;
    var index;
    if (t >= READY_AT) return last;
    index = Math.floor((t / READY_AT) * last);
    if (index < 0) index = 0;
    if (index > last - 1) index = last - 1;
    return index;
  }

  function showStep(step) {
    if (step === lastStep || !statusEl) return;
    statusEl.textContent = MESSAGES[step];
    lastStep = step;
    if (!reduced) {
      statusEl.classList.remove("is-swap");
      void statusEl.offsetWidth;
      statusEl.classList.add("is-swap");
    }
  }

  function paint(t) {
    var pct = Math.round(Math.min(1, Math.max(0, t)) * 100);
    if (bar) bar.style.width = pct + "%";
    if (progress && (pct === 100 || pct % 25 === 0)) {
      progress.setAttribute("aria-valuenow", String(pct));
    }
    showStep(stepFor(t));
  }

  function finish() {
    if (closed) return;
    closed = true;
    paint(1);
    root.setAttribute("aria-busy", "false");
    root.classList.add("is-done");
    window.setTimeout(function () {
      unlockPage();
      document.documentElement.classList.remove("cockpit-splash-on");
      if (root.parentNode) root.parentNode.removeChild(root);
    }, reduced ? 0 : FADE_MS);
  }

  function frame(now) {
    if (!start) start = now;
    var t = (now - start) / SPLASH_MS;
    if (t >= 1) {
      finish();
      return;
    }
    paint(t);
    window.requestAnimationFrame(frame);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", lockPage);
  } else {
    lockPage();
  }

  paint(0);
  window.requestAnimationFrame(frame);
})();
