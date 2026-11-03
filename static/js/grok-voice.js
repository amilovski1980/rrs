/* Assistant vocal Grok : jeton éphémère côté serveur, audio PCM 24 kHz. */
(function () {
  var SAMPLE_RATE = 24000;

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
    var params = new URLSearchParams(window.location.search);
    return params.get("societe") || "";
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

    function setStatus(text) {
      if (statusEl) statusEl.textContent = text;
    }

    function setTranscript(text) {
      transcript = text;
      if (transcriptEl) transcriptEl.textContent = text;
    }

    function setListening(on) {
      if (dialog) dialog.classList.toggle("is-listening", on);
      mic.classList.toggle("is-listening", on);
    }

    function stopPlayback() {
      for (var i = 0; i < sources.length; i++) {
        try { sources[i].stop(); } catch (e) { /* déjà terminé */ }
      }
      sources = [];
      playAt = 0;
    }

    function playSamples(samples) {
      if (!audioCtx || !samples.length) return;
      var buffer = audioCtx.createBuffer(1, samples.length, SAMPLE_RATE);
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
      stopPlayback();
      if (processor) {
        try { processor.disconnect(); } catch (e) { /* ignore */ }
        processor.onaudioprocess = null;
        processor = null;
      }
      if (stream) {
        stream.getTracks().forEach(function (track) { track.stop(); });
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
    }

    function sendAudio(input) {
      if (!ws || ws.readyState !== 1 || muted || !audioCtx) return;
      var samples = resample(input, audioCtx.sampleRate, SAMPLE_RATE);
      if (!samples.length) return;
      ws.send(JSON.stringify({
        type: "input_audio_buffer.append",
        audio: pcm16Base64(samples)
      }));
    }

    function fieldBox(key) {
      var formField = document.querySelector("form [name='" + key + "']");
      if (formField) return formField;
      return document.querySelector("[data-live-field='" + key + "']");
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
      for (var i = 0; i < liveFields.length; i++) {
        var key = liveFields[i];
        var target = liveTargets[key] || "";
        var current = liveShown[key] || "";
        if (current.length < target.length) {
          current = target.slice(0, current.length + 1);
          liveShown[key] = current;
          pending = true;
        }
        var box = fieldBox(key);
        if (!box) continue;
        if (box.value !== current) box.value = current;
        box.classList.toggle("is-typing", current.length > 0 && current.length < target.length);
      }
      var line = document.querySelector("[data-live-line]");
      if (line) {
        line.textContent = liveTargets.designation
          ? "Prestation : " + (liveShown.designation || "")
          : "Saisie en cours…";
      }
      if (!pending && liveTimer) {
        window.clearInterval(liveTimer);
        liveTimer = null;
      }
    }

    function showLiveInvoice(buffer) {
      var parsed = parsePartial(buffer);
      var hasForm = !!document.querySelector("form [name='client_name']");
      if (sheet && !hasForm) sheet.hidden = false;
      if (hasForm) {
        var form = document.querySelector("form [name='client_name']");
        if (form && form.scrollIntoView) form.scrollIntoView({ block: "center", behavior: "smooth" });
      }
      for (var i = 0; i < liveFields.length; i++) {
        liveTargets[liveFields[i]] = parsed[liveFields[i]] || "";
      }
      if (!liveTimer) liveTimer = window.setInterval(paintLive, 28);
      setStatus("Aminia saisit la facture…");
    }

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
      if (!invoice || !link) return;
      link.hidden = false;
      link.href = invoice.url;
      link.textContent = "Ouvrir " + invoice.number;
      var line = document.querySelector("[data-live-line]");
      if (line) line.textContent = "Brouillon " + invoice.number + " enregistré.";
    }

    function handleTool(event) {
      var args = event.arguments || "{}";
      var send = function () {
        postJson("/agent/outil/", { name: event.name, arguments: args }).then(function (data) {
          if (!ws || ws.readyState !== 1) return;
          var output = data.output || { error: data.message || data.error || "outil indisponible" };
          if (event.name === "draft_invoice") finishLive(output);
          if (output.company && output.company.denomination) {
            setStatus("Société : " + output.company.denomination);
          }
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
      send();
    }

    function onMessage(raw) {
      var event;
      try { event = JSON.parse(raw.data); } catch (e) { return; }
      var type = event.type || "";
      if (type === "input_audio_buffer.speech_started") {
        stopPlayback();
        setListening(true);
        setStatus("Je vous écoute…");
      } else if (type === "input_audio_buffer.speech_stopped") {
        setListening(false);
        setStatus("Aminia réfléchit…");
      } else if (type.indexOf("audio") !== -1 && type.indexOf("delta") !== -1 && (event.delta || event.audio)) {
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
      } else if (type === "error") {
        var message = (event.error && (event.error.message || event.error)) || "Erreur vocale.";
        setStatus(typeof message === "string" ? message : "Erreur vocale.");
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
      ws.send(JSON.stringify({
        type: "conversation.item.create",
        item: {
          type: "message",
          role: "user",
          content: [{
            type: "input_text",
            text: "L'utilisateur vient d'ouvrir l'assistant. Salue-le en une phrase et dis que tu gères la comptabilité" + who + "."
          }]
        }
      }));
      ws.send(JSON.stringify({ type: "response.create" }));
    }

    function start() {
      if (starting || (ws && ws.readyState === 1)) return;
      starting = true;
      setStatus("Connexion à Aminia…");
      setTranscript("");
      postJson("/agent/session/", { company_id: companyIdFromPage() }).then(function (session) {
        if (session._status === 401) {
          starting = false;
          setStatus(session.message || "Connectez-vous au cockpit.");
          return;
        }
        if (!session.token) {
          starting = false;
          setStatus(session.message || "Agent vocal indisponible.");
          return;
        }
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
            setStatus("Connexion vocale interrompue.");
          };
          socket.onclose = function () {
            if (!panel.hidden) setStatus("Session vocale terminée.");
            setListening(false);
            ws = null;
          };
        });
      }).catch(function () {
        starting = false;
        hangup();
        setStatus("Micro ou réseau indisponible.");
      });
    }

    openBtn.addEventListener("click", function () {
      window.setTimeout(start, 60);
    });
    root.querySelectorAll("[data-agent-close]").forEach(function (button) {
      button.addEventListener("click", function () {
        hangup();
        setStatus("Appuyez pour parler");
      });
    });
    mic.addEventListener("click", function (event) {
      event.stopImmediatePropagation();
      if (!ws || ws.readyState !== 1) {
        start();
        return;
      }
      muted = !muted;
      setListening(!muted);
      setStatus(muted ? "Micro coupé." : "Je vous écoute…");
    }, true);

    document.addEventListener("visibilitychange", function () {
      if (document.hidden) hangup();
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    var root = document.querySelector("[data-voice-agent]");
    if (root) init(root);
  });
})();
