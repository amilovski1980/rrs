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
