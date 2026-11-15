/* Change le modèle/couleur de facture sans recharger la page. */
(function () {
  "use strict";

  function status(message, isError) {
    document.querySelectorAll("[data-style-status]").forEach(function (node) {
      node.textContent = message || "";
      node.classList.toggle("is-error", !!isError);
    });
  }

  function refreshPreviews() {
    document.querySelectorAll("[data-invoice-preview]").forEach(function (box) {
      var image = box.querySelector("img[data-preview-url]");
      if (!image) return;
      var base = image.getAttribute("data-preview-url");
      var separator = base.indexOf("?") >= 0 ? "&" : "?";
      image.src = base + separator + "v=" + Date.now();
      box.classList.remove("preview-failed");
    });
  }

  function applyStyle(data) {
    document.querySelectorAll(".sheet").forEach(function (sheet) {
      Array.prototype.forEach.call(Array.from(sheet.classList), function (name) {
        if (name.indexOf("sheet-") === 0 || name.indexOf("layout-") === 0) {
          sheet.classList.remove(name);
        }
      });
      sheet.classList.add("sheet-" + data.theme);
      if (data.layout) sheet.classList.add("layout-" + data.layout);
    });

    document.querySelectorAll("form.model-pick").forEach(function (form) {
      var themeInput = form.querySelector('input[name="theme"]');
      var layoutInput = form.querySelector('input[name="layout"]');
      var selected = false;
      if (themeInput) selected = themeInput.value === data.theme;
      else if (layoutInput) selected = layoutInput.value === (data.layout || "");
      var card = form.querySelector(".model-card");
      if (card) {
        card.classList.toggle("is-on", selected);
        card.setAttribute("aria-pressed", selected ? "true" : "false");
      }
    });

    var themeField = document.querySelector('input[name="invoice_theme"]');
    if (themeField) themeField.value = data.theme || themeField.value;

    refreshPreviews();
    status("Modèle enregistré.", false);
  }

  function intercept(form) {
    if (form.dataset.stylePickerReady) return;
    form.dataset.stylePickerReady = "1";
    form.addEventListener("submit", function (event) {
      if (!window.fetch) return;
      event.preventDefault();
      var button = form.querySelector("button[type=submit]");
      if (button) button.disabled = true;
      fetch(form.action, {
        method: "POST",
        body: new FormData(form),
        headers: {
          "X-Requested-With": "XMLHttpRequest",
          Accept: "application/json",
        },
        credentials: "same-origin",
      })
        .then(function (response) {
          return response.json().then(function (data) {
            return { ok: response.ok, data: data };
          });
        })
        .then(function (result) {
          if (result.ok && result.data.ok) {
            applyStyle(result.data);
          } else {
            status(result.data.error || "Impossible de changer ce modèle.", true);
          }
        })
        .catch(function () {
          status("La modification n'a pas pu être enregistrée.", true);
        })
        .finally(function () {
          if (button) button.disabled = false;
        });
    });
  }

  function init() {
    document.querySelectorAll("form.model-pick").forEach(intercept);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
