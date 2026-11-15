/* Tableaux des cartes : transformation en fiches lisibles sur mobile. */
(function () {
  "use strict";

  function labelTable(table) {
    var headers = Array.prototype.map.call(
      table.querySelectorAll("thead th"),
      function (th) {
        return (th.textContent || "").trim();
      }
    );
    if (!headers.length || !table.querySelector("tbody")) return;

    Array.prototype.forEach.call(
      table.querySelectorAll("tbody tr"),
      function (row) {
        Array.prototype.forEach.call(row.children, function (cell, index) {
          if (headers[index]) cell.setAttribute("data-label", headers[index]);
        });
      }
    );

    table.classList.add("table-mobile-cards");
    var card = table.closest(".card-tight");
    if (card) card.classList.add("mobile-cards");
  }

  function init() {
    Array.prototype.forEach.call(
      document.querySelectorAll(".card-tight table"),
      labelTable
    );
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
