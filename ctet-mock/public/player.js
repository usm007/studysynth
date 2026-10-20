/* CTET Mock — player page.
   Resolves the mock named in the query string, shows it in a frame, and keeps
   a way back to the library. */
(function () {
  "use strict";

  var frame = document.getElementById("playerFrame");
  var titleEl = document.getElementById("playerTitle");
  var errorEl = document.getElementById("playerError");
  var openLink = document.getElementById("playerOpenLink");
  var openBtn = document.getElementById("playerOpen");
  var retryBtn = document.getElementById("playerRetry");

  var LOAD_TIMEOUT = 8000;
  var mock = null;
  var timer = null;

  function queryId() {
    var match = /[?&]m=([^&]+)/.exec(window.location.search || "");
    return match ? decodeURIComponent(match[1]) : "";
  }

  function showError() {
    if (!errorEl) return;
    errorEl.hidden = false;
    frame.hidden = true;
  }

  function hideError() {
    if (!errorEl) return;
    errorEl.hidden = true;
    frame.hidden = false;
  }

  function load() {
    if (window.location.protocol === "file:") {
      titleEl.textContent = "Offline library";
      showError();
      return Promise.resolve(null);
    }
    return fetch("catalog.json", { cache: "no-cache" })
      .then(function (response) {
        if (!response.ok) throw new Error("catalogue unavailable");
        return response.json();
      })
      .then(function (catalog) {
        var id = queryId();
        var found = (catalog.mocks || []).filter(function (m) { return m.id === id; })[0];
        if (!found) throw new Error("unknown mock");
        mock = found;
        titleEl.textContent = found.title;
        document.title = found.title + " · CTET Mock";
        openLink.href = found.file;
        openBtn.setAttribute("aria-label", "Open " + found.title + " in a new tab");

        if (timer) window.clearTimeout(timer);
        timer = window.setTimeout(function () {
          if (!frame.contentDocument || !frame.contentDocument.body ||
            !frame.contentDocument.body.childNodes.length) {
            showError();
          }
        }, LOAD_TIMEOUT);

        frame.addEventListener("load", function () {
          if (timer) window.clearTimeout(timer);
          hideError();
        }, { once: true });

        frame.src = found.file;
        return found;
      })
      .catch(function () {
        titleEl.textContent = "Mock paper";
        showError();
        return null;
      });
  }

  if (openBtn) {
    openBtn.addEventListener("click", function () {
      if (mock) window.open(mock.file, "_blank", "noopener");
    });
  }
  if (retryBtn) {
    retryBtn.addEventListener("click", function () {
      hideError();
      if (mock) frame.src = mock.file + (mock.file.indexOf("?") >= 0 ? "&" : "?") +
        "retry=" + Date.now();
    });
  }

  load();
  window.CTETMockPlayer = { load: load };
})();
