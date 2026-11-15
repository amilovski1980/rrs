/* Tableaux des cartes : transformation en fiches lisibles sur mobile. */
(function () {
  "use strict";

  var SKIP = [
    "invoice-lines-table",
    "sheet-table",
    "compare",
    "table-mobile-cards-off",
  ];

  function shouldSkip(table) {
    if (table.dataset.mobileCards === "off") return true;
    for (var i = 0; i < SKIP.length; i += 1) {
      if (table.classList.contains(SKIP[i])) return true;
    }
    if (table.closest(".invoice-lines-scroll, .sheet-table-wrap")) return true;
    if (table.closest(".model-grid, .model-picker")) return true;
    return false;
  }

  function labelTable(table) {
    if (shouldSkip(table)) return;
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
        var cells = Array.prototype.slice.call(row.children);
        var hasAction = cells.some(function (cell) {
          return !!cell.querySelector("a.btn, button.btn, form button");
        });
        Array.prototype.forEach.call(cells, function (cell, index) {
          var label = headers[index] || "";
          if (!label && hasAction && cell.querySelector("a, button")) {
            label = "Action";
          }
          if (label) cell.setAttribute("data-label", label);
        });
      }
    );

    table.classList.add("table-mobile-cards");
    var card = table.closest(".card-tight, .card");
    if (card) card.classList.add("mobile-cards");
  }

  function init() {
    Array.prototype.forEach.call(
      document.querySelectorAll(".card table, .card-tight table"),
      labelTable
    );
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
