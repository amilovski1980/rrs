/* Import d'historique : sélection mobile, progression et import collectif. */
(function () {
  "use strict";

  function csrfToken() {
    var input = document.querySelector("input[name=csrfmiddlewaretoken]");
    return input ? input.value : "";
  }

  function initUpload() {
    var form = document.querySelector("[data-import-upload]");
    if (!form) return;
    var inputs = form.querySelectorAll("[data-import-input]");
    var summary = form.querySelector("[data-import-summary]");
    function update() {
      var total = 0;
      Array.prototype.forEach.call(inputs, function (input) {
        total += input.files ? input.files.length : 0;
      });
      if (summary) {
        summary.textContent = total
          ? total + " fichier" + (total > 1 ? "s" : "") + " sélectionné" + (total > 1 ? "s" : "") + "."
          : "Aucun fichier sélectionné.";
      }
    }
    Array.prototype.forEach.call(inputs, function (input) {
      input.addEventListener("change", update);
    });
    update();
  }

  function initSelectAll() {
    var master = document.querySelector("[data-import-select-all]");
    if (!master) return;
    var checks = document.querySelectorAll("[data-import-check]");
    master.addEventListener("change", function () {
      Array.prototype.forEach.call(checks, function (check) {
        check.checked = master.checked;
      });
    });
  }

  function initProgress() {
    var progress = document.querySelector("[data-import-progress]");
    if (!progress) return;
    var pending = parseInt(progress.dataset.pending || "0", 10);
    var url = progress.dataset.processUrl;
    if (!url || pending <= 0) return;

    var bar = progress.querySelector("[data-import-bar]");
    var done = progress.querySelector("[data-import-done]");
    var note = progress.querySelector("[data-import-note]");
    var status = progress.querySelector("[data-import-status]");
    var activity = progress.querySelector("[data-import-activity]");
    var token = csrfToken();
    var attempts = 0;

    function paintActivities(events) {
      if (!activity || !Array.isArray(events)) return;
      activity.textContent = "";
      if (!events.length) {
        var empty = document.createElement("li");
        var dash = document.createElement("span");
        dash.className = "import-activity-time";
        dash.textContent = "—";
        var text = document.createElement("span");
        text.textContent = "Aucune activité pour le moment.";
        empty.appendChild(dash);
        empty.appendChild(text);
        activity.appendChild(empty);
        return;
      }
      events.forEach(function (event) {
        var item = document.createElement("li");
        var time = document.createElement("span");
        time.className = "import-activity-time";
        time.textContent = event.time || "";
        var body = document.createElement("span");
        var label = document.createElement("b");
        label.textContent = event.label || "Activité";
        body.appendChild(label);
        if (event.document) {
          body.appendChild(document.createTextNode(" · " + event.document));
        }
        if (event.detail) {
          var detail = document.createElement("small");
          detail.textContent = " " + event.detail;
          body.appendChild(detail);
        }
        item.appendChild(time);
        item.appendChild(body);
        activity.appendChild(item);
      });
    }

    function paint(data) {
      var total = data.total || 0;
      var left = data.pending || 0;
      var processed = Math.max(total - left, 0);
      if (done) done.textContent = processed;
      if (bar) bar.style.width = (total ? Math.round((processed / total) * 100) : 0) + "%";
      if (status) {
        status.textContent = left
          ? "Aminia analyse vos documents…"
          : "Analyse terminée.";
      }
      if (note) {
        note.textContent = left
          ? "Analyse en cours : " + left + " document(s) restant(s)."
          : "Analyse terminée. La liste va s'actualiser.";
      }
      paintActivities(data.activities || []);
    }

    function tick() {
      attempts += 1;
      fetch(url, {
        method: "POST",
        headers: {
          "X-Requested-With": "XMLHttpRequest",
          "X-CSRFToken": token,
        },
      })
        .then(function (response) {
          if (!response.ok) throw new Error("http");
          return response.json();
        })
        .then(function (data) {
          paint(data);
          if ((data.pending || 0) > 0) {
            window.setTimeout(tick, 650);
          } else {
            window.setTimeout(function () {
              window.location.reload();
            }, 1400);
          }
        })
        .catch(function () {
          if (attempts < 20) {
            window.setTimeout(tick, 1500);
          } else if (note) {
            note.textContent = "Analyse interrompue. Utilisez « Continuer maintenant ».";
          }
        });
    }

    window.setTimeout(tick, 350);
  }

  function init() {
    initUpload();
    initSelectAll();
    initProgress();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
