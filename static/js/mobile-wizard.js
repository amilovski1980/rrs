/* Assistant mobile par étapes : facture, devis, avoir, achat.
 *
 * Activation : <form data-mobile-wizard> avec des sections
 * <div data-wizard-step data-step-label="Client">…</div>.
 * Sur desktop, les sections restent affichées normalement (display: contents).
 */
(function () {
  "use strict";

  var MOBILE_QUERY = "(max-width: 768px)";
  var mql = window.matchMedia(MOBILE_QUERY);

  function fieldValue(form, selector) {
    var field = form.querySelector(selector);
    return field ? String(field.value || "").trim() : "";
  }

  function selectedLabel(select) {
    if (!select || !select.value) return "";
    var option = select.options[select.selectedIndex];
    return option ? String(option.textContent || "").trim() : "";
  }

  function readMoney(node) {
    if (!node) return 0;
    var raw = String(node.textContent || "")
      .replace(/\u00a0/g, " ")
      .replace(/[^\d,.-]/g, "")
      .replace(/\s/g, "")
      .replace(",", ".");
    var value = parseFloat(raw);
    return Number.isFinite(value) ? value : 0;
  }

  function formatDate(value) {
    if (!value) return "";
    var parts = String(value).split("-");
    if (parts.length !== 3) return value;
    return parts[2] + "/" + parts[1] + "/" + parts[0];
  }

  function appendRecapRow(box, label, value, extraClass) {
    if (!value) return;
    var row = document.createElement("div");
    row.className = "wizard-recap-row" + (extraClass ? " " + extraClass : "");
    var key = document.createElement("span");
    key.textContent = label;
    var strong = document.createElement("strong");
    strong.textContent = value;
    row.appendChild(key);
    row.appendChild(strong);
    box.appendChild(row);
  }

  function fillRecap(form, box) {
    if (!box) return;
    box.textContent = "";

    var clientName =
      fieldValue(form, "#id_client_name") ||
      selectedLabel(form.querySelector("[data-client-select]"));
    appendRecapRow(box, "Client", clientName);

    var supplierName =
      fieldValue(form, "#id_supplier_name") ||
      selectedLabel(form.querySelector("#id_supplier"));
    appendRecapRow(box, "Fournisseur", supplierName);

    var invoiceNumber = fieldValue(form, "#id_number");
    appendRecapRow(box, "N° facture", invoiceNumber);

    var lines = form.querySelectorAll("[data-line-form]");
    if (lines.length) {
      var used = 0;
      Array.prototype.forEach.call(lines, function (row) {
        var description = row.querySelector('[name$="-description"]');
        var price = row.querySelector('[name$="-unit_price"]');
        var hasText = description && description.value.trim();
        var hasPrice =
          price && parseFloat(String(price.value).replace(",", ".")) > 0;
        if (hasText || hasPrice) used += 1;
      });
      if (used) {
        appendRecapRow(box, "Lignes", used + (used > 1 ? " lignes" : " ligne"));
      }
    }

    var ttcNode = form.querySelector("[data-preview-ttc]");
    var ttcValue = ttcNode ? String(ttcNode.textContent || "").trim() : "";
    if (!readMoney(ttcNode)) {
      var amountTtc = parseFloat(
        fieldValue(form, "#id_amount_ttc").replace(",", ".")
      );
      ttcValue =
        Number.isFinite(amountTtc) && amountTtc > 0
          ? amountTtc.toFixed(2).replace(".", ",") + " €"
          : "";
    }
    appendRecapRow(box, "Total TTC", ttcValue, "wizard-recap-total");

    var date =
      fieldValue(form, "#id_due_date") ||
      fieldValue(form, "#id_valid_until") ||
      fieldValue(form, "#id_invoice_date");
    appendRecapRow(box, "Échéance", formatDate(date));

    var reason = fieldValue(form, "#id_reason");
    appendRecapRow(
      box,
      "Motif",
      reason.length > 90 ? reason.slice(0, 90) + "…" : reason
    );

    if (!box.children.length) {
      var empty = document.createElement("p");
      empty.className = "micro";
      empty.textContent = "Vérifiez les informations puis enregistrez.";
      box.appendChild(empty);
    }
  }

  function makeElement(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text) node.textContent = text;
    return node;
  }

  function initWizard(form) {
    if (form._mobileWizard) return;
    var steps = Array.prototype.slice.call(
      form.querySelectorAll("[data-wizard-step]")
    );
    if (steps.length < 2) return;
    var forced = form.getAttribute("data-wizard-mode") === "always";
    if (forced) form.classList.add("wizard-forced");

    var originalSubmit = form.querySelector(
      ".form-actions-bar button[type='submit'], .form-actions button[type='submit']"
    );
    var submitLabel = originalSubmit
      ? originalSubmit.textContent.trim()
      : "Enregistrer";

    var head = makeElement("div", "wizard-head");
    var headTop = makeElement("div", "wizard-head-top");
    var kicker = makeElement("span", "wizard-kicker");
    var label = makeElement("span", "wizard-label");
    headTop.appendChild(kicker);
    headTop.appendChild(label);
    var track = makeElement("div", "wizard-track");
    var trackFill = document.createElement("i");
    track.appendChild(trackFill);
    head.appendChild(headTop);
    head.appendChild(track);

    var nav = makeElement("div", "wizard-nav");
    var back = makeElement("button", "btn btn-ghost wizard-back", "← Précédent");
    back.type = "button";
    var position = makeElement("span", "wizard-position");
    var next = makeElement("button", "btn btn-primary wizard-next", "Suivant →");
    next.type = "button";
    var submit = makeElement(
      "button",
      "btn btn-primary wizard-submit",
      submitLabel
    );
    submit.type = "submit";
    var originalCancel = form.querySelector(
      ".form-actions-bar a.btn, .form-actions a.btn"
    );
    var cancel = null;
    if (originalCancel) {
      cancel = makeElement(
        "a",
        "wizard-cancel",
        originalCancel.textContent.trim() || "Annuler"
      );
      cancel.href = originalCancel.getAttribute("href") || "#";
    }
    nav.appendChild(back);
    nav.appendChild(position);
    nav.appendChild(next);
    nav.appendChild(submit);
    if (cancel) nav.appendChild(cancel);

    form.insertBefore(head, steps[0]);
    form.appendChild(nav);
    form.classList.add("wizard-mode");
    document.body.classList.add("wizard-active");

    var index = 0;

    function paint() {
      steps.forEach(function (step, i) {
        step.classList.toggle("is-active", i === index);
      });
      kicker.textContent = "Étape " + (index + 1) + " sur " + steps.length;
      label.textContent =
        steps[index].getAttribute("data-step-label") || "Formulaire";
      position.textContent = index + 1 + " / " + steps.length;
      trackFill.style.width = ((index + 1) / steps.length) * 100 + "%";
      back.hidden = index === 0;
      next.hidden = index === steps.length - 1;
      submit.hidden = index !== steps.length - 1;
      if (cancel) cancel.hidden = index !== steps.length - 1;
      if (index === steps.length - 1) {
        fillRecap(form, steps[index].querySelector("[data-wizard-recap]"));
      }
    }

    function goTo(nextIndex, scroll) {
      index = Math.max(0, Math.min(nextIndex, steps.length - 1));
      paint();
      if (scroll) {
        var top = head.getBoundingClientRect().top + window.pageYOffset - 12;
        window.scrollTo({ top: top, behavior: "smooth" });
      }
    }

    function stepIsValid(step) {
      var fields = step.querySelectorAll("input, select, textarea");
      for (var i = 0; i < fields.length; i += 1) {
        var field = fields[i];
        if (field.disabled || field.type === "hidden") continue;
        if (field.closest(".is-deleted")) continue;
        if (!field.checkValidity()) {
          field.reportValidity();
          return false;
        }
      }
      return true;
    }

    back.addEventListener("click", function () {
      goTo(index - 1, true);
    });

    next.addEventListener("click", function () {
      if (!stepIsValid(steps[index])) return;
      goTo(index + 1, true);
    });

    // Entrée dans un champ texte = étape suivante, pas un envoi prématuré.
    form.addEventListener("keydown", function (event) {
      if (event.key !== "Enter") return;
      if (!event.target.matches("input")) return;
      if (
        event.target.type === "submit" ||
        event.target.type === "checkbox"
      ) {
        return;
      }
      event.preventDefault();
      if (index < steps.length - 1) {
        if (stepIsValid(steps[index])) goTo(index + 1, true);
      } else {
        if (form.requestSubmit) {
          form.requestSubmit();
        } else {
          form.submit();
        }
      }
    });

    form.addEventListener("submit", function (event) {
      for (var i = 0; i < steps.length; i += 1) {
        if (!stepIsValid(steps[i])) {
          event.preventDefault();
          goTo(i, true);
          return;
        }
      }
    });

    form.addEventListener("input", function () {
      if (index === steps.length - 1) {
        fillRecap(form, steps[index].querySelector("[data-wizard-recap]"));
      }
    });

    form._mobileWizard = {
      steps: steps,
      head: head,
      nav: nav,
      reset: function () {
        index = 0;
        paint();
      },
    };

    // Après une erreur serveur, ouvrir directement l'étape concernée.
    var firstError = form.querySelector(
      ".error, .form-errors li, .errorlist li, .invalid-feedback"
    );
    var errorStep = firstError ? firstError.closest("[data-wizard-step]") : null;
    if (errorStep) {
      index = steps.indexOf(errorStep);
      var details = errorStep.querySelector("details");
      if (details) details.open = true;
    }
    paint();
  }

  function teardownWizard(form) {
    var state = form._mobileWizard;
    if (!state) return;
    form.classList.remove("wizard-mode");
    state.steps.forEach(function (step) {
      step.classList.remove("is-active");
    });
    state.head.remove();
    state.nav.remove();
    form._mobileWizard = null;
    if (!document.querySelector("[data-mobile-wizard].wizard-mode")) {
      document.body.classList.remove("wizard-active");
    }
  }

  function sync() {
    Array.prototype.forEach.call(
      document.querySelectorAll("form[data-mobile-wizard]"),
      function (form) {
        if (mql.matches || form.getAttribute("data-wizard-mode") === "always") {
          initWizard(form);
        } else {
          teardownWizard(form);
        }
      }
    );
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", sync);
  } else {
    sync();
  }

  if (mql.addEventListener) {
    mql.addEventListener("change", sync);
  } else if (mql.addListener) {
    mql.addListener(sync);
  }
})();
