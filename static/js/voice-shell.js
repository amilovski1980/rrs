/* Coque vocale : conserve Aminia pendant la navigation interne dans un iframe. */
(function () {
  "use strict";

  var state = { iframe: null, active: false, entering: false };

  function shellDocument() {
    if (!state.iframe) return document;
    try {
      return state.iframe.contentDocument || document;
    } catch (error) {
      return document;
    }
  }

  function currentUrl() {
    if (!state.iframe) return "";
    try {
      var location = state.iframe.contentWindow.location;
      return location.pathname + location.search + location.hash;
    } catch (error) {
      return "";
    }
  }

  function syncAddress() {
    var url = currentUrl();
    if (!url) return;
    if (url !== window.location.pathname + window.location.search + window.location.hash) {
      try {
        window.history.replaceState({ aminiaShell: true }, "", url);
      } catch (error) {
        /* URL non partageable : on garde l'adresse du shell. */
      }
    }
  }

  function decorateFrame() {
    if (!state.iframe) return;
    var doc = shellDocument();
    if (!doc || !doc.head) return;
    if (doc.getElementById("aminia-shell-style")) return;
    var style = doc.createElement("style");
    style.id = "aminia-shell-style";
    style.textContent =
      ".agent{display:none!important}" +
      "html,body{overscroll-behavior:contain}";
    doc.head.appendChild(style);
    syncAddress();
    try {
      var frameWindow = state.iframe.contentWindow;
      var companyId =
        new URLSearchParams(frameWindow.location.search).get("societe") || "";
      window.dispatchEvent(
        new CustomEvent("aminia:shell-url", {
          detail: {
            url: frameWindow.location.pathname + frameWindow.location.search,
            companyId: companyId,
          },
        })
      );
    } catch (error) {
      /* navigation inter-document : simple repli */
    }
  }

  function enter(url) {
    if (state.active || state.entering) return;
    state.entering = true;
    var frame = document.createElement("iframe");
    frame.className = "voice-shell-frame";
    frame.name = "aminia-voice-shell";
    frame.title = "Application RRS Sandy";
    frame.setAttribute(
      "allow",
      "microphone; autoplay; clipboard-read; clipboard-write; screen-wake-lock"
    );
    frame.src = url || window.location.href;
    frame.addEventListener("load", function () {
      decorateFrame();
      state.entering = false;
    });
    document.body.appendChild(frame);
    document.body.classList.add("voice-shell-active");
    state.iframe = frame;
    state.active = true;
  }

  function navigate(url) {
    if (!state.iframe) {
      enter(url);
      return;
    }
    if (url) state.iframe.src = url;
  }

  function exit() {
    var url = currentUrl();
    if (state.iframe) state.iframe.remove();
    state.iframe = null;
    state.active = false;
    state.entering = false;
    document.body.classList.remove("voice-shell-active");
    if (url) window.location.href = url;
  }

  function shouldHandleLink(link) {
    if (!link || link.target || link.hasAttribute("download")) return false;
    if (link.dataset.voiceIgnore !== undefined) return false;
    var href = link.getAttribute("href") || "";
    if (!href || href.charAt(0) === "#") return false;
    if (/^(mailto:|tel:|javascript:)/i.test(href)) return false;
    var url;
    try {
      url = new URL(link.href, window.location.href);
    } catch (error) {
      return false;
    }
    if (url.origin !== window.location.origin) return false;
    if (url.pathname.indexOf("/static/") === 0) return false;
    if (url.pathname.indexOf("/compte/logout") === 0) return false;
    return true;
  }

  document.addEventListener(
    "click",
    function (event) {
      if (!state.active) return;
      var link = event.target.closest && event.target.closest("a[href]");
      if (!shouldHandleLink(link)) return;
      event.preventDefault();
      enter(link.href);
    },
    true
  );

  document.addEventListener(
    "submit",
    function (event) {
      if (!state.active) return;
      var form = event.target;
      if (!form || form.tagName !== "FORM") return;
      if (form.target === "aminia-voice-shell") return;
      if (form.dataset.voiceIgnore !== undefined) return;
      if (!state.iframe) enter("about:blank");
      form.target = "aminia-voice-shell";
    },
    true
  );

  window.addEventListener("popstate", function () {
    if (!state.active) return;
    var url = window.location.pathname + window.location.search + window.location.hash;
    if (url && state.iframe) state.iframe.src = url;
  });

  window.AminiaShell = {
    enter: enter,
    navigate: navigate,
    exit: exit,
    document: shellDocument,
    get active() {
      return state.active;
    },
  };
})();
