/* Actions mobiles : sort le bouton principal du menu « Actions ».
   Le bouton reste dans le formulaire d'origine grâce à l'attribut form. */
(function () {
  "use strict";

  var MOBILE = "(max-width: 768px)";
  var mql = window.matchMedia(MOBILE);
  var docks = [];
  var formCounter = 0;

  function isVisiblePrimary(node) {
    if (!node) return false;
    if (node.disabled) return false;
    if (node.hidden) return false;
    return true;
  }

  function buildPrimary(primary) {
    if (!isVisiblePrimary(primary)) return null;
    var tag = primary.tagName;

    if (tag === "A") {
      var link = primary.cloneNode(true);
      link.removeAttribute("id");
      return link;
    }

    if (tag === "BUTTON" && (primary.type === "submit" || !primary.type)) {
      var form = primary.closest("form");
      if (!form) return null;
      if (!form.id) {
        formCounter += 1;
        form.id = "m-dock-form-" + formCounter;
      }
      var button = primary.cloneNode(true);
      button.removeAttribute("id");
      button.setAttribute("form", form.id);
      return button;
    }

    return null;
  }

  function enhance(details) {
    if (details.dataset.mDock) return;
    var list = details.querySelector(".actions-list");
    if (!list) return;

    var primary = list.querySelector(".btn-primary");
    if (!primary) return;

    var node = buildPrimary(primary);
    if (!node) return;

    var actions = list.querySelectorAll(".btn");
    var single = actions.length <= 1;

    node.classList.add("m-dock-primary");
    if (single) node.classList.add("m-dock-primary--wide");
    node.removeAttribute("data-m-dock-primary");
    details.dataset.mDock = single ? "single" : "split";
    details.classList.add(single ? "m-dock-single" : "m-dock-split");
    document.body.appendChild(node);
    docks.push({ node: node, details: details });
  }

  function teardown() {
    docks.forEach(function (entry) {
      if (entry.node && entry.node.parentNode) entry.node.parentNode.removeChild(entry.node);
      if (entry.details) {
        entry.details.classList.remove("m-dock-split", "m-dock-single");
        delete entry.details.dataset.mDock;
      }
    });
    docks = [];
  }

  function bindFooterAgent() {
    Array.prototype.forEach.call(
      document.querySelectorAll("[data-agent-footer-open]"),
      function (button) {
        if (button.dataset.agentBound) return;
        button.dataset.agentBound = "1";
        button.addEventListener("click", function (event) {
          event.preventDefault();
          event.stopPropagation();
          var fab = document.querySelector("[data-agent-open]");
          if (fab) fab.click();
        });
      }
    );
  }

  function sync() {
    bindFooterAgent();
    teardown();
    if (!mql.matches) return;
    Array.prototype.forEach.call(
      document.querySelectorAll("details.page-actions"),
      enhance
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
