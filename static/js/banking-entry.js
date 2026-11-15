/* Rapprochement bancaire : nature, comptes, références et aperçu live. */
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

  function selectedText(select, fallback) {
    if (!select || !select.options || select.selectedIndex < 0) return fallback;
    var option = select.options[select.selectedIndex];
    return option && option.value ? (option.textContent || "").trim() : fallback;
  }

  function init() {
    var form = document.querySelector("[data-banking-entry]");
    if (!form) return;

    var amount = Math.abs(parseAmount(form.dataset.amount));
    var outgoing = parseAmount(form.dataset.amount) < 0;
    var bankCode = (form.dataset.bankCode || "512").trim();
    var bankLabel = (form.dataset.bankLabel || "Banque").trim();
    var bankText = bankCode + " — " + bankLabel;

    var nature = document.getElementById("id_nature");
    var reference = document.getElementById("id_reference");
    var counterpart = document.getElementById("id_counterpart_code");
    var chargeAccount = document.getElementById("id_charge_account_code");
    var vatAccount = document.getElementById("id_vat_account_code");
    var vatAmount = document.getElementById("id_vat_amount");
    var feeAmount = document.getElementById("id_fee_amount");
    var feeAccount = document.getElementById("id_fee_account_code");
    var grossAmount = document.getElementById("id_gross_amount");
    var loanPrincipal = document.getElementById("id_loan_principal");
    var loanInterest = document.getElementById("id_loan_interest");
    var transferAccount = document.getElementById("id_transfer_account");
    var vatPaymentAccount = document.getElementById("id_vat_payment_account_code");
    var accounts = optionMap("#counterpart-accounts");
    var vatAccounts = optionMap("#vat-accounts");
    var sectionNodes = form.querySelectorAll("[data-nature-section]");
    var previewLines = form.querySelector("[data-preview-lines]");
    var status = form.querySelector("[data-preview-status]");
    var referenceHint = form.querySelector("[data-reference-hint]");
    var counterpartHint = form.querySelector("[data-counterpart-hint]");

    function accountText(code, fallback) {
      code = (code || "").trim().toUpperCase();
      return accounts[code] || (code ? "Compte " + code : fallback);
    }

    function vatText(code) {
      code = (code || "").trim().toUpperCase();
      return vatAccounts[code] || (code ? "Compte " + code : "TVA déductible");
    }

    function currentNature() {
      return nature ? nature.value : "other";
    }

    function syncSections() {
      var value = currentNature();
      Array.prototype.forEach.call(sectionNodes, function (node) {
        node.hidden = node.getAttribute("data-nature-section") !== value;
      });
    }

    function addLine(lines, side, label, value) {
      if (!value || Math.abs(value) < 0.005) return;
      lines.push({ side: side, label: label, value: value });
    }

    function buildLines() {
      var lines = [];
      var code = currentNature();
      var fee = Math.max(parseAmount(feeAmount && feeAmount.value), 0);
      var vat = Math.max(parseAmount(vatAmount && vatAmount.value), 0);

      if (code === "customer_receipt") {
        var gross = parseAmount(grossAmount && grossAmount.value) || amount + fee;
        addLine(lines, "Débit", bankText, amount);
        addLine(lines, "Débit", accountText(feeAccount && feeAccount.value, "Frais bancaires"), fee);
        addLine(lines, "Crédit", "411 — Clients", gross);
      } else if (code === "supplier_payment") {
        var paid = parseAmount(grossAmount && grossAmount.value) || Math.max(amount - fee, 0);
        addLine(lines, "Débit", "401 — Fournisseurs", paid);
        addLine(lines, "Débit", accountText(feeAccount && feeAccount.value, "Frais bancaires"), fee);
        addLine(lines, "Crédit", bankText, amount);
      } else if (code === "expense") {
        addLine(
          lines,
          "Débit",
          accountText(chargeAccount && chargeAccount.value, "Compte de charge"),
          Math.max(amount - vat, 0)
        );
        addLine(lines, "Débit", vatText(vatAccount && vatAccount.value), vat);
        addLine(lines, "Crédit", bankText, amount);
      } else if (code === "bank_fee") {
        addLine(lines, "Débit", "627000 — Frais bancaires", amount);
        addLine(lines, "Crédit", bankText, amount);
      } else if (code === "loan_payment") {
        var principal = parseAmount(loanPrincipal && loanPrincipal.value);
        var interest = parseAmount(loanInterest && loanInterest.value);
        addLine(lines, "Débit", "164 — Emprunts", principal);
        addLine(lines, "Débit", "661 — Charges financières", interest);
        addLine(lines, "Crédit", bankText, amount);
      } else if (code === "internal_transfer") {
        var other = selectedText(transferAccount, "Compte de destination");
        if (outgoing) {
          addLine(lines, "Débit", other, amount);
          addLine(lines, "Crédit", bankText, amount);
        } else {
          addLine(lines, "Débit", bankText, amount);
          addLine(lines, "Crédit", other, amount);
        }
      } else if (code === "vat_payment") {
        addLine(
          lines,
          "Débit",
          vatText(vatPaymentAccount && vatPaymentAccount.value),
          amount
        );
        addLine(lines, "Crédit", bankText, amount);
      } else {
        var otherText = accountText(
          counterpart && counterpart.value,
          "Compte de contrepartie"
        );
        if (outgoing) {
          addLine(lines, "Débit", otherText, Math.max(amount - vat, 0));
          addLine(lines, "Débit", vatText(vatAccount && vatAccount.value), vat);
          addLine(lines, "Crédit", bankText, amount);
        } else {
          addLine(lines, "Débit", bankText, amount);
          addLine(lines, "Crédit", otherText, amount);
        }
      }
      return lines;
    }

    function render() {
      var lines = buildLines();
      var debit = 0;
      var credit = 0;
      if (previewLines) {
        previewLines.textContent = "";
        lines.forEach(function (line) {
          var row = document.createElement("div");
          row.className = "entry-preview-line";
          var label = document.createElement("span");
          var badge = document.createElement("span");
          badge.className = "badge" + (line.side === "Crédit" ? " badge-blue" : "");
          badge.textContent = line.side;
          label.appendChild(badge);
          label.appendChild(document.createTextNode(" " + line.label));
          var amountNode = document.createElement("b");
          amountNode.textContent = money(line.value);
          row.appendChild(label);
          row.appendChild(amountNode);
          previewLines.appendChild(row);
          if (line.side === "Débit") debit += line.value;
          else credit += line.value;
        });
      }

      if (status) {
        var missing = false;
        var code = currentNature();
        if (code === "expense" && !(chargeAccount && chargeAccount.value.trim())) missing = true;
        if (code === "other" && !(counterpart && counterpart.value.trim())) missing = true;
        if (code === "internal_transfer" && !(transferAccount && transferAccount.value)) missing = true;
        if (code === "vat_payment" && !(vatPaymentAccount && vatPaymentAccount.value.trim())) missing = true;
        if (missing) {
          status.textContent = "Complétez les champs manquants pour voir l'écriture.";
          status.classList.add("is-warn");
        } else if (Math.abs(debit - credit) > 0.01) {
          status.textContent =
            "Déséquilibre : " + money(debit) + " au débit contre " + money(credit) + " au crédit.";
          status.classList.add("is-warn");
        } else {
          status.textContent =
            "Écriture équilibrée : " + money(debit) + " au débit et au crédit.";
          status.classList.remove("is-warn");
        }
      }

      if (counterpartHint) {
        var accountCode = (counterpart && counterpart.value ? counterpart.value : "").trim().toUpperCase();
        counterpartHint.textContent = accountCode
          ? accounts[accountCode]
            ? "Compte sélectionné : " + accounts[accountCode]
            : "Nouveau compte : " + accountCode + " sera créé à l'enregistrement."
          : "Choisissez un compte du plan comptable.";
      }
      if (referenceHint) {
        referenceHint.textContent =
          reference && reference.value.trim()
            ? "Référence utilisée : " + reference.value.trim()
            : "Référence facultative : le relevé ou le numéro de facture.";
      }
    }

    function syncFeeAndGross() {
      var code = currentNature();
      if (code !== "customer_receipt" && code !== "supplier_payment") return;
      var fee = Math.max(parseAmount(feeAmount && feeAmount.value), 0);
      if (grossAmount) {
        var target = code === "customer_receipt" ? amount + fee : Math.max(amount - fee, 0);
        grossAmount.value = target.toFixed(2);
      }
    }

    function syncLoan() {
      if (currentNature() !== "loan_payment") return;
      var principal = parseAmount(loanPrincipal && loanPrincipal.value);
      var interest = parseAmount(loanInterest && loanInterest.value);
      if (document.activeElement === loanPrincipal && loanInterest) {
        loanInterest.value = Math.max(amount - principal, 0).toFixed(2);
      } else if (document.activeElement === loanInterest && loanPrincipal) {
        loanPrincipal.value = Math.max(amount - interest, 0).toFixed(2);
      }
    }

    function update() {
      syncSections();
      render();
    }

    Array.prototype.forEach.call(
      [
        nature,
        reference,
        counterpart,
        chargeAccount,
        vatAccount,
        vatAmount,
        feeAmount,
        feeAccount,
        grossAmount,
        loanPrincipal,
        loanInterest,
        transferAccount,
        vatPaymentAccount,
      ],
      function (field) {
        if (!field) return;
        field.addEventListener("input", update);
        field.addEventListener("change", update);
      }
    );

    if (feeAmount) {
      feeAmount.addEventListener("input", function () {
        syncFeeAndGross();
        update();
      });
    }
    if (loanPrincipal) loanPrincipal.addEventListener("input", function () { syncLoan(); update(); });
    if (loanInterest) loanInterest.addEventListener("input", function () { syncLoan(); update(); });
    if (nature) nature.addEventListener("change", function () { syncFeeAndGross(); update(); });

    var useReference = form.querySelector("[data-use-reference]");
    if (useReference && reference) {
      useReference.addEventListener("click", function () {
        reference.value = useReference.getAttribute("data-use-reference") || "";
        reference.dispatchEvent(new Event("input", { bubbles: true }));
      });
    }

    syncFeeAndGross();
    update();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
