/* Assistant vocal Grok : jeton éphémère côté serveur, audio PCM 24 kHz. */
(function () {
  var SAMPLE_RATE = 24000;
  var WAKE_KEY = "aminia:screen-wake:v2";
  var wakeLock = null;
  var wakeTimer = null;
  var wakeEnabled = true;
  try {
    wakeEnabled = window.localStorage.getItem(WAKE_KEY) !== "0";
  } catch (error) {
    wakeEnabled = true;
  }

  function csrfToken() {
    var input = document.querySelector("[data-agent] input[name=csrfmiddlewaretoken]");
    if (input && input.value) return input.value;
    var match = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : "";
  }

  function postJson(url, body) {
    return fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
        "X-CSRFToken": csrfToken()
      },
      body: JSON.stringify(body || {})
    }).then(function (response) {
      return response.json().catch(function () { return {}; }).then(function (data) {
        data._status = response.status;
        return data;
      });
    });
  }

  function companyIdFromPage() {
    if (window.AminiaShell && window.AminiaShell.active) {
      try {
        var frameWindow = window.AminiaShell.document().defaultView;
        if (frameWindow) {
          return new URLSearchParams(frameWindow.location.search).get("societe") || "";
        }
      } catch (error) {
        /* repli sur la page hôte */
      }
    }
    var params = new URLSearchParams(window.location.search);
    return params.get("societe") || "";
  }

  function activeDocument() {
    if (window.AminiaShell && window.AminiaShell.active) {
      try {
        return window.AminiaShell.document();
      } catch (error) {
        return document;
      }
    }
    return document;
  }

  function resample(input, fromRate, toRate) {
    if (fromRate === toRate) return input;
    var ratio = fromRate / toRate;
    var length = Math.floor(input.length / ratio);
    var out = new Float32Array(length);
    for (var i = 0; i < length; i++) {
      var x = i * ratio;
      var i0 = Math.floor(x);
      var i1 = Math.min(i0 + 1, input.length - 1);
      var t = x - i0;
      out[i] = input[i0] * (1 - t) + input[i1] * t;
    }
    return out;
  }

  function pcm16Base64(samples) {
    var bytes = new Uint8Array(samples.length * 2);
    var view = new DataView(bytes.buffer);
    for (var i = 0; i < samples.length; i++) {
      var s = Math.max(-1, Math.min(1, samples[i]));
      view.setInt16(i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
    }
    var binary = "";
    for (var j = 0; j < bytes.length; j++) binary += String.fromCharCode(bytes[j]);
    return btoa(binary);
  }

  function b64ToPcm(b64) {
    var binary = atob(b64);
    var bytes = new Uint8Array(binary.length);
    for (var i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
    var view = new DataView(bytes.buffer);
    var samples = new Float32Array(Math.floor(bytes.length / 2));
    for (var n = 0; n < samples.length; n++) samples[n] = view.getInt16(n * 2, true) / 32768;
    return samples;
  }

  function init(root) {
    var openBtn = root.querySelector("[data-agent-open]");
    var panel = root.querySelector("[data-agent-panel]");
    var mic = root.querySelector("[data-agent-mic]");
    var statusEl = root.querySelector("[data-agent-status]");
    var transcriptEl = root.querySelector("[data-agent-transcript]");
    var dialog = root.querySelector(".agent-dialog");
    if (!openBtn || !panel || !mic) return;

    var ws = null;
    var audioCtx = null;
    var stream = null;
    var processor = null;
    var muted = false;
    var starting = false;
    var playAt = 0;
    var sources = [];
    var transcript = "";
    var callNames = {};
    var argBuffers = {};
    var liveTargets = {};
    var liveShown = {};
    var liveTimer = null;
    var sheet = document.querySelector("[data-live-invoice]");
    var liveFields = ["client_name", "client_siren", "amount_ht", "vat_rate", "designation"];
    var durationEl = root.querySelector("[data-agent-duration]");
    var wakeEl = root.querySelector("[data-agent-wakelock]");
    var reconnectBtn = root.querySelector("[data-agent-reconnect]");
    var draftLink = root.querySelector("[data-agent-draft]");
    var liveDot = root.querySelector("[data-agent-live-dot]");
    var startedAt = 0;
    var durationTimer = null;
    var engine = "xai";
    var elevenOutRate = 24000;
    var sessionCompanyId = companyIdFromPage();
    var logEl = root.querySelector("[data-agent-log]");
    var pendingOps = 0;
    var agentSpeakingUntil = 0;
    var silenceTimer = null;
    var farewellTimer = null;

    function lockCall(on) {
      if (window.AminiaShell && window.AminiaShell.active) {
        window.AminiaShell.setLock(!!on);
      }
    }

    function agentLog(text, kind) {
      if (!logEl) return;
      var li = document.createElement("li");
      if (kind) li.className = kind;
      li.textContent = text;
      logEl.appendChild(li);
      while (logEl.children.length > 50) logEl.removeChild(logEl.firstChild);
      logEl.scrollTop = logEl.scrollHeight;
    }

    function clearSilence() {
      if (silenceTimer) window.clearTimeout(silenceTimer);
      if (farewellTimer) window.clearTimeout(farewellTimer);
      silenceTimer = null;
      farewellTimer = null;
    }

    function armSilence() {
      clearSilence();
      if (!ws || ws.readyState !== 1 || muted) return;
      if (Date.now() < agentSpeakingUntil) return;
      if (pendingOps > 0) return;
      silenceTimer = window.setTimeout(function () {
        silenceTimer = null;
        setStatus("Vous êtes toujours là ?");
        agentLog("Vous êtes toujours là ?", "pending");
        try {
          if (engine === "xai") {
            ws.send(JSON.stringify({
              type: "conversation.item.create",
              item: {
                type: "message",
                role: "user",
                content: [{
                  type: "input_text",
                  text: "Silence détecté. Dis à voix haute, en une courte phrase : « Vous êtes toujours là ? » Puis attends."
                }]
              }
            }));
            ws.send(JSON.stringify({ type: "response.create" }));
          }
        } catch (e) { /* socket fermé : le hangup suivra */ }
        farewellTimer = window.setTimeout(function () {
          farewellTimer = null;
          setStatus("Je vous laisse, à bientôt.");
          agentLog("Je vous laisse, à bientôt.", "pending");
        }, 5000);
        hangupTimer = window.setTimeout(function () {
          hangupTimer = null;
          hangup();
          setStatus("Je vous laisse, à bientôt.");
        }, 5600);
      }, 4000);
    }

    var hangupTimer = null;

    function setStatus(text) {
      if (statusEl) statusEl.textContent = text;
    }

    /* Pendant une opération (brouillon, recherche…), l'overlay se réduit en
       une petite carte pour laisser voir l'application derrière. */
    function setMinimized(on) {
      if (panel) panel.classList.toggle("is-minimized", !!on);
    }

    /* Les URLs des outils sont sans préfixe : dans la coque dark, on les
       remonte sous /dark pour ne pas sauter à la version claire. */
    function themePath(path) {
      if (
        path &&
        path.charAt(0) === "/" &&
        path.indexOf("/dark") !== 0 &&
        document.documentElement.getAttribute("data-theme") === "dark"
      ) {
        return "/dark" + path;
      }
      return path;
    }

    function setTranscript(text) {
      transcript = text;
      if (transcriptEl) transcriptEl.textContent = text;
    }

    function setListening(on) {
      if (dialog) dialog.classList.toggle("is-listening", on);
      mic.classList.toggle("is-listening", on);
    }

    function setLiveIndicator(on) {
      if (liveDot) liveDot.hidden = !on;
      if (dialog) dialog.classList.toggle("is-live", on);
    }

    function setReconnect(on) {
      if (reconnectBtn) reconnectBtn.hidden = !on;
    }

    function setDraft(url, number) {
      if (!draftLink) return;
      if (!url) {
        draftLink.hidden = true;
        draftLink.removeAttribute("href");
        return;
      }
      draftLink.hidden = false;
      draftLink.href = themePath(url);
      draftLink.textContent = number ? "Brouillon " + number : "Brouillon";
    }

    function updateDuration() {
      if (!durationEl) return;
      if (!startedAt) {
        durationEl.textContent = "00:00";
        return;
      }
      var seconds = Math.max(0, Math.floor((Date.now() - startedAt) / 1000));
      var minutes = Math.floor(seconds / 60);
      durationEl.textContent =
        String(minutes).padStart(2, "0") + ":" + String(seconds % 60).padStart(2, "0");
    }

    function startDuration() {
      startedAt = Date.now();
      updateDuration();
      if (durationTimer) window.clearInterval(durationTimer);
      durationTimer = window.setInterval(updateDuration, 1000);
    }

    function stopDuration() {
      if (durationTimer) window.clearInterval(durationTimer);
      durationTimer = null;
      startedAt = 0;
      updateDuration();
    }

    async function requestWakeLock() {
      if (!wakeEnabled || !("wakeLock" in navigator) || document.hidden) return;
      if (wakeLock && !wakeLock.released) return;
      try {
        wakeLock = await navigator.wakeLock.request("screen");
        wakeLock.addEventListener("release", function () {
          wakeLock = null;
        });
      } catch (error) {
        wakeLock = null;
        if (wakeEl) {
          wakeEl.title = "Le navigateur n'autorise pas le maintien de l'écran.";
        }
      }
    }

    function releaseWakeLock() {
      if (!wakeLock) return;
      try {
        wakeLock.release();
      } catch (error) {
        /* ignore */
      }
      wakeLock = null;
    }

    /* Certains navigateurs relâchent le verrou après un changement d'onglet
       ou une coupure réseau. On le redemande tant que l'appel est vivant. */
    function startWakeGuard() {
      if (wakeTimer) window.clearInterval(wakeTimer);
      wakeTimer = window.setInterval(function () {
        if (ws && ws.readyState === 1 && document.visibilityState === "visible") {
          requestWakeLock();
        }
      }, 15000);
    }

    function stopWakeGuard() {
      if (wakeTimer) window.clearInterval(wakeTimer);
      wakeTimer = null;
    }

    function syncWakePreference() {
      if (!wakeEl) return;
      wakeEl.checked = wakeEnabled;
      wakeEl.addEventListener("change", function () {
        wakeEnabled = !!wakeEl.checked;
        try {
          window.localStorage.setItem(WAKE_KEY, wakeEnabled ? "1" : "0");
        } catch (error) {
          /* stockage indisponible */
        }
        if (wakeEnabled && ws && ws.readyState === 1) requestWakeLock();
        else releaseWakeLock();
      });
    }

    function goToDraft(event) {
      if (!draftLink || !draftLink.href) return;
      if (window.AminiaShell && window.AminiaShell.active) {
        event.preventDefault();
        window.AminiaShell.navigate(draftLink.href);
      }
    }

    syncWakePreference();
    if (draftLink) draftLink.addEventListener("click", goToDraft);

    function stopPlayback() {
      for (var i = 0; i < sources.length; i++) {
        try { sources[i].stop(); } catch (e) { /* déjà terminé */ }
      }
      sources = [];
      playAt = 0;
    }

    function playSamples(samples) {
      if (!audioCtx || !samples.length) return;
      var rate = engine === "eleven" ? elevenOutRate : SAMPLE_RATE;
      var buffer = audioCtx.createBuffer(1, samples.length, rate);
      buffer.copyToChannel(samples, 0);
      var source = audioCtx.createBufferSource();
      source.buffer = buffer;
      source.connect(audioCtx.destination);
      var now = audioCtx.currentTime;
      if (playAt < now + 0.05) playAt = now + 0.08;
      source.start(playAt);
      playAt += buffer.duration;
      sources.push(source);
      source.onended = function () {
        var idx = sources.indexOf(source);
        if (idx >= 0) sources.splice(idx, 1);
      };
    }

    function hangup() {
      muted = false;
      starting = false;
      setListening(false);
      setLiveIndicator(false);
      setReconnect(false);
      stopWakeGuard();
      releaseWakeLock();
      stopDuration();
      stopPlayback();
      if (processor) {
        try { processor.disconnect(); } catch (e) { /* ignore */ }
        processor.onaudioprocess = null;
        processor = null;
      }
      if (stream) {
        stream.getTracks().forEach(function (track) {
          track.onended = null;
          track.stop();
        });
        stream = null;
      }
      if (ws) {
        try { ws.close(); } catch (e) { /* ignore */ }
        ws = null;
      }
      if (audioCtx) {
        audioCtx.close().catch(function () {});
        audioCtx = null;
      }
      pendingOps = 0;
      agentSpeakingUntil = 0;
      clearSilence();
      setMinimized(false);
    }

    function sendAudio(input) {
      if (!ws || ws.readyState !== 1 || muted || !audioCtx) return;
      if (engine === "eleven") {
        var chunks = resample(input, audioCtx.sampleRate, 16000);
        if (!chunks.length) return;
        ws.send(JSON.stringify({
          type: "user_audio_chunk",
          user_audio_chunk: pcm16Base64(chunks)
        }));
        return;
      }
      var samples = resample(input, audioCtx.sampleRate, SAMPLE_RATE);
      if (!samples.length) return;
      ws.send(JSON.stringify({
        type: "input_audio_buffer.append",
        audio: pcm16Base64(samples)
      }));
    }

    function fieldBox(key) {
      var target = activeDocument();
      var formField = target.querySelector("form [name='" + key + "']");
      if (formField) return formField;
      return target.querySelector("[data-live-field='" + key + "']");
    }

    function parsePartial(buffer) {
      function text(key) {
        var re = new RegExp('"' + key + '"\\s*:\\s*"((?:\\\\.|[^"\\\\])*)');
        var match = buffer.match(re);
        if (!match) return "";
        try { return JSON.parse('"' + match[1] + '"'); } catch (e) { return match[1]; }
      }
      function num(key) {
        var asText = text(key);
        if (asText) return asText;
        var re = new RegExp('"' + key + '"\\s*:\\s*([0-9]+(?:[.,][0-9]*)?)');
        var match = buffer.match(re);
        return match ? match[1] : "";
      }
      return {
        client_name: text("client_name"),
        client_siren: text("client_siren") || num("client_siren"),
        amount_ht: text("amount_ht") || num("amount_ht"),
        vat_rate: text("vat_rate") || num("vat_rate"),
        designation: text("designation")
      };
    }

    function paintLive() {
      var pending = false;
      var activeKey = "";
      for (var i = 0; i < liveFields.length; i++) {
        var key = liveFields[i];
        var target = liveTargets[key] || "";
        var current = liveShown[key] || "";
        if (!activeKey && current.length < target.length) {
          current = target.slice(0, current.length + 1);
          liveShown[key] = current;
          activeKey = key;
        }
        if ((liveShown[key] || "").length < target.length) pending = true;
        var box = fieldBox(key);
        if (!box) continue;
        var value = liveShown[key] || "";
        if (box.value !== value) box.value = value;
        box.classList.toggle("is-typing", key === activeKey);
      }
      var line = document.querySelector("[data-live-line]");
      if (line) {
        line.textContent = pending ? "Aminia écrit…" : "Saisie terminée.";
      }
      if (!pending && liveTimer) {
        window.clearInterval(liveTimer);
        liveTimer = null;
      }
    }

    function armLive(values) {
      liveShown = {};
      liveTargets = {};
      for (var i = 0; i < liveFields.length; i++) {
        var key = liveFields[i];
        var box = fieldBox(key);
        if (box) box.value = "";
        liveTargets[key] = values[key] || "";
      }
      if (sheet) sheet.hidden = false;
      var panel = root.querySelector("[data-agent-panel]");
      var openBtn = root.querySelector("[data-agent-open]");
      if (panel) panel.hidden = false;
      if (openBtn) openBtn.setAttribute("aria-expanded", "true");
      document.body.classList.add("agent-open");
      if (liveTimer) window.clearInterval(liveTimer);
      liveTimer = window.setInterval(paintLive, 48);
      setStatus("Aminia saisit la facture…");
    }

    function showLiveInvoice(buffer) {
      var parsed = parsePartial(buffer);
      var target = activeDocument();
      var form = target.querySelector("form [name='client_name']");
      var hasForm = !!form;
      if (sheet && !hasForm) sheet.hidden = false;
      if (hasForm && form.scrollIntoView) {
        form.scrollIntoView({ block: "center", behavior: "smooth" });
      }
      for (var i = 0; i < liveFields.length; i++) {
        var key = liveFields[i];
        var next = parsed[key] || "";
        if (next.length >= (liveTargets[key] || "").length) liveTargets[key] = next;
      }
      if (!liveTimer) liveTimer = window.setInterval(paintLive, 48);
      setStatus("Aminia saisit la facture…");
    }

    window.AminiaSaisie = {
      play: function (values) {
        armLive(values || {
          client_name: "Atelier Martin",
          client_siren: "552100554",
          amount_ht: "800,00",
          vat_rate: "20",
          designation: "Pose de fenêtres"
        });
      }
    };

    window.AminiaCherche = {
      cherche: function (query) {
        var encoded = encodeURIComponent(query || "");
        return fetch("/agent/recherche/?query=" + encoded + "&limit=5", {
          credentials: "same-origin",
          headers: { Accept: "application/json" }
        })
          .then(function (response) {
            return response.json().then(function (data) {
              return { status: response.status, data: data };
            });
          })
          .then(function (payload) {
            var data = payload.data || {};
            if (data.error && payload.status !== 200) {
              setStatus(data.error);
              return data;
            }
            showCompanyResults(data);
            return data;
          });
      }
    };

    function liveCaughtUp() {
      for (var i = 0; i < liveFields.length; i++) {
        var key = liveFields[i];
        if ((liveShown[key] || "") !== (liveTargets[key] || "")) return false;
      }
      return true;
    }

    function whenTyped(done) {
      var started = Date.now();
      function wait() {
        paintLive();
        if (liveCaughtUp() || Date.now() - started > 3500) done();
        else window.setTimeout(wait, 40);
      }
      wait();
    }

    function finishLive(output) {
      var invoice = output && output.invoice;
      var link = document.querySelector("[data-live-open]");
      if (invoice) {
        setDraft(invoice.url, invoice.number);
        var liveBox = document.querySelector("[data-live-invoice]");
        if (liveBox) {
          liveBox.setAttribute("data-live-draft-id", String(invoice.id || ""));
          liveTimer = window.setInterval(paintLive, 48);
        }
        /* Le brouillon existe : la relecture plein écran est prête à être
           validée. Valider ouvre le brouillon (et termine l'appel). */
        var validate = document.querySelector("[data-live-validate]");
        if (validate) {
          validate.removeAttribute("hidden");
          validate.href = themePath(invoice.url);
        }
      }
      if (!invoice || !link) return;
      link.hidden = false;
      link.href = themePath(invoice.url);
      link.textContent = "Ouvrir " + invoice.number;
      var line = document.querySelector("[data-live-line]");
      if (line) line.textContent = "Brouillon " + invoice.number + " enregistré — modifiable ici ou par Aminia.";
      refreshLiveSheet();
    }

    /* ---- Panneau de recherche d'entreprises (annuaire officiel) ---- */
    var companySearch = { company: null, selected: null };

    function esc(text) {
      var box = document.createElement("div");
      box.textContent = text == null ? "" : String(text);
      return box.innerHTML;
    }

    function showCompanyResults(output) {
      var panel = document.querySelector("[data-agent-results]");
      var box = document.querySelector("[data-agent-results-list]");
      var title = document.querySelector("[data-agent-results-title]");
      var sub = document.querySelector("[data-agent-results-sub]");
      var actions = document.querySelector("[data-agent-results-actions]");
      if (!panel || !box || !title || !sub || !actions) return;
      companySearch.company = (output && output.company) || null;
      companySearch.selected = null;
      var items = (output && output.results) || [];
      if (!items.length) {
        title.textContent = "Aucun résultat";
        sub.textContent = (output && output.message) || "Reformulez ou vérifiez le SIREN.";
        box.innerHTML = "";
        actions.hidden = true;
      } else {
        title.textContent = "Entreprises trouvées";
        sub.textContent =
          items.length + (items.length > 1 ? " fiches" : " fiche") +
          (output.geo_filtre ? " filtrées par ville ou code postal" : "") +
          " — dites « la première », « la deuxième »…";
        var html = "";
        for (var i = 0; i < items.length; i++) {
          var item = items[i];
          var badges = "";
          if (item.deja_client) badges += '<span class="badge badge-green">déjà client</span>';
          if (item.deja_fournisseur) badges += '<span class="badge badge-blue">déjà fournisseur</span>';
          html += '<button class="agent-result-row" type="button" data-result-index="' + esc(item.index) + '">'
            + '<span class="agent-result-rank" aria-hidden="true">' + esc(item.index) + '</span>'
            + '<span class="agent-result-main"><b>' + esc(item.denomination) + '</b>'
            + '<small>' + esc(item.forme ? item.forme + " · " : "") + 'SIREN ' + esc(item.siren)
            + (item.siret ? " · SIRET " + esc(item.siret) : "") + (item.etat ? " · " + esc(item.etat) : "") + '</small>'
            + '<small>' + esc(item.adresse || "") + (item.ville ? " · " + esc(item.ville) : "") + '</small></span>'
            + (badges ? '<span class="agent-result-badges">' + badges + '</span>' : "")
            + '</button>';
        }
        box.innerHTML = html;
        actions.hidden = true;
      }
      panel.hidden = false;
    }

    function showPickedResult(output) {
      var card = (output && output.selected) || null;
      var box = document.querySelector("[data-agent-results-list]");
      var actions = document.querySelector("[data-agent-results-actions]");
      var sub = document.querySelector("[data-agent-results-sub]");
      if (!box || !actions || !card) return;
      companySearch.selected = card;
      var rows = box.querySelectorAll("[data-result-index]");
      for (var i = 0; i < rows.length; i++) {
        rows[i].classList.toggle("is-on", String(rows[i].getAttribute("data-result-index")) === String(card.index));
      }
      if (sub) {
        sub.textContent = "Fiche sélectionnée : " + (card.denomination || "") + " — dites ce que vous en faites (client, fournisseur, facture…).";
      }
      var enc = encodeURIComponent;
      var base = companySearch.company && companySearch.company.id ? "societe=" + enc(companySearch.company.id) + "&" : "";
      var map = {
        client: "/factures/clients/nouveau/?" + base + "name=" + enc(card.denomination || "") + "&siren=" + enc(card.siren || "") + "&address=" + enc(card.adresse || ""),
        supplier: "/fournisseurs/rechercher/?q=" + enc(card.siren || ""),
        invoice: "/factures/nouvelle/?" + base + "client_name=" + enc(card.denomination || "") + "&client_siren=" + enc(card.siren || ""),
        quote: "/devis/nouveau/?" + base + "client_name=" + enc(card.denomination || "") + "&client_siren=" + enc(card.siren || "")
      };
      var links = actions.querySelectorAll("[data-dest]");
      for (var j = 0; j < links.length; j++) {
        links[j].href = themePath(map[links[j].getAttribute("data-dest")] || "#");
      }
      actions.hidden = false;
    }

    function closeCompanyResults() {
      var panel = document.querySelector("[data-agent-results]");
      if (panel) panel.hidden = true;
    }

    function initCompanyResults(root) {
      var panel = root.querySelector("[data-agent-results]");
      if (!panel) return;
      panel.addEventListener("click", function (event) {
        var target = event.target;
        if (!target || !target.closest) return;
        if (target.closest("[data-agent-results-close]")) {
          closeCompanyResults();
          return;
        }
        var row = target.closest("[data-result-index]");
        if (!row) return;
        var index = row.getAttribute("data-result-index");
        setStatus("Sélection de la fiche " + index + "…");
        // Sélection par GET : lecture seule, compatible mode démo.
        fetch("/agent/recherche/?choisir=" + encodeURIComponent(index), {
          credentials: "same-origin",
          headers: { Accept: "application/json" }
        })
          .then(function (response) {
            return response.json().then(function (data) {
              return { status: response.status, data: data };
            });
          })
          .then(function (payload) {
            var data = payload.data || {};
            if (data.selected) showPickedResult({ selected: data.selected });
            else if (data.error) setStatus(data.error);
          });
      });
    }

    var TOOL_LOG = {
      get_company_overview: "Recherche de la société…",
      list_companies: "Recherche des sociétés…",
      switch_company: "Changement de société…",
      get_balance: "Vérification du solde…",
      list_entries: "Lecture du grand livre…",
      list_drafts: "Vérification des brouillons…",
      propose_entry: "Préparation de l'écriture…",
      draft_client: "Préparation du client…",
      draft_invoice: "Préparation de la facture…",
      search_french_companies: "Recherche officielle (annuaire INSEE)…",
      choose_company_result: "Sélection de la fiche…",
    };

    function logToolOutcome(name, output) {
      var kind = "ok";
      var text = "";
      if (!output || output.error) {
        kind = "error";
        text = typeof output.error === "string" ? output.error : (output.message || "Échec de l'opération.");
      } else if (name === "draft_invoice" && output.invoice && output.invoice.number) {
        text = "Facture " + output.invoice.number + " créée (brouillon).";
      } else if (name === "propose_entry" || (output.entry && output.entry.label)) {
        text = "Écriture proposée — à valider au grand livre.";
      } else if (name === "draft_client") {
        text = "Brouillon client créé — à valider.";
      } else if (output.company && output.company.denomination) {
        text = "Société : " + output.company.denomination + ".";
      } else {
        text = "Vérification terminée.";
      }
      agentLog(text, kind);
    }

    function runTool(name, args, respond) {
      setMinimized(true);
      agentLog(TOOL_LOG[name] || "Exécution en cours…", "pending");
      pendingOps += 1;
      clearSilence();
      postJson("/agent/outil/", { name: name, arguments: args }).then(function (data) {
        var output = data.output || { error: data.message || data.error || "outil indisponible" };
        if (name === "draft_invoice") finishLive(output);
        if (name === "search_french_companies") showCompanyResults(output);
        if (name === "choose_company_result") showPickedResult(output);
        if (output.company && output.company.denomination) {
          setStatus("Société : " + output.company.denomination);
        }
        pendingOps = Math.max(0, pendingOps - 1);
        logToolOutcome(name, output);
        respond(output);
        if (pendingOps === 0) armSilence();
      }).catch(function () {
        pendingOps = Math.max(0, pendingOps - 1);
        agentLog("Échec de l'opération — réseau indisponible.", "error");
      });
    }

    function handleTool(event) {
      var args = event.arguments || "{}";
      if (engine === "eleven") return;
      var send = function () {
        runTool(event.name, args, function (output) {
          if (!ws || ws.readyState !== 1) return;
          ws.send(JSON.stringify({
            type: "conversation.item.create",
            item: {
              type: "function_call_output",
              call_id: event.call_id,
              output: JSON.stringify(output)
            }
          }));
          ws.send(JSON.stringify({ type: "response.create" }));
        });
      };
      if (event.name === "draft_invoice") {
        showLiveInvoice(typeof args === "string" ? args : JSON.stringify(args));
        whenTyped(send);
        return;
      }
      if (event.name === "search_french_companies") {
        setStatus("Recherche dans l'annuaire officiel…");
      }
      if (event.name === "choose_company_result") {
        setStatus("Fiche sélectionnée…");
      }
      send();
    }

    function onMessage(raw) {
      var event;
      try { event = JSON.parse(raw.data); } catch (e) { return; }
      var type = event.type || "";
      if (type === "input_audio_buffer.speech_started") {
        stopPlayback();
        clearSilence();
        setListening(true);
        setStatus("Je vous écoute…");
      } else if (type === "input_audio_buffer.speech_stopped") {
        setListening(false);
        setStatus("Aminia réfléchit…");
        agentLog("Analyse de votre demande…", "pending");
      } else if (type.indexOf("audio") !== -1 && type.indexOf("delta") !== -1 && (event.delta || event.audio)) {
        clearSilence();
        agentSpeakingUntil = Date.now() + 400;
        setStatus("Aminia parle…");
        try { playSamples(b64ToPcm(event.delta || event.audio)); } catch (e) { /* chunk illisible */ }
      } else if (type.indexOf("transcript") !== -1 && event.delta) {
        setTranscript((transcript + event.delta).slice(-400));
      } else if (type === "response.output_item.added" && event.item && event.item.name) {
        callNames[event.item.call_id || ""] = event.item.name;
      } else if (type === "response.function_call_arguments.delta") {
        var callId = event.call_id || "";
        argBuffers[callId] = (argBuffers[callId] || "") + (event.delta || "");
        if ((callNames[callId] || event.name) === "draft_invoice") showLiveInvoice(argBuffers[callId]);
      } else if (type === "response.function_call_arguments.done") {
        setStatus(event.name === "draft_invoice" ? "Aminia saisit la facture…" : "Je consulte la comptabilité…");
        handleTool(event);
      } else if (type === "response.done") {
        if (pendingOps === 0) {
          agentLog("Écoute en cours…", "pending");
          armSilence();
        }
      } else if (type === "error") {
        var message = (event.error && (event.error.message || event.error)) || "Erreur vocale.";
        setStatus(typeof message === "string" ? message : "Erreur vocale.");
        agentLog(typeof message === "string" ? message : "Erreur vocale.", "error");
      }
    }

    function configure(session) {
      ws.send(JSON.stringify({
        type: "session.update",
        session: {
          voice: session.voice || "eve",
          instructions: session.instructions,
          turn_detection: { type: "server_vad" },
          audio: {
            input: { format: { type: "audio/pcm", rate: SAMPLE_RATE } },
            output: { format: { type: "audio/pcm", rate: SAMPLE_RATE } }
          },
          tools: session.tools || []
        }
      }));
      var who = session.company_name ? " de " + session.company_name : "";
      var greeting = session.greeting || "Bonjour, que puis-je faire pour vous ?";
      ws.send(JSON.stringify({
        type: "conversation.item.create",
        item: {
          type: "message",
          role: "user",
          content: [{
            type: "input_text",
            text: "L'utilisateur vient d'ouvrir Aminia. Dis d'abord exactement : « " + greeting + " » puis dis en une phrase que tu gères la comptabilité" + who + "."
          }]
        }
      }));
      ws.send(JSON.stringify({ type: "response.create" }));
    }

    function start() {
      if (starting || (ws && ws.readyState === 1)) return;
      starting = true;
      engine = "xai";
      setStatus("Connexion à Aminia…");
      setTranscript("");
      postJson("/agent/session/", { company_id: companyIdFromPage() }).then(function (session) {
        if (session._status === 401) {
          starting = false;
          setStatus(session.message || "Connectez-vous au cockpit.");
          return;
        }
        if (session.provider === "elevenlabs" && session.signed_url) {
          startEleven(session);
          return;
        }
        if (session.notice) setStatus(session.notice);
        if (!session.token) {
          starting = false;
          setStatus(session.message || "Agent vocal indisponible.");
          return;
        }
        sessionCompanyId = session.company_id || companyIdFromPage();
        var AudioContext = window.AudioContext || window.webkitAudioContext;
        audioCtx = new AudioContext();
        return navigator.mediaDevices.getUserMedia({
          audio: { echoCancellation: true, noiseSuppression: true }
        }).then(function (userStream) {
          stream = userStream;
          var socket = new WebSocket(session.url, ["xai-client-secret." + session.token]);
          ws = socket;
          socket.onopen = function () {
            starting = false;
            setStatus("Aminia est en ligne.");
            setListening(true);
            setLiveIndicator(true);
            setReconnect(false);
            startDuration();
            startWakeGuard();
            requestWakeLock();
            lockCall(true);
            agentLog("Communication établie avec Aminia.", "ok");
            var audioTrack = stream.getAudioTracks()[0];
            if (audioTrack) {
              audioTrack.onended = function () {
                setListening(false);
                setLiveIndicator(false);
                setReconnect(true);
                stopWakeGuard();
                releaseWakeLock();
                setStatus("Microphone interrompu. Reconnectez Aminia.");
              };
            }
            configure(session);
            var source = audioCtx.createMediaStreamSource(stream);
            processor = audioCtx.createScriptProcessor(4096, 1, 1);
            processor.onaudioprocess = function (e) {
              sendAudio(e.inputBuffer.getChannelData(0));
            };
            var silent = audioCtx.createGain();
            silent.gain.value = 0;
            source.connect(processor);
            processor.connect(silent);
            silent.connect(audioCtx.destination);
            audioCtx.resume();
          };
          socket.onmessage = onMessage;
          socket.onerror = function () {
            starting = false;
            setListening(false);
            setLiveIndicator(false);
            setReconnect(true);
            stopWakeGuard();
            releaseWakeLock();
            setStatus("Connexion vocale interrompue.");
          };
          socket.onclose = function () {
            if (!panel.hidden) {
              setStatus("Session vocale interrompue. Reconnectez Aminia.");
            }
            setListening(false);
            setLiveIndicator(false);
            setReconnect(true);
            stopWakeGuard();
            releaseWakeLock();
            ws = null;
          };
        });
      }).catch(function () {
        starting = false;
        hangup();
        setReconnect(true);
        setStatus("Micro ou réseau indisponible. Reconnectez Aminia.");
      });
    }

    /* Fab ouvre le sélecteur ; le vocal démarre via aminia:open-voice. */
    function startEleven(session) {
      sessionCompanyId = session.company_id || companyIdFromPage();
      var AudioContext = window.AudioContext || window.webkitAudioContext;
      audioCtx = new AudioContext();
      navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true }
      }).then(function (userStream) {
        stream = userStream;
        engine = "eleven";
        elevenOutRate = 24000;
        var socket = new WebSocket(session.signed_url);
        ws = socket;
        socket.onopen = function () {
          starting = false;
          setStatus("Aminia est en ligne (ElevenLabs).");
          setListening(true);
          setLiveIndicator(true);
          setReconnect(false);
          startDuration();
          startWakeGuard();
          requestWakeLock();
          lockCall(true);
          agentLog("Communication établie avec Aminia.", "ok");
          socket.send(JSON.stringify({
            type: "conversation_initiation_client_data",
            conversation_config_override: {
              agent: {
                first_message: session.greeting || "Bonjour, que puis-je faire pour vous ?"
              }
            },
            custom_llm_extra_body: {
              societe_id: session.company_id || "",
              instructions: session.instructions || ""
            }
          }));
          var audioTrack = stream.getAudioTracks()[0];
          if (audioTrack) {
            audioTrack.onended = function () {
              setListening(false);
              setLiveIndicator(false);
              setReconnect(true);
              stopWakeGuard();
              releaseWakeLock();
              setStatus("Microphone interrompu. Reconnectez Aminia.");
            };
          }
          var source = audioCtx.createMediaStreamSource(stream);
          processor = audioCtx.createScriptProcessor(4096, 1, 1);
          processor.onaudioprocess = function (e) {
            sendAudio(e.inputBuffer.getChannelData(0));
          };
          var silent = audioCtx.createGain();
          silent.gain.value = 0;
          source.connect(processor);
          processor.connect(silent);
          silent.connect(audioCtx.destination);
          audioCtx.resume();
        };
        socket.onmessage = onElevenMessage;
        socket.onerror = function () {
          starting = false;
          setListening(false);
          setLiveIndicator(false);
          setReconnect(true);
          stopWakeGuard();
          releaseWakeLock();
          setStatus("Connexion ElevenLabs interrompue.");
        };
        socket.onclose = function () {
          if (!panel.hidden) {
            setStatus("Session vocale interrompue. Reconnectez Aminia.");
          }
          setListening(false);
          setLiveIndicator(false);
          setReconnect(true);
          stopWakeGuard();
          releaseWakeLock();
          ws = null;
        };
      });
    }

    function elevenToolRespond(callId, output) {
      if (!ws || ws.readyState !== 1) return;
      ws.send(JSON.stringify({
        type: "client_tool_result",
        tool_call_id: callId,
        result: JSON.stringify(output),
        is_error: false
      }));
    }

    function onElevenMessage(raw) {
      var evt;
      try { evt = JSON.parse(raw.data); } catch (e) { return; }
      var type = evt.type || "";
      if (type === "conversation_initiation_metadata") {
        var meta = evt.conversation_initiation_metadata_event || {};
        var outFormat = String(meta.agent_output_audio_format || "");
        var rate = parseInt(outFormat.replace("pcm_", ""), 10);
        if (rate > 0) elevenOutRate = rate;
        setStatus("Aminia est en ligne.");
      } else if (type === "audio" && evt.audio_event && evt.audio_event.audio_base_64) {
        clearSilence();
        agentSpeakingUntil = Date.now() + 400;
        setStatus("Aminia parle…");
        try { playSamples(b64ToPcm(evt.audio_event.audio_base_64)); } catch (e) { /* chunk illisible */ }
      } else if (type === "interruption") {
        stopPlayback();
        setStatus("Je vous écoute…");
      } else if (type === "user_transcript") {
        setTranscript(evt.user_transcription_event ? evt.user_transcription_event.user_transcript : "");
      } else if (type === "agent_chat_response_part") {
        var part = evt.text_response_part || {};
        if (part.text && part.type === "delta") setStatus("Aminia réfléchit…");
      } else if (type === "agent_response") {
        var reply = (evt.agent_response_event || {}).agent_response || "";
        if (reply) setTranscript(reply.slice(-400));
      } else if (type === "client_tool_call" || type === "agent_tool_request") {
        var payload = evt.client_tool_call || evt.agent_tool_request || {};
        var name = payload.tool_name || "";
        var callId = payload.tool_call_id || "";
        var args = payload.parameters || {};
        if (callId && !payload.expects_response && type === "client_tool_call") {
          /* Résultat non attendu : on exécute quand même côté serveur. */
        }
        if (name) {
          if (name === "draft_invoice") {
            showLiveInvoice(typeof args === "string" ? args : JSON.stringify(args));
            whenTyped(function () {
              runTool(name, args, function (output) {
                elevenToolRespond(callId, output);
              });
            });
          } else {
            runTool(name, args, function (output) {
              elevenToolRespond(callId, output);
            });
          }
        }
      } else if (type === "agent_response_complete") {
        agentLog("Écoute en cours…", "pending");
        armSilence();
      } else if (type === "ping") {
        var pingPayload = evt.ping_event || {};
        try {
          ws.send(JSON.stringify({ type: "pong", event_id: pingPayload.event_id }));
        } catch (e) { /* socket déjà fermé */ }
      } else if (type === "client_error") {
        var err = evt.error_event || {};
        setStatus(err.message || "Erreur ElevenLabs.");
        setReconnect(true);
      }
    }

    /* Fab ouvre le sélecteur ; le vocal démarre via aminia:open-voice. */
    document.addEventListener("aminia:open-voice", function () {
      panel.hidden = false;
      openBtn.setAttribute("aria-expanded", "true");
      document.body.classList.add("agent-open");
      requestWakeLock();
      window.setTimeout(start, 60);
    });
    root.querySelectorAll("[data-agent-close]").forEach(function (button) {
      button.addEventListener("click", function () {
        clearSilence();
        if (hangupTimer) window.clearTimeout(hangupTimer);
        hangup();
        lockCall(false);
        setStatus("Appuyez pour parler");
        if (window.AminiaShell && window.AminiaShell.active) {
          window.AminiaShell.exit();
        }
      });
    });
    if (reconnectBtn) reconnectBtn.addEventListener("click", start);
    if (dialog) {
      dialog.addEventListener("click", function (event) {
        if (!panel || !panel.classList.contains("is-minimized")) return;
        if (event.target.closest("button, a, input, textarea, select")) return;
        setMinimized(false);
      });
    }
    mic.addEventListener("click", function (event) {
      event.stopImmediatePropagation();
      if (!ws || ws.readyState !== 1) {
        start();
        return;
      }
      muted = !muted;
      if (stream) {
        stream.getAudioTracks().forEach(function (track) {
          track.enabled = !muted;
        });
      }
      setListening(!muted);
      mic.setAttribute(
        "aria-label",
        muted ? "Réactiver le microphone" : "Couper le microphone"
      );
      mic.title = muted ? "Réactiver le microphone" : "Couper le microphone";
      setStatus(muted ? "Micro coupé." : "Je vous écoute…");
    }, true);

    document.addEventListener("visibilitychange", function () {
      if (!ws || ws.readyState !== 1) return;
      if (document.visibilityState === "visible") {
        if (audioCtx && audioCtx.state === "suspended") audioCtx.resume();
        startWakeGuard();
        requestWakeLock();
        setStatus("Aminia est en ligne.");
      } else {
        releaseWakeLock();
        setStatus("Aminia continue en arrière-plan.");
      }
    });

    window.addEventListener("pageshow", function () {
      if (ws && ws.readyState === 1 && document.visibilityState === "visible") {
        startWakeGuard();
        requestWakeLock();
      }
    });

    document.addEventListener("aminia:shell-url", function (event) {
      var companyId = event.detail && event.detail.companyId;
      if (!companyId || companyId === sessionCompanyId || !ws || ws.readyState !== 1) {
        return;
      }
      sessionCompanyId = companyId;
      postJson("/agent/session/", { company_id: companyId }).then(function (session) {
        if (!session || !session.instructions || !ws || ws.readyState !== 1) return;
        ws.send(JSON.stringify({
          type: "session.update",
          session: {
            instructions: session.instructions,
            tools: session.tools || [],
          },
        }));
        setStatus(
          session.company_name
            ? "Société : " + session.company_name
            : "Contexte de société mis à jour."
        );
      });
    });

    window.addEventListener("offline", function () {
      if (ws) {
        setStatus("Réseau perdu. Aminia reprendra à la reconnexion.");
        setLiveIndicator(false);
      }
    });
    window.addEventListener("online", function () {
      if (ws && ws.readyState !== 1) setReconnect(true);
    });
    initCompanyResults(root);
    bindLivePanel();
    bindSheetPreviewForms();
  }

  /* Aperçu fidèle : facture et devis dans l'étape finale du wizard. */
  function bindSheetPreviewForms() {
    var forms = document.querySelectorAll("[data-wizard-sheet]");
    for (var i = 0; i < forms.length; i++) {
      bindSheetPreviewForm(forms[i]);
    }
  }

  function bindSheetPreviewForm(form) {
    if (!form || form.dataset.sheetPreviewWired === "1") return;
    var holder = form.querySelector("[data-wizard-sheet]");
    if (!holder) return;
    form.dataset.sheetPreviewWired = "1";
    var timer = null;
    function load() {
      fetch(holder.getAttribute("data-preview-url"), {
        method: "POST",
        body: new FormData(form),
        credentials: "same-origin",
        headers: {
          Accept: "application/json",
          "X-Requested-With": "XMLHttpRequest",
          "X-CSRFToken": csrfToken(),
        },
      })
        .then(function (response) {
          return response.ok ? response.json() : null;
        })
        .then(function (data) {
          if (data && data.html) holder.innerHTML = data.html;
        })
        .catch(function () {});
    }
    form.addEventListener("wizard:final", load);
    var refresh = form.querySelector("[data-sheet-refresh]");
    if (refresh) refresh.addEventListener("click", load);
  }

  /* Aperçu du panneau live Aminia (mêmes données, rendu serveur). */
  function refreshLiveSheet() {
    var box = document.querySelector("[data-live-invoice]");
    var sheetHolder = box ? box.querySelector("[data-live-sheet]") : null;
    if (!box || !sheetHolder) return;
    var fields = collectLiveFields();
    var body = new FormData();
    body.append("client_name", fields.client_name || "");
    body.append("client_siren", (fields.client_siren || "").replace(/\D/g, ""));
    body.append("amount_ht", fields.amount_ht || "0");
    body.append("vat_rate", (fields.vat_rate || "").replace(/[^\d.,]/g, ""));
    body.append("lines-TOTAL_FORMS", "1");
    body.append("lines-INITIAL_FORMS", "0");
    body.append("lines-MIN_NUM_FORMS", "0");
    body.append("lines-MAX_NUM_FORMS", "1000");
    body.append("lines-0-description", fields.designation || "Prestation");
    body.append("lines-0-quantity", "1.000");
    body.append("lines-0-unit_price", fields.amount_ht || "0");
    body.append("lines-0-vat_rate", (fields.vat_rate || "").replace(/[^\d.,]/g, ""));
    body.append("lines-0-id", "");
    fetch(
      sheetHolder.getAttribute("data-preview-url") || "/factures/apercu/",
      {
        method: "POST",
        body: body,
        credentials: "same-origin",
        headers: { Accept: "application/json", "X-CSRFToken": csrfToken() },
      }
    )
      .then(function (response) {
        return response.ok ? response.json() : null;
      })
      .then(function (data) {
        if (data && data.html) sheetHolder.innerHTML = data.html;
      })
      .catch(function () {});
  }

  /* Correction manuelle : bouton et mise à jour du brouillon. */
  function bindLivePanel() {
    var box = document.querySelector("[data-live-invoice]");
    if (!box || box.dataset.liveWired === "1") return;
    box.dataset.liveWired = "1";
    var timer = null;
    box.addEventListener("input", function () {
      if (box.hidden) return;
      window.clearTimeout(timer);
      timer = window.setTimeout(function () {
        var draftId = box.getAttribute("data-live-draft-id");
        if (!draftId) return;
        var fields = collectLiveFields();
        var body = new URLSearchParams();
        body.set("invoice_id", draftId);
        body.set("client_name", fields.client_name || "");
        body.set("client_siren", (fields.client_siren || "").replace(/\D/g, ""));
        body.set("amount_ht", fields.amount_ht || "");
        body.set("vat_rate", (fields.vat_rate || "").replace(/[^\d.,]/g, ""));
        body.set("designation", fields.designation || "");
        fetch("/factures/live-update/", {
          method: "POST",
          credentials: "same-origin",
          headers: {
            "Content-Type": "application/x-www-form-urlencoded",
            Accept: "application/json",
            "X-CSRFToken": csrfToken(),
          },
          body: body.toString(),
        })
          .then(function (response) {
            return response.json().then(function (data) {
              return { ok: response.ok, data: data };
            });
          })
          .then(function (payload) {
            var data = payload.data || {};
            if (payload.ok && data.invoice) {
              setStatus(
                "Facture mise à jour : " + data.invoice.number +
                " (TTC " + data.invoice.amount_ttc + " €)"
              );
            } else if (data.error) {
              setStatus(data.error);
            }
          })
          .catch(function () {});
        refreshLiveSheet();
      }, 700);
    });
    var refresh = box.querySelector("[data-live-sheet-refresh]");
    if (refresh) refresh.addEventListener("click", refreshLiveSheet);
    var openBtn = document.querySelector("[data-agent-open]");
    if (openBtn) {
      openBtn.addEventListener("click", function () {
        window.setTimeout(refreshLiveSheet, 900);
      });
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    var root = document.querySelector("[data-voice-agent]");
    if (root) init(root);
    document.querySelectorAll("[data-saisie-play]").forEach(function (button) {
      button.addEventListener("click", function () {
        if (window.AminiaSaisie) window.AminiaSaisie.play();
      });
    });
    if (document.querySelector("[data-saisie-demo]") && new URLSearchParams(window.location.search).get("saisie") === "1") {
      if (window.AminiaSaisie) window.AminiaSaisie.play();
    }
  });
})();
