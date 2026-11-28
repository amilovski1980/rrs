/* Bascule clair / sombre de la vitrine.
   Le sombre reste le thème officiel ; le clair inverse les tokens de dark.css.
   Le choix est mémorisé localement, sans cookie ni requête serveur. */
(function () {
  "use strict";

  var KEY = "rrs-theme";
  var META_COLORS = { dark: "#070708", light: "#f8f5f0" };
  var root = document.documentElement;

  function current() {
    return root.dataset.theme === "light" ? "light" : "dark";
  }

  function label(theme) {
    return theme === "light" ? "Passer en version sombre" : "Passer en version claire";
  }

  function apply(theme) {
    root.dataset.theme = theme;
    var meta = document.getElementById("rrs-theme-color");
    if (meta) {
      meta.setAttribute("content", META_COLORS[theme] || META_COLORS.dark);
    }
    document.querySelectorAll("[data-theme-toggle]").forEach(function (button) {
      var target = theme === "light" ? "Version sombre" : "Version claire";
      button.setAttribute("aria-label", label(theme));
      button.setAttribute("title", target);
      button.setAttribute("aria-pressed", theme === "light" ? "true" : "false");
    });
  }

  function store(theme) {
    try {
      localStorage.setItem(KEY, theme);
    } catch (error) {
      /* Navigation privée : la bascule reste valable pour la page. */
    }
  }

  document.addEventListener("click", function (event) {
    var button = event.target.closest("[data-theme-toggle]");
    if (!button) return;
    var next = current() === "light" ? "dark" : "light";
    apply(next);
    store(next);
  });

  window.addEventListener("storage", function (event) {
    if (event.key === KEY && (event.newValue === "light" || event.newValue === "dark")) {
      apply(event.newValue);
    }
  });

  apply(current());
})();
