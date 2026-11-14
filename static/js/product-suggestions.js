/* Aide à la saisie des produits/services selon le métier de la société. */
(function () {
  "use strict";

  function normalize(value) {
    return String(value || "")
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .toLowerCase()
      .trim();
  }

  function init() {
    var root = document.querySelector("[data-product-autocomplete]");
    if (!root) return;
    var input = root.querySelector("input");
    var panel = root.querySelector("[data-product-suggestions]");
    var dataNode = document.getElementById("product-suggestions");
    if (!input || !panel || !dataNode) return;

    var suggestions = [];
    try {
      suggestions = JSON.parse(dataNode.textContent) || [];
    } catch (error) {
      suggestions = [];
    }
    if (!suggestions.length) return;

    var activeIndex = -1;
    var current = [];
    var listId = "product-suggestions-list";
    panel.id = listId;
    input.setAttribute("role", "combobox");
    input.setAttribute("aria-autocomplete", "list");
    input.setAttribute("aria-controls", listId);
    input.setAttribute("aria-expanded", "false");
    input.setAttribute("autocomplete", "off");

    function close() {
      panel.hidden = true;
      input.setAttribute("aria-expanded", "false");
      input.removeAttribute("aria-activedescendant");
      activeIndex = -1;
    }

    function select(item) {
      if (!item) return;
      input.value = item.label;
      var form = input.closest("form");
      var description = form && form.querySelector('[name="description"]');
      if (description && !description.value.trim() && item.description) {
        description.value = item.description;
        description.dispatchEvent(new Event("input", { bubbles: true }));
      }
      input.dispatchEvent(new Event("input", { bubbles: true }));
      input.dispatchEvent(new Event("change", { bubbles: true }));
      close();
    }

    function paint() {
      panel.textContent = "";
      current.forEach(function (item, index) {
        var option = document.createElement("div");
        option.className = "product-suggestion";
        option.id = listId + "-" + index;
        option.setAttribute("role", "option");
        option.setAttribute("aria-selected", index === activeIndex ? "true" : "false");
        var label = document.createElement("b");
        label.textContent = item.label;
        option.appendChild(label);
        if (item.description) {
          var description = document.createElement("span");
          description.textContent = item.description;
          option.appendChild(description);
        }
        option.addEventListener("mousedown", function (event) {
          event.preventDefault();
          select(item);
        });
        option.addEventListener("click", function () {
          select(item);
        });
        panel.appendChild(option);
      });
      panel.hidden = current.length === 0;
      input.setAttribute("aria-expanded", current.length ? "true" : "false");
      if (activeIndex >= 0 && current[activeIndex]) {
        var activeId = listId + "-" + activeIndex;
        input.setAttribute("aria-activedescendant", activeId);
        var active = document.getElementById(activeId);
        if (active && active.scrollIntoView) {
          active.scrollIntoView({ block: "nearest" });
        }
      } else {
        input.removeAttribute("aria-activedescendant");
      }
    }

    function update() {
      var query = normalize(input.value);
      if (!query) {
        current = suggestions.slice(0, 8);
      } else {
        current = suggestions
          .filter(function (item) {
            return normalize(item.label).indexOf(query) !== -1;
          })
          .sort(function (a, b) {
            var left = normalize(a.label).indexOf(query);
            var right = normalize(b.label).indexOf(query);
            return left - right || a.label.localeCompare(b.label, "fr");
          })
          .slice(0, 8);
      }
      activeIndex = -1;
      paint();
    }

    input.addEventListener("focus", update);
    input.addEventListener("input", update);

    input.addEventListener("keydown", function (event) {
      if (panel.hidden) {
        if (event.key === "ArrowDown") {
          update();
          event.preventDefault();
        }
        return;
      }
      if (event.key === "ArrowDown") {
        event.preventDefault();
        activeIndex = (activeIndex + 1) % current.length;
        paint();
      } else if (event.key === "ArrowUp") {
        event.preventDefault();
        activeIndex = activeIndex <= 0 ? current.length - 1 : activeIndex - 1;
        paint();
      } else if (event.key === "Enter" && activeIndex >= 0) {
        event.preventDefault();
        select(current[activeIndex]);
      } else if (event.key === "Escape") {
        close();
      }
    });

    input.addEventListener("blur", function () {
      window.setTimeout(close, 120);
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
