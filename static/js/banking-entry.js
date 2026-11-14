/* Formulaire d'écriture bancaire : comptes, référence et aperçu live. */
(function () {
  "use strict";

  function parseAmount(value) {
    var text = String(value == null ? "" : value)
      .replace(/\u2212/g, "-")
      .replace(/\u00a0/g, "")
      .replace(/\s/g, "")
      .replace(",", ".");
    var number = parseFloat(text);
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

  function optionMap(selector) {
    var map = {};
    Array.prototype.forEach.call(
      document.querySelectorAll(selector + " option"),
      function (option) {
        map[option.value] = (option.textContent || "").trim();
      }
    );
    return map;
  }

  function setText(root, selector, value) {
    var node = root.querySelector(selector);
    if (node) node.textContent = value;
  }

  function init() {
    var form = document.querySelector("[data-banking-entry]");
    if (!form) return;

    var amount = Math.abs(parseAmount(form.dataset.amount));
    var outgoing = parseAmount(form.dataset.amount) < 0;
    var bankCode = (form.dataset.bankCode || "512").trim();
    var bankLabel = (form.dataset.bankLabel || "Banque").trim();
    var bankText = bankCode + " — " + bankLabel;
    var counterpart = document.getElementById("id_counterpart_code");
    var vatAccount = document.getElementById("id_vat_account_code");
    var vatAmount = document.getElementById("id_vat_amount");
    var reference = document.getElementById("id_reference");
    if (!counterpart) return;

    var accounts = optionMap("#counterpart-accounts");
    var vatAccounts = optionMap("#vat-accounts");
    var counterpartHint = form.querySelector("[data-counterpart-hint]");
    var referenceHint = form.querySelector("[data-reference-hint]");
    var vatLine = form.querySelector("[data-preview-vat]");
    var status = form.querySelector("[data-preview-status]");

    function update() {
      var code = (counterpart.value || "").trim().toUpperCase();
      var counterpartText = accounts[code] || (code ? "Compte " + code : "Compte de contrepartie");
      if (counterpartHint) {
        counterpartHint.textContent = code
          ? accounts[code]
            ? "Compte sélectionné : " + counterpartText
            : "Nouveau compte : " + code + " sera créé à l'enregistrement."
          : "Choisissez un compte du plan comptable.";
      }

      var vat = outgoing
        ? Math.min(Math.max(parseAmount(vatAmount && vatAmount.value), 0), amount)
        : 0;
      var vatCode = (vatAccount && vatAccount.value ? vatAccount.value : "").trim().toUpperCase();
      var vatText = vatAccounts[vatCode] || (vatCode ? "Compte " + vatCode : "TVA déductible");
      var net = Math.max(amount - vat, 0);

      var debitLabel;
      var debitAmount;
      var creditLabel;
      var creditAmount;
      if (outgoing) {
        debitLabel = counterpartText;
        debitAmount = net;
        creditLabel = bankText;
        creditAmount = amount;
      } else {
        debitLabel = bankText;
        debitAmount = amount;
        creditLabel = counterpartText;
        creditAmount = amount;
      }

      setText(form, "[data-preview-debit-label]", debitLabel);
      setText(form, "[data-preview-debit-amount]", money(debitAmount));
      setText(form, "[data-preview-vat-label]", vatText);
      setText(form, "[data-preview-vat-amount]", money(vat));
      setText(form, "[data-preview-credit-label]", creditLabel);
      setText(form, "[data-preview-credit-amount]", money(creditAmount));
      if (vatLine) vatLine.hidden = !(outgoing && vat > 0);

      if (status) {
        if (!code) {
          status.textContent = "Renseignez le compte de contrepartie pour voir l'écriture.";
          status.classList.add("is-warn");
        } else {
          status.textContent =
            "Écriture équilibrée : " + money(amount) + " au débit et au crédit.";
          status.classList.remove("is-warn");
        }
      }

      if (referenceHint) {
        referenceHint.textContent = reference && reference.value.trim()
          ? "Référence utilisée : " + reference.value.trim()
          : "Référence facultative : le relevé ou le numéro de facture.";
      }
    }

    Array.prototype.forEach.call(
      [counterpart, vatAccount, vatAmount, reference],
      function (field) {
        if (!field) return;
        field.addEventListener("input", update);
        field.addEventListener("change", update);
      }
    );

    var useReference = form.querySelector("[data-use-reference]");
    if (useReference && reference) {
      useReference.addEventListener("click", function () {
        reference.value = useReference.getAttribute("data-use-reference") || "";
        reference.dispatchEvent(new Event("input", { bubbles: true }));
      });
    }

    update();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
