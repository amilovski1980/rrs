/* Éditeur de lignes de facture : préremplissage catalogue/client, totaux
   et aperçu fidèle de la facture dans l'étape finale du wizard. */
(function () {
  "use strict";

  function parseNumber(value) {
    var normalized = String(value == null ? "" : value)
      .replace(/\s/g, "")
      .replace(",", ".");
    var number = parseFloat(normalized);
    return Number.isFinite(number) ? number : 0;
  }

  function money(value) {
    try {
      return new Intl.NumberFormat("fr-FR", {
        style: "currency",
        currency: "EUR",
      }).format(value || 0);
    } catch (error) {
      return (value || 0).toFixed(2).replace(".", ",") + " €";
    }
  }

  function setValue(id, value) {
    var input = document.getElementById(id);
    if (input) input.value = value == null ? "" : value;
  }

  function bindSheetPreview(root) {
    var holder = root.querySelector("[data-wizard-sheet]");
    if (!holder || holder.dataset.previewWired === "1") return;
    holder.dataset.previewWired = "1";
    var url = holder.getAttribute("data-preview-url") || window.location.pathname;
    var timer = null;

    function load() {
      holder.innerHTML =
        '<p class="empty" style="padding:14px">Génération de l\'aperçu…</p>';
      fetch(url, {
        method: "POST",
        body: new FormData(root),
        credentials: "same-origin",
        headers: {
          "X-Requested-With": "XMLHttpRequest",
          Accept: "application/json",
        },
      })
        .then(function (response) {
          return response
            .json()
            .then(
              function (data) { return { ok: response.ok, data: data, status: response.status }; },
              function () { return { ok: false, data: null, status: response.status }; }
            );
        })
        .then(function (payload) {
          if (payload && payload.ok && payload.data && payload.data.html) {
            holder.innerHTML = payload.data.html;
            return;
          }
          var detail = payload && payload.status ? " (erreur " + payload.status + ")" : "";
          holder.innerHTML =
            '<p class="error">Aperçu indisponible' + detail + ". Réessayez.</p>";
        })
        .catch(function () {
          holder.innerHTML =
            '<p class="error">Impossible de générer l\'aperçu (réseau). Réessayez.</p>';
        });
    }

    root.addEventListener("wizard:final", load);
    root.addEventListener(
      "wizard:final-input",
      function () {
        window.clearTimeout(timer);
        timer = window.setTimeout(load, 700);
      }
    );
    var refresh = root.querySelector("[data-sheet-refresh]");
    if (refresh) refresh.addEventListener("click", load);
    // Premier rendu si l'étape aperçu est déjà affichée (erreur serveur…).
    var active = holder.closest(".wizard-step");
    if (active && active.classList.contains("is-active")) load();
  }

  function init() {
    var root = document.querySelector("[data-invoice-form]");
    if (!root) return;

    var table = root.querySelector("[data-line-rows]");
    var totalForms = root.querySelector('input[name$="-TOTAL_FORMS"]');
    var emptyTemplate = root.querySelector("template[data-empty-form]");
    var addButton = root.querySelector("[data-add-line]");
    var reverseCharge = document.getElementById("id_reverse_charge");
    var previewHt = root.querySelector("[data-preview-ht]");
    var previewVat = root.querySelector("[data-preview-vat]");
    var previewTtc = root.querySelector("[data-preview-ttc]");
    var advanced = root.querySelector("[data-invoice-advanced]");

    // Mobile : replier les options secondaires, sauf si une erreur doit être vue.
    if (
      advanced &&
      window.matchMedia("(max-width: 768px)").matches &&
      !advanced.querySelector(".error")
    ) {
      advanced.open = false;
    }

    function rowDeleted(row) {
      var checkbox = row.querySelector('input[name$="-DELETE"]');
      return !!(checkbox && checkbox.checked);
    }

    function rowField(row, suffix) {
      return row.querySelector('[name$="-' + suffix + '"]');
    }

    var sheetPreview = bindSheetPreview(root);

    function updateRow(row) {
      var quantity = parseNumber(rowField(row, "quantity") && rowField(row, "quantity").value);
      var price = parseNumber(rowField(row, "unit_price") && rowField(row, "unit_price").value);
      var totalCell = row.querySelector("[data-line-total]");
      if (totalCell) totalCell.textContent = money(quantity * price);
    }

    function escapeRegExp(value) {
      return String(value).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    }

    // Après une suppression, les index Django doivent rester contigus :
    // sans cela, TOTAL_FORMS ne correspond plus aux lignes du DOM et le POST
    // réclame des champs qui n'existent plus.
    function reindexRows() {
      if (!table || !totalForms) return;
      var prefix = totalForms.name.replace(/-TOTAL_FORMS$/, "");
      var pattern = new RegExp("(^|_)" + escapeRegExp(prefix) + "-\\d+-");
      var rows = table.querySelectorAll("[data-line-form]");
      Array.prototype.forEach.call(rows, function (row, index) {
        function rewrite(value) {
          if (!value) return value;
          return value.replace(pattern, function (match, start) {
            return start + prefix + "-" + index + "-";
          });
        }
        Array.prototype.forEach.call(
          row.querySelectorAll("input, select, textarea"),
          function (field) {
            if (field.name) field.name = rewrite(field.name);
            if (field.id) field.id = rewrite(field.id);
          }
        );
        Array.prototype.forEach.call(row.querySelectorAll("label[for]"), function (label) {
          label.setAttribute("for", rewrite(label.getAttribute("for")));
        });
      });
      totalForms.value = rows.length;
    }

    function updateTotals() {
      if (!table) return;
      var totalHt = 0;
      var totalVat = 0;
      Array.prototype.forEach.call(
        table.querySelectorAll("[data-line-form]"),
        function (row) {
          if (rowDeleted(row) || row.classList.contains("is-deleted")) return;
          var quantity = parseNumber(rowField(row, "quantity") && rowField(row, "quantity").value);
          var price = parseNumber(rowField(row, "unit_price") && rowField(row, "unit_price").value);
          var rate = parseNumber(rowField(row, "vat_rate") && rowField(row, "vat_rate").value);
          var amount = quantity * price;
          totalHt += amount;
          totalVat += amount * rate / 100;
          var totalCell = row.querySelector("[data-line-total]");
          if (totalCell) totalCell.textContent = money(amount);
        }
      );
      var reverse = !!(reverseCharge && reverseCharge.checked);
      var vat = reverse ? 0 : totalVat;
      if (previewHt) previewHt.textContent = money(totalHt);
      if (previewVat) {
        previewVat.textContent = money(vat) + (reverse ? " (autoliquidation)" : "");
      }
      if (previewTtc) previewTtc.textContent = money(totalHt + vat);
    }

    function addRow() {
      if (!table || !totalForms) return;
      // D'abord : déplier une ligne déjà rendue mais masquée (écran épuré,
      // un seul formulaire visible au départ).
      var hiddenRow = table.querySelector("[data-line-form][hidden]");
      if (hiddenRow) {
        hiddenRow.removeAttribute("hidden");
        var description = rowField(hiddenRow, "description");
        if (description) description.focus();
        if (window.matchMedia("(max-width: 768px)").matches && hiddenRow.scrollIntoView) {
          hiddenRow.scrollIntoView({ behavior: "smooth", block: "center" });
        }
        updateTotals();
        return;
      }
      if (!emptyTemplate) return;
      var index = table.querySelectorAll("[data-line-form]").length;
      var wrapper = document.createElement("tbody");
      wrapper.innerHTML = emptyTemplate.innerHTML.replace(/__prefix__/g, index);
      var row = wrapper.querySelector("[data-line-form]");
      if (!row) return;
      table.appendChild(row);
      totalForms.value = index + 1;
      var description = rowField(row, "description");
      if (description) description.focus();
      if (window.matchMedia("(max-width: 768px)").matches && row.scrollIntoView) {
        row.scrollIntoView({ behavior: "smooth", block: "center" });
      }
      updateTotals();
    }

    if (addButton) addButton.addEventListener("click", addRow);

    if (table) {
      table.addEventListener("input", function (event) {
        var row = event.target.closest("[data-line-form]");
        if (row) updateRow(row);
        updateTotals();
      });

      table.addEventListener("change", function (event) {
        var target = event.target;
        var row = target.closest("[data-line-form]");
        if (!row) return;

        if (target.matches("[data-product-select]")) {
          var option = target.options[target.selectedIndex];
          if (target.value && option) {
            var description = rowField(row, "description");
            var price = rowField(row, "unit_price");
            var rate = rowField(row, "vat_rate");
            if (description) {
              description.value =
                option.getAttribute("data-product-description") ||
                option.getAttribute("data-product-label") ||
                "";
            }
            if (price) price.value = option.getAttribute("data-product-unit-price") || "";
            if (rate) rate.value = option.getAttribute("data-product-vat-rate") || "";
          }
        }

        if (target.matches('input[name$="-DELETE"]')) {
          row.classList.toggle("is-deleted", target.checked);
        }
        updateRow(row);
        updateTotals();
      });

      table.addEventListener("click", function (event) {
        var button = event.target.closest("[data-remove-line]");
        if (!button) return;
        var row = button.closest("[data-line-form]");
        if (row) {
          row.remove();
          reindexRows();
          updateTotals();
        }
      });
    }

    var clientSelect = root.querySelector("[data-client-select]");
    if (clientSelect) {
      clientSelect.addEventListener("change", function () {
        if (!clientSelect.value) return; // Aucune fiche : les champs restent libres.
        var option = clientSelect.options[clientSelect.selectedIndex];
        if (!option) return;
        setValue("id_client_name", option.getAttribute("data-client-name") || "");
        setValue("id_client_siren", option.getAttribute("data-client-siren") || "");
        setValue("id_client_tva_intra", option.getAttribute("data-client-tva") || "");
      });
    }

    if (reverseCharge) reverseCharge.addEventListener("change", updateTotals);
    updateTotals();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
