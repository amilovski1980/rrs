/* Actions mobiles.
   Décision design (app bancaire) : plus de bouton primaire flottant
   au-dessus de la barre d'onglets. Le CTA principal reste dans la page,
   les menus « Actions » restent à leur place. Ce module ne branche plus
   que l'onglet Aminia du pied de page. */
(function () {
  "use strict";

  function bindFooterAgent() {
    Array.prototype.forEach.call(
      document.querySelectorAll("[data-agent-footer-open]"),
      function (button) {
        if (button.dataset.agentBound) return;
        button.dataset.agentBound = "1";
        button.addEventListener("click", function (event) {
          event.preventDefault();
          event.stopPropagation();
          /* Ne pas couper un appel en cours en retapant l'onglet Aminia. */
          if (document.body.classList.contains("agent-open")) return;
          var fab = document.querySelector("[data-agent-open]");
          if (fab) fab.click();
        });
      }
    );
  }

  function bindFooterScanner() {
    Array.prototype.forEach.call(
      document.querySelectorAll("[data-scan-open]"),
      function (button) {
        if (button.dataset.scanBound) return;
        button.dataset.scanBound = "1";
        button.addEventListener("click", function (event) {
          event.preventDefault();
          event.stopPropagation();
          var prefix =
            document.documentElement.getAttribute("data-theme") === "dark"
              ? "/dark"
              : "";
          window.location.href = prefix + "/factures/tickets/import/";
        });
      }
    );
  }

  function sync() {
    bindFooterAgent();
    bindFooterScanner();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", sync);
  } else {
    sync();
  }
})();
