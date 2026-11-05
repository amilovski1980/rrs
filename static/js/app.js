(function () {
  "use strict";

  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function initVoiceDemo(reduceMotion) {
    var stage = document.querySelector("[data-voice-demo]");
    if (!stage) return;

    var messages = Array.prototype.slice.call(stage.querySelectorAll(".voice-msg"));
    var dotsWrap = stage.querySelector("[data-voice-dots]");
    var toggle = stage.querySelector("[data-voice-toggle]");
    var status = stage.querySelector("[data-voice-status]");
    var indexEl = stage.querySelector("[data-voice-index]");
    var playIcon = stage.querySelector('[data-voice-icon="play"]');
    var pauseIcon = stage.querySelector('[data-voice-icon="pause"]');
    var replay = document.querySelector("[data-voice-replay]");
    var current = 0;
    var playing = !reduceMotion;
    var timer = null;
    var inView = false;

    if (reduceMotion) {
      stage.classList.add("is-static");
      if (status) status.textContent = "Démo vocale";
      return;
    }

    messages.forEach(function (msg, i) {
      msg.classList.toggle("is-off", i !== 0);
    });

    var dots = messages.map(function (msg, i) {
      var dot = document.createElement("button");
      dot.type = "button";
      dot.setAttribute("aria-label", "Message " + (i + 1) + " sur " + messages.length);
      dot.addEventListener("click", function () {
        current = i;
        playing = false;
        paint();
        clearTimer();
      });
      if (dotsWrap) dotsWrap.appendChild(dot);
      return dot;
    });

    function clearTimer() {
      if (timer) {
        window.clearTimeout(timer);
        timer = null;
      }
    }

    function paint() {
      messages.forEach(function (msg, i) {
        msg.classList.toggle("is-off", i > current);
      });
      dots.forEach(function (dot, i) {
        dot.classList.toggle("is-on", i === current);
      });
      if (indexEl) indexEl.textContent = String(current + 1);
      var isAgent = current % 2 === 1;
      stage.classList.toggle("is-speaking", playing && isAgent);
      if (status) {
        status.textContent = !playing
          ? "Démo en pause"
          : isAgent
            ? "Aminia vous répond"
            : "L'artisan parle";
      }
      if (toggle) {
        toggle.setAttribute("aria-label", playing ? "Mettre la démo en pause" : "Lancer la démo");
        toggle.setAttribute("aria-pressed", playing ? "false" : "true");
      }
      if (playIcon) playIcon.hidden = playing;
      if (pauseIcon) pauseIcon.hidden = !playing;
    }

    function schedule() {
      clearTimer();
      if (!playing || !inView) return;
      var delay = current === messages.length - 1 ? 5200 : 2400;
      timer = window.setTimeout(function () {
        current = current === messages.length - 1 ? 0 : current + 1;
        paint();
        schedule();
      }, delay);
    }

    function setPlaying(next) {
      playing = next;
      paint();
      if (playing) schedule();
      else clearTimer();
    }

    if (toggle) {
      toggle.addEventListener("click", function () {
        setPlaying(!playing);
      });
    }

    if (replay) {
      replay.addEventListener("click", function () {
        current = 0;
        inView = true;
        setPlaying(true);
        if (window.matchMedia("(max-width: 1000px)").matches) {
          stage.scrollIntoView({ behavior: "smooth", block: "center" });
        }
      });
    }

    if ("IntersectionObserver" in window) {
      var observer = new IntersectionObserver(
        function (entries) {
          entries.forEach(function (entry) {
            inView = entry.isIntersecting;
            if (inView && playing) schedule();
            else if (!inView) clearTimer();
          });
        },
        { threshold: 0.25 }
      );
      observer.observe(stage);
    } else {
      inView = true;
    }

    paint();
  }

  function initSirenSearch() {
    var form = document.querySelector("[data-siren-search]");
    if (!form) return;

    var input = form.querySelector('input[name="siren"]');
    var result = document.querySelector("[data-siren-result]");
    var button = form.querySelector('button[type="submit"]');
    if (!input || !result || !button) return;

    var controller = null;
    var requestId = 0;

    var digits = function (value) {
      return String(value || "").replace(/\D/g, "").slice(0, 9);
    };

    var validSiren = function (siren) {
      if (!/^\d{9}$/.test(siren)) return false;
      var sum = 0;
      for (var i = 0; i < siren.length; i++) {
        var digit = parseInt(siren.charAt(i), 10);
        if (i % 2 === 1) {
          digit *= 2;
          if (digit > 9) digit -= 9;
        }
        sum += digit;
      }
      return sum % 10 === 0;
    };

    var formatSiren = function (siren) {
      return siren.replace(/^(\d{3})(\d{3})(\d{3})$/, "$1 $2 $3");
    };

    var escapeHtml = function (value) {
      return String(value == null ? "" : value).replace(/[&<>"']/g, function (ch) {
        return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch];
      });
    };

    var show = function (html) {
      result.innerHTML = html;
      result.hidden = false;
    };

    var showError = function (message) {
      show('<p class="siren-error">' + escapeHtml(message) + "</p>");
    };

    var render = function (item) {
      var siege = item.siege || {};
      var address = siege.adresse || [siege.code_postal, siege.libelle_commune].filter(Boolean).join(" ");
      var activity = item.activite_principale ? "Activité " + item.activite_principale : "";
      var created = item.date_creation ? "Créée en " + item.date_creation.slice(0, 4) : "";
      var meta = [activity, created].filter(Boolean).join(" · ");
      var name = item.nom_complet || "SIREN " + formatSiren(item.siren);
      var subject = "Ouverture cockpit — " + name;
      var body = "Bonjour,\n\nJe souhaite ouvrir mon cockpit Road Runner Solutions.\n\n" +
        "Activité : " + name + "\n" +
        "SIREN : " + formatSiren(item.siren) + "\n" +
        (address ? "Adresse : " + address + "\n" : "") +
        "\nMerci.";
      var mailto = "mailto:contact@roadrunner-solutions.fr?subject=" +
        encodeURIComponent(subject) + "&body=" + encodeURIComponent(body);

      show(
        '<div class="siren-card">' +
          "<div>" +
            '<span class="siren-kicker">SIREN ' + escapeHtml(formatSiren(item.siren)) + "</span>" +
            "<strong>" + escapeHtml(name) + "</strong>" +
            (address ? '<span class="siren-meta">' + escapeHtml(address) + "</span>" : "") +
            (meta ? '<span class="siren-meta">' + escapeHtml(meta) + "</span>" : "") +
          "</div>" +
          '<a class="btn btn-primary" href="compte/demo/?next=' + encodeURIComponent("/cockpit/?siren=" + (item.siren || "")) + '">Ouvrir mon cockpit</a>' +
        "</div>"
      );
    };

    var search = function () {
      var siren = digits(input.value);
      input.value = siren;

      if (siren.length !== 9) {
        showError("Le SIREN doit contenir exactement 9 chiffres.");
        input.focus();
        return;
      }

      if (!validSiren(siren)) {
        showError("Ce SIREN n'est pas valide. Vérifiez les 9 chiffres.");
        input.focus();
        return;
      }

      if (controller) controller.abort();
      controller = new AbortController();
      var currentId = ++requestId;
      button.disabled = true;
      show('<p class="siren-loading">Recherche dans la base Sirene…</p>');

      fetch("https://recherche-entreprises.api.gouv.fr/search?q=" + encodeURIComponent(siren) + "&page=1&per_page=1", {
        signal: controller.signal,
        headers: { Accept: "application/json" }
      })
        .then(function (response) {
          if (!response.ok) throw new Error("HTTP " + response.status);
          return response.json();
        })
        .then(function (data) {
          var item = (data.results || []).filter(function (row) {
            return row.siren === siren;
          })[0];

          if (!item) {
            showError("Aucune activité trouvée pour ce SIREN. Vérifiez les 9 chiffres.");
            return;
          }
          render(item);
        })
        .catch(function (error) {
          if (error.name === "AbortError") return;
          showError("Recherche indisponible pour le moment. Réessayez dans un instant.");
        })
        .finally(function () {
          if (currentId === requestId) button.disabled = false;
        });
    };

    input.addEventListener("input", function () {
      input.value = digits(input.value);
    });

    form.addEventListener("submit", function (event) {
      event.preventDefault();
      search();
    });

    var params = new URLSearchParams(window.location.search);
    var initial = digits(params.get("siren") || "");
    if (initial.length === 9) {
      input.value = initial;
      search();
    }
  }

  function initActivityDemo() {
    var select = document.querySelector("[data-activity-select]");
    if (!select) return;

    var activities = {
      btp: {
        company: "BTP Martin — SARL",
        regime: "Réel simplifié",
        ca: "128 400 €",
        encaisse: "18 200 €",
        tva: "9 640 €",
        delta: "+18,2 %",
        encaisseMeta: "4 factures",
        tvaMeta: "CA3 · janv.",
        bar: "72%",
        floatTva: "9 640 € · CA3 janvier",
        floatExpense: "Achat béton · 2 480 €",
        items: ["Facture FAC-2026-00087 · Gros œuvre", "Achat béton · 2 480 €", "Attestation TVA · à jour"],
        note: "Plan comptable BTP : achats 601, outillage 6063, entretien 615. TVA CA3 mensuelle."
      },
      plomberie: {
        company: "Plomberie Bernard — SARL",
        regime: "Réel simplifié",
        ca: "86 200 €",
        encaisse: "7 450 €",
        tva: "4 310 €",
        delta: "+9,6 %",
        encaisseMeta: "2 factures",
        tvaMeta: "CA3 · janv.",
        bar: "58%",
        floatTva: "4 310 € · CA3 janvier",
        floatExpense: "Achat tuyauterie · 1 180 €",
        items: ["Facture FAC-2026-00054 · Salle de bain", "Achat tuyauterie · 1 180 €", "Extrait RNE · KBIS"],
        note: "Plan comptable plomberie : achats 601, outillage 6063, entretien 615. TVA CA3."
      },
      electricite: {
        company: "Élec Durand — SARL",
        regime: "Réel simplifié",
        ca: "94 800 €",
        encaisse: "12 600 €",
        tva: "5 740 €",
        delta: "+11,3 %",
        encaisseMeta: "3 factures",
        tvaMeta: "CA3 · janv.",
        bar: "64%",
        floatTva: "5 740 € · CA3 janvier",
        floatExpense: "Achat câbles · 1 640 €",
        items: ["Facture FAC-2026-00061 · Tableau", "Achat câbles · 1 640 €", "Attestation TVA · à jour"],
        note: "Plan comptable électricité : achats 601, outillage 6063, entretien 615. TVA CA3."
      },
      menuiserie: {
        company: "Menuiserie Dupont — SARL",
        regime: "Réel simplifié",
        ca: "48 250 €",
        encaisse: "7 320 €",
        tva: "2 145 €",
        delta: "+12,4 %",
        encaisseMeta: "3 factures",
        tvaMeta: "CA12 · janv.",
        bar: "64%",
        floatTva: "2 145 € · CA12 janvier",
        floatExpense: "Achat outillage · 1 240 €",
        items: ["Facture FAC-2026-00042 · Cadres", "Écriture · Achat outillage", "Extrait RNE · KBIS"],
        note: "Plan comptable menuiserie : achats 601, outillage 6063, entretien 615. TVA CA12."
      },
      coiffure: {
        company: "Salon Léa — SARL",
        regime: "Micro",
        ca: "32 600 €",
        encaisse: "1 240 €",
        tva: "1 630 €",
        delta: "+6,1 %",
        encaisseMeta: "1 facture",
        tvaMeta: "CA12 · janv.",
        bar: "45%",
        floatTva: "1 630 € · CA12 janvier",
        floatExpense: "Achat produits · 420 €",
        items: ["Facture FAC-2026-00023 · Prestations", "Achat produits · 420 €", "Déclaration TVA · CA12"],
        note: "Plan comptable coiffure : achats 606, produits 607, entretien 615. TVA CA12."
      },
      restauration: {
        company: "Restaurant Chez Paul — SARL",
        regime: "Réel simplifié",
        ca: "156 900 €",
        encaisse: "4 800 €",
        tva: "7 845 €",
        delta: "+14,7 %",
        encaisseMeta: "2 factures",
        tvaMeta: "CA3 · janv.",
        bar: "81%",
        floatTva: "7 845 € · CA3 janvier",
        floatExpense: "Achat denrées · 2 310 €",
        items: ["Facture FAC-2026-00112 · Traiteur", "Achat denrées · 2 310 €", "Déclaration TVA · CA3"],
        note: "Plan comptable restauration : denrées 601, petit équipement 6063, entretien 615. TVA CA3."
      }
    };

    var setText = function (selector, value) {
      var node = document.querySelector(selector);
      if (node && value != null) node.textContent = value;
    };

    var update = function () {
      var data = activities[select.value];
      if (!data) return;

      setText("[data-demo-company]", data.company);
      setText("[data-demo-regime]", data.regime);
      setText('[data-demo-kpi="ca"]', data.ca);
      setText('[data-demo-kpi="encaisse"]', data.encaisse);
      setText('[data-demo-kpi="tva"]', data.tva);
      setText('[data-demo-delta="ca"]', data.delta);
      setText('[data-demo-meta="encaisse"]', data.encaisseMeta);
      setText('[data-demo-meta="tva"]', data.tvaMeta);
      setText("[data-demo-float-tva]", data.floatTva);
      setText("[data-demo-float-expense]", data.floatExpense);

      var items = document.querySelectorAll("[data-demo-item]");
      for (var i = 0; i < items.length; i++) {
        if (data.items[i]) items[i].textContent = data.items[i];
      }

      var note = document.querySelector("[data-activity-note]");
      if (note) note.textContent = data.note;

      var bar = document.querySelector("[data-demo-bar]");
      if (bar) bar.style.width = data.bar;
    };

    select.addEventListener("change", update);
    update();
  }

  function initAgent() {
    var root = document.querySelector("[data-agent]");
    if (!root) return;

    var openBtn = root.querySelector("[data-agent-open]");
    var panel = root.querySelector("[data-agent-panel]");
    var dialog = root.querySelector(".agent-dialog");
    var mic = root.querySelector("[data-agent-mic]");
    var status = root.querySelector("[data-agent-status]");
    var chooser = root.querySelector("[data-agent-chooser]");
    var chat = root.querySelector("[data-agent-chat]");
    if (!openBtn) return;

    var closeButtons = root.querySelectorAll("[data-agent-close]");
    var lastFocus = null;
    var timers = [];
    var listening = false;

    var clearTimers = function () {
      for (var i = 0; i < timers.length; i++) window.clearTimeout(timers[i]);
      timers = [];
    };

    var setStatus = function (message) {
      if (status) status.textContent = message;
    };

    var setState = function (state) {
      if (!dialog) return;
      dialog.classList.remove("is-listening", "is-thinking", "is-done");
      if (state) dialog.classList.add(state);
      if (mic) mic.classList.toggle("is-listening", state === "is-listening");
    };

    var reset = function () {
      clearTimers();
      listening = false;
      setState("");
      setStatus("Appuyez pour parler");
    };

    var closeChooser = function () {
      if (chooser) chooser.hidden = true;
    };

    var openChooser = function () {
      lastFocus = document.activeElement;
      if (panel) panel.hidden = true;
      if (chat) chat.hidden = true;
      if (chooser) {
        chooser.hidden = false;
        openBtn.setAttribute("aria-expanded", "true");
        openBtn.setAttribute("aria-controls", "agent-chooser");
        var first = chooser.querySelector("[data-agent-pick]");
        window.setTimeout(function () { if (first) first.focus(); }, 30);
      }
    };

    var openVoice = function () {
      closeChooser();
      if (!panel || !dialog) {
        document.dispatchEvent(new CustomEvent("aminia:open-voice"));
        return;
      }
      lastFocus = document.activeElement;
      panel.hidden = false;
      openBtn.setAttribute("aria-expanded", "true");
      openBtn.setAttribute("aria-controls", "agent-panel");
      document.body.classList.add("agent-open");
      reset();
      window.setTimeout(function () {
        if (mic) mic.focus();
      }, 30);
      document.dispatchEvent(new CustomEvent("aminia:open-voice"));
    };

    var closeVoice = function () {
      clearTimers();
      if (panel) panel.hidden = true;
      openBtn.setAttribute("aria-expanded", "false");
      document.body.classList.remove("agent-open");
      setState("");
      if (lastFocus && typeof lastFocus.focus === "function") lastFocus.focus();
      else openBtn.focus();
    };

    var openChat = function () {
      closeChooser();
      if (!chat) return;
      lastFocus = document.activeElement;
      if (panel) panel.hidden = true;
      chat.hidden = false;
      openBtn.setAttribute("aria-expanded", "true");
      openBtn.setAttribute("aria-controls", "agent-chat");
      document.body.classList.add("agent-open");
      var input = chat.querySelector("[data-agent-chat-input]");
      window.setTimeout(function () { if (input) input.focus(); }, 30);
    };

    var closeChat = function () {
      if (chat) chat.hidden = true;
      openBtn.setAttribute("aria-expanded", "false");
      document.body.classList.remove("agent-open");
      if (lastFocus && typeof lastFocus.focus === "function") lastFocus.focus();
      else openBtn.focus();
    };

    var preview = function () {
      if (listening) return;
      listening = true;
      setState("is-listening");
      setStatus("Je vous écoute…");

      timers.push(window.setTimeout(function () {
        setStatus("« Combien de TVA sur cette facture ? »");
      }, 1300));
      timers.push(window.setTimeout(function () {
        setState("is-thinking");
        setStatus("Aminia prépare la réponse…");
      }, 2400));
      timers.push(window.setTimeout(function () {
        setState("is-done");
        setStatus("Aperçu : la réponse vocale arrive bientôt.");
        listening = false;
      }, 3700));
      timers.push(window.setTimeout(reset, 7200));
    };

    openBtn.addEventListener("click", function (event) {
      event.preventDefault();
      if (chooser && chooser.hidden === false) {
        closeChooser();
        openBtn.setAttribute("aria-expanded", "false");
        return;
      }
      if (panel && panel.hidden === false) {
        closeVoice();
        return;
      }
      if (chat && chat.hidden === false) {
        closeChat();
        return;
      }
      openChooser();
    });

    if (chooser) {
      var picks = chooser.querySelectorAll("[data-agent-pick]");
      for (var pi = 0; pi < picks.length; pi++) {
        picks[pi].addEventListener("click", function (ev) {
          var mode = ev.currentTarget.getAttribute("data-agent-pick");
          if (mode === "voice") openVoice();
          else if (mode === "chat") openChat();
        });
      }
      var chooserClose = chooser.querySelector("[data-agent-chooser-close]");
      if (chooserClose) {
        chooserClose.addEventListener("click", function () {
          closeChooser();
          openBtn.setAttribute("aria-expanded", "false");
        });
      }
    }

    for (var i = 0; i < closeButtons.length; i++) {
      closeButtons[i].addEventListener("click", closeVoice);
    }
    var chatClose = root.querySelector("[data-agent-chat-close]");
    if (chatClose) chatClose.addEventListener("click", closeChat);

    if (mic) mic.addEventListener("click", function () {
      if (window.SIP && window.SIP.SimpleUser) {
        var evt;
        try { evt = new CustomEvent("aminia:open-call"); } catch (e) { return; }
        document.dispatchEvent(evt);
        return;
      }
      preview();
    });

    document.addEventListener("keydown", function (event) {
      if (event.key !== "Escape") return;
      if (chooser && !chooser.hidden) {
        closeChooser();
        openBtn.setAttribute("aria-expanded", "false");
        return;
      }
      if (chat && !chat.hidden) {
        closeChat();
        return;
      }
      if (panel && !panel.hidden) closeVoice();
    });
  }

  function csrfTokenFrom(root) {
    var input = (root && root.querySelector("input[name=csrfmiddlewaretoken]"))
      || document.querySelector("[data-agent] input[name=csrfmiddlewaretoken]")
      || document.querySelector("input[name=csrfmiddlewaretoken]");
    return input ? input.value : "";
  }

  function appendChatBubble(log, role, text) {
    if (!log) return;
    var empty = log.querySelector(".agent-chat-empty");
    if (empty) empty.remove();
    var bubble = document.createElement("div");
    bubble.className = "agent-chat-bubble agent-chat-bubble--" + role;
    var p = document.createElement("p");
    p.textContent = text;
    bubble.appendChild(p);
    log.appendChild(bubble);
    log.scrollTop = log.scrollHeight;
  }

  function wireChatForm(container) {
    if (!container || container.getAttribute("data-chat-wired") === "1") return;
    var form = container.querySelector("[data-agent-chat-form]");
    var input = container.querySelector("[data-agent-chat-input]");
    var log = container.querySelector("[data-agent-chat-log]");
    var err = container.querySelector("[data-agent-chat-error]");
    var sendBtn = container.querySelector("[data-agent-chat-send]");
    if (!form || !input || !log) return;
    container.setAttribute("data-chat-wired", "1");
    var conversationId = container.getAttribute("data-conversation-id") || "";

    form.addEventListener("submit", function (event) {
      event.preventDefault();
      var text = (input.value || "").trim();
      if (!text) return;
      if (err) { err.hidden = true; err.textContent = ""; }
      appendChatBubble(log, "user", text);
      input.value = "";
      input.disabled = true;
      if (sendBtn) sendBtn.disabled = true;
      appendChatBubble(log, "assistant", "…");
      var pending = log.lastElementChild;

      fetch("/agent/chat/message/", {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": csrfTokenFrom(container)
        },
        body: JSON.stringify({
          message: text,
          conversation_id: conversationId || undefined
        })
      }).then(function (res) {
        return res.json().then(function (data) {
          return { ok: res.ok, status: res.status, data: data };
        });
      }).then(function (payload) {
        var data = payload.data || {};
        if (data.conversation_id) {
          conversationId = data.conversation_id;
          container.setAttribute("data-conversation-id", conversationId);
        }
        var reply = data.reply || data.error || "Réponse indisponible.";
        if (!payload.ok || data.ok === false) {
          reply = data.error || reply;
          if (err) {
            err.hidden = false;
            err.textContent = reply;
          }
        }
        if (pending) {
          var pp = pending.querySelector("p");
          if (pp) pp.textContent = reply;
        } else {
          appendChatBubble(log, "assistant", reply);
        }
      }).catch(function () {
        var msg = "Impossible de joindre Aminia. Réessayez.";
        if (pending) {
          var pp = pending.querySelector("p");
          if (pp) pp.textContent = msg;
        }
        if (err) { err.hidden = false; err.textContent = msg; }
      }).finally(function () {
        input.disabled = false;
        if (sendBtn) sendBtn.disabled = false;
        input.focus();
      });
    });
  }

  function initAgentChat() {
    var floating = document.querySelector("[data-agent-chat]");
    if (floating) wireChatForm(floating);
    var page = document.querySelector("[data-agent-chat-page]");
    if (page) wireChatForm(page);
  }

  function initPhone() {
    var root = document.querySelector("[data-agent]");
    if (!root) return;

    var panel = root.querySelector("[data-agent-panel]");
    var callBtn = root.querySelector("[data-phone-call]");
    if (!panel || !callBtn) return;

    var phone = root.querySelector("[data-phone]");
    var phoneStatus = root.querySelector("[data-phone-status]");
    var phoneTimer = root.querySelector("[data-phone-timer]");
    var muteBtn = root.querySelector("[data-phone-mute]");
    var hangupBtn = root.querySelector("[data-phone-hangup]");
    var keys = root.querySelectorAll("[data-phone-keys] .phone-key");
    var phoneBox = phone;

    var cfg = null;
    var sipLib = null;
    var simple = null;
    var muted = 0;
    var timerId = null;
    var callStart = null;
    var busy = 0;

    var speak = function (text) {
      try {
        if (!("speechSynthesis" in window)) return;
        var u = window.speechSynthesis ? new SpeechSynthesisUtterance(text) : null;
        if (!u) return;
        u.lang = "fr-FR";
        u.rate = 1.02;
        window.speechSynthesis.cancel();
        window.speechSynthesis.speak(u);
      } catch (e) { /* TTS indisponible : le texte reste affiché */ }
    };

    var setStatus = function (message) {
      if (phoneStatus) phoneStatus.textContent = message;
    };

    var stopTimer = function () {
      if (timerId) { window.clearInterval(timerId); timerId = null; }
      if (phoneTimer) phoneTimer.hidden = true;
      callStart = null;
    };

    var startTimer = function () {
      callStart = Date.now();
      if (phoneTimer) phoneTimer.hidden = false;
      timerId = window.setInterval(function () {
        if (callStart === null) return;
        var s = Math.floor((Date.now() - callStart) / 1000);
        var mm = (s / 60 | 0) < 10 ? "0" + (s / 60 | 0) : "" + (s / 60 | 0);
        var ss = (s % 60) < 10 ? "0" + (s % 60) : "" + (s % 60);
        if (phoneTimer) phoneTimer.textContent = mm + ":" + ss;
      }, 500);
    };

    var resetPhone = function (message) {
      stopTimer();
      simple = null;
      muted = 0;
      busy = 0;
      if (phoneBox) phoneBox.classList.remove("is-live");
      if (muteBtn) muteBtn.textContent = "Muet";
      callBtn.hidden = false;
      if (phone) phone.hidden = false;
      setStatus(message || "Appel terminé");
    };

    var loadSip = function (done) {
      if (window.SIP) { done(); return; }
      import("https://cdn.jsdelivr.net/npm/sip.js@0.21.2/lib/platform/web/index.js")
        .then(function (mod) {
          window.SIP = mod;
          done();
        })
        .catch(function () { done(null); });
    };

    var fetchConfig = function (done) {
      if (cfg) { done(cfg); return; }
      fetch("/agent-config", { headers: { Accept: "application/json" } })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (data) { cfg = data && data.sip ? data : null; done(cfg); })
        .catch(function () { cfg = null; done(null); });
    };

    var demoGuide = function () {
      var steps = [
        "Mode démo : je vous guide par la voix.",
        "Le tableau de bord est à gauche. Vos écritures sont dans le grand livre.",
        "Pour la TVA, ouvrez la balance, puis la période à déclarer.",
        "Sur le cockpit réel, je resterai à vos côtés pendant les appels."
      ];
      for (var i = 0; i < steps.length; i++) {
        (function (t, delay) {
          window.setTimeout(function () { setStatus(t); speak(t); }, delay);
        })(steps[i], i * 3600);
      }
      window.setTimeout(function () {
        resetPhone("Fin du guidage vocal");
      }, (steps.length + 1) * 3600);
    };

    var startCall = function () {
      if (busy) return;
      busy = 1;
      callBtn.hidden = true;
      if (phone) phone.hidden = false;
      if (phoneTimer) phoneTimer.hidden = true;
      setStatus("Connexion au standard…");
      speak("Je vous connecte au standard Aminia, poste 9999. Veuillez patienter.");

      fetchConfig(function (config) {
        if (!config) {
          setStatus("Standard indisponible ici — guidage vocal en mode démo.");
          busy = 0;
          demoGuide();
          return;
        }
        loadSip(function () {
          sipLib = sipLib || window.SIP || null;
          if (!sipLib) {
            setStatus("Bibliothèque SIP chargée impossible — guidage vocal en mode démo.");
            busy = 0;
            demoGuide();
            return;
          }
          var sip = config.sip;
          var SavedWebSocket = window.WebSocket;
          if (!window.__sipWebSocketPatched) {
            window.__sipWebSocketPatched = true;
            window.WebSocket = function (url, protocols) {
              return new SavedWebSocket(url, protocols || "sip");
            };
          }
          var sipHostEl = root.querySelector("[data-sip-host]");
          var sipExtEl = root.querySelector("[data-sip-ext]");
          var sipCalleeEl = root.querySelector("[data-sip-callee]");
          var host = (sipHostEl && sipHostEl.value) || sip.host;
          var wssList = sip.wss || [];
          var portInput = root.querySelector("[data-phone-ws-port]");
          var port = portInput ? parseInt(portInput.value, 10) : 0;
          var ext = (sipExtEl && sipExtEl.value) || sip.user;
          var callee = (sipCalleeEl && sipCalleeEl.value) || sip.callee;
          if (port > 0) {
            var first = wssList[0] || ("wss://" + sip.host + ":443" + (sip.wssPath || "/ws"));
            var slash = first.indexOf("/", "wss://".length);
            var path = slash === -1 ? "/ws" : first.slice(slash);
            wssList = [
              "wss://" + sip.host + ":" + port + path,
              wssList[1] || ("wss://" + sip.host + ":443" + (sip.wssPath || "/ws"))
            ];
          }
          var tryWss = function (i) {
            if (i >= wssList.length) {
              setStatus("Le standard SIP n'a pas répondu — guidage vocal en mode démo.");
              busy = 0;
              demoGuide();
              return;
            }
            try {
              simple = new sipLib.SimpleUser(wssList[i], {
                aor: "sip:" + ext + "@" + host,
                transportOptions: { server: wssList[i], traceSip: false, wsProtocol: "sip" },
                userAgentConfiguration: {
                  authorizationUsername: sip.user,
                  authorizationPassword: sip.password
                },
                displayName: "Aminia — Road Runner",
                media: { constraints: { audio: true, video: false } }
              });
            } catch (err) {
              tryWss(i + 1);
              return;
            }
            var connected = 0;
            simple.delegate = {
              onCallCreated: function () {
                setStatus("Appel vers le poste " + sip.callee + " en cours…");
              },
              onCallReceived: function () { /* entrant : non accepté en démo */ },
              onCallProgress: function () { setStatus("Sonnerie au poste " + sip.callee + "…"); },
              onCallEstablished: function () {
                connected = 1;
                if (phoneBox) phoneBox.classList.add("is-live");
                setStatus("En ligne — Aminia vous guide par la voix.");
                startTimer();
                speak("Vous êtes en ligne. Je reste avec vous durant l'appel. Dites raccrocher quand vous voulez terminer.");
              },
              onCallHangup: function () {
                speak("Appel terminé. À bientôt !");
                resetPhone("Appel terminé");
              },
              onRegistered: function () {
                setStatus("SIP enregistrǸ " + " " + "l'appel du poste " + callee + "�?�");
                simple.call("sip:" + callee + "@" + host, {}).catch(function () {
                  tryWss(i + 1);
                });
              },
              onRegisterFailed: function () {
                if (!connected) { tryWss(i + 1); }
              },
              onUnregistered: function () { /* fin de session */ }
            };
            var watch = window.setInterval(function () {
              var session = simple && simple.session ? simple.session : null;
              if (session && session.state === "Established" && !connected) {
                connected = 1;
                if (phoneBox) phoneBox.classList.add("is-live");
                setStatus("En ligne — Aminia vous guide par la voix.");
                startTimer();
                speak("Vous êtes en ligne. Je reste avec vous durant l'appel.");
              }
              if (session && session.state === "Terminated") {
                window.clearInterval(watch);
                resetPhone(connected ? "Appel terminé" : "Le standard n'a pas décroché");
              }
            }, 700);
            var go = (simple.connect ? simple.connect() : Promise.resolve())
              .then(function () {
                return simple.register ? simple.register() : null;
              })
              .catch(function () { tryWss(i + 1); });
          };
          tryWss(0);
        });
      });
    };

    var hangUp = function () {
      if (simple) {
        try { simple.hangup(); } catch (e) { /* déjà raccroché */ }
        try { simple.stop ? simple.stop() : null; } catch (e) { }
      }
      resetPhone("Appel terminé");
    };

    var toggleMute = function () {
      if (!simple) return;
      muted = muted ? 0 : 1;
      try {
        if (muted) simple.mute ? simple.mute() : null;
        else simple.unmute ? simple.unmute() : null;
      } catch (e) { /* fonctionnalités selon la session */ }
      if (muteBtn) muteBtn.textContent = muted ? "Réactiver" : "Muet";
      setStatus(muted ? "Micro coupé" : "Micro actif");
    };

    for (var k = 0; k < keys.length; k++) {
      (function (key) {
        key.addEventListener("click", function () {
          if (simple && simple.session) {
            try { simple.sendDTMF ? simple.sendDTMF(key.getAttribute("data-key")) : null; } catch (e) { }
          }
          setStatus("Touche " + key.getAttribute("data-key"));
        });
      })(keys[k]);
    }

    callBtn.addEventListener("click", startCall);
    if (muteBtn) muteBtn.addEventListener("click", toggleMute);
    if (hangupBtn) hangupBtn.addEventListener("click", hangUp);

    document.addEventListener("aminia:open-call", function () { startCall(); });

    if (window.MutationObserver) {
      new MutationObserver(function () {
        if (panel.hidden) {
          stopTimer();
          if (simple) {
            try { simple.stop ? simple.stop() : null; } catch (e) { }
          }
          try { window.speechSynthesis ? window.speechSynthesis.cancel() : null; } catch (e) { }
          resetPhone("Prêt à appeler");
          if (phone) phone.hidden = true;
        }
      }).observe(panel, { attributes: true, attributeFilter: ["hidden"] });
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    var nav = document.querySelector(".nav");
    if (nav) {
      var onScroll = function () {
        nav.classList.toggle("is-scrolled", window.scrollY > 8);
      };
      window.addEventListener("scroll", onScroll, { passive: true });
      onScroll();
    }

    initVoiceDemo(reduceMotion);
    initSirenSearch();
    initActivityDemo();
    initAgent();
    initAgentChat();
    initPhone();

    if (reduceMotion) return;

    var targets = document.querySelectorAll(
      ".trust .container, section .sec-head, .voice-copy, .voice-stage, .feature, .plan, " +
      ".quick-card, .cta-band, .card, .kpi, .company, .page-head, .auth-card"
    );

    if ("IntersectionObserver" in window && targets.length) {
      var observer = new IntersectionObserver(
        function (entries) {
          entries.forEach(function (entry) {
            if (!entry.isIntersecting) return;
            entry.target.classList.add("is-visible");
            observer.unobserve(entry.target);
          });
        },
        { threshold: 0.12, rootMargin: "0px 0px -40px 0px" }
      );

      targets.forEach(function (el, index) {
        if (el.classList.contains("auth-card")) return;
        el.classList.add("reveal");
        el.style.transitionDelay = (index % 6) * 45 + "ms";
        observer.observe(el);
      });
    }

    var counters = document.querySelectorAll("[data-count]");
    if (!counters.length) return;

    var format = function (value) {
      return new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 0 }).format(value);
    };

    var animate = function (el) {
      var target = parseFloat(el.getAttribute("data-count")) || 0;
      var suffix = el.getAttribute("data-suffix") || "";
      var prefix = el.getAttribute("data-prefix") || "";
      var duration = 1100;
      var start = null;

      var step = function (timestamp) {
        if (start === null) start = timestamp;
        var progress = Math.min((timestamp - start) / duration, 1);
        var eased = 1 - Math.pow(1 - progress, 3);
        el.textContent = prefix + format(Math.round(target * eased)) + suffix;
        if (progress < 1) requestAnimationFrame(step);
      };
      requestAnimationFrame(step);
    };

    var counterObserver = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          if (!entry.isIntersecting) return;
          animate(entry.target);
          counterObserver.unobserve(entry.target);
        });
      },
      { threshold: 0.5 }
    );

    counters.forEach(function (el) {
      counterObserver.observe(el);
    });
  });
})();
