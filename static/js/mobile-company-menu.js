/* Ferme le sélecteur de société mobile au clic extérieur ou avec Échap. */
(function () {
  "use strict";

  function closeMenus(except) {
    document.querySelectorAll("details.m-company-menu[open]").forEach(function (menu) {
      if (menu !== except) menu.open = false;
    });
  }

  document.addEventListener("click", function (event) {
    document.querySelectorAll("details.m-company-menu[open]").forEach(function (menu) {
      if (!menu.contains(event.target)) menu.open = false;
    });
  });

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape") closeMenus();
  });
})();
