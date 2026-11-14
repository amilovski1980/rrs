/* Réglages SMTP : presets fournisseurs et bascule de la connexion Google. */
(function () {
  "use strict";

  var select = document.querySelector("[data-smtp-provider]");
  if (!select) return;

  var presetsNode = document.getElementById("smtp-presets");
  var presets = {};
  try {
    presets = presetsNode ? JSON.parse(presetsNode.textContent) : {};
  } catch (error) {
    presets = {};
  }

  var host = document.getElementById("id_smtp_host");
  var port = document.getElementById("id_smtp_port");
  var useTls = document.getElementById("id_smtp_use_tls");
  var username = document.getElementById("id_smtp_username");
  var password = document.getElementById("id_smtp_password");
  var fromEmail = document.getElementById("id_smtp_from_email");
  var googleBox = document.querySelector("[data-google-mail-box]");

  function toggleGoogle() {
    if (googleBox) googleBox.hidden = select.value !== "gmail";
  }

  function applyPreset(force) {
    var preset = presets[select.value];
    if (!preset) return;
    if (select.value === "custom") {
      if (force) {
        if (host) host.value = "";
        if (port) port.value = "587";
      }
    } else {
      if (host && (force || !host.value.trim())) host.value = preset.host || "";
      if (port && (force || !port.value.trim())) port.value = preset.port || 587;
      if (useTls) useTls.checked = !!preset.use_tls;
    }
    if (username) username.placeholder = preset.username_hint || "";
    if (password) password.placeholder = preset.password_hint || "";
    if (fromEmail && username) fromEmail.placeholder = username.placeholder;
    toggleGoogle();
  }

  applyPreset(false);
  select.addEventListener("change", function () {
    applyPreset(true);
  });
})();
