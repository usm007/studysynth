/* CTET Mock — landing page logic.
   Reads the generated catalogue, renders the paper / subject / class / lesson
   / mock tree, and keeps the service worker informed about the offline state. */
(function () {
  "use strict";

  var state = {
    catalog: null,
    view: "papers",
    paperId: null,
    subjectId: null,
    classId: null,
    lessonId: null,
    query: ""
  };

  var ICONS = {
    chevron:
      '<path d="M9 5l7 7-7 7" fill="none" stroke="currentColor" stroke-width="2" ' +
      'stroke-linecap="round" stroke-linejoin="round"/>',
    back:
      '<path d="M15.5 4.5 8 12l7.5 7.5" fill="none" stroke="currentColor" ' +
      'stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>',
    external:
      '<path d="M14 4h6v6M20 4l-8.5 8.5M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5" ' +
      'fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" ' +
      'stroke-linejoin="round"/>'
  };

  var $ = function (id) { return document.getElementById(id); };
  var viewEl = $("view");
  var deferredPrompt = null;
  var reloading = false;

  function icon(name) {
    return '<svg class="ic" viewBox="0 0 24 24" aria-hidden="true" focusable="false">' +
      (ICONS[name] || "") + "</svg>";
  }

  function esc(value) {
    return String(value === null || value === undefined ? "" : value)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function countMocks(node) {
    if (!node) return 0;
    if (node.mocks) return node.mocks.length;
    var total = 0;
    ["lessons", "classes", "subjects"].forEach(function (key) {
      if (node[key]) {
        node[key].forEach(function (child) { total += countMocks(child); });
      }
    });
    return total;
  }

  function findPaper(id) {
    return (state.catalog.papers || []).filter(function (p) { return p.id === id; })[0];
  }
  function findSubject(paper, id) {
    return ((paper && paper.subjects) || []).filter(function (s) { return s.id === id; })[0];
  }
  function findClass(subject, id) {
    return ((subject && subject.classes) || []).filter(function (c) { return c.id === id; })[0];
  }
  function findLesson(klass, id) {
    return ((klass && klass.lessons) || []).filter(function (l) { return l.id === id; })[0];
  }

  function allMocks() {
    return state.catalog && state.catalog.mocks ? state.catalog.mocks : [];
  }

  function mockById(id) {
    return allMocks().filter(function (m) { return m.id === id; })[0];
  }

  /* --------------------------------------------------------- progress chip */

  function progressFor(mock) {
    var raw = null;
    try { raw = window.localStorage.getItem(mock.sessionKey); } catch (error) { raw = null; }
    if (!raw) return { label: "Not started", state: "" };
    var session = null;
    try { session = JSON.parse(raw); } catch (error) { session = null; }
    if (!session) return { label: "Not started", state: "" };
    var answers = session.answers || {};
    var answered = Object.keys(answers).length;
    var total = mock.questions || 0;
    if (!answered) return { label: "Not started", state: "" };
    if (total && answered >= total) {
      return { label: "Finished · " + answered + "/" + total, state: "is-done" };
    }
    return {
      label: "In progress · " + answered + "/" + (total || "?"),
      state: "is-going"
    };
  }

  /* ---------------------------------------------------------------- render */

  function mockCard(mock) {
    var progress = progressFor(mock);
    var action = progress.state === "is-going" ? "Resume"
      : (progress.state === "is-done" ? "Revise" : "Start");
    return (
      '<a class="mock-card" data-mock-id="' + esc(mock.id) + '" ' +
      'href="player.html?m=' + encodeURIComponent(mock.id) + '">' +
      '<span class="mock-title">' + esc(mock.title) + "</span>" +
      '<span class="mock-badges">' +
      '<span class="badge badge-paper">' + esc(mock.paper) + "</span>" +
      '<span class="badge">' + esc(mock.subject) + "</span>" +
      '<span class="badge">' + esc(mock.klass ? "Class " + mock.klass : "—") + "</span>" +
      '<span class="badge">' + esc(mock.questions) + " questions</span>" +
      "</span>" +
      '<span class="mock-foot">' +
      '<span class="mock-progress ' + progress.state + '">' + esc(progress.label) + "</span>" +
      '<span class="mock-open">' + action + "</span>" +
      "</span></a>"
    );
  }

  function plural(count, word) {
    return count + " " + word + (count === 1 ? "" : "s");
  }

  function row(title, sub, count, go, id) {
    return (
      '<button class="card" type="button" data-go="' + go + '" data-id="' + esc(id) + '">' +
      '<span class="card-main">' +
      '<span class="card-title">' + esc(title) + "</span>" +
      (sub ? '<span class="card-sub">' + esc(sub) + "</span>" : "") +
      "</span>" +
      (count === null ? "" : '<span class="card-count">' + esc(count) + "</span>") +
      '<svg class="card-chevron" viewBox="0 0 24 24" aria-hidden="true">' + ICONS.chevron + "</svg>" +
      "</button>"
    );
  }

  function renderPapers() {
    var catalog = state.catalog;
    var total = allMocks().length;
    var html =
      '<section class="view-papers">' +
      '<div class="hero"><h2>CTET Mock</h2>' +
      "<p>Mock papers for CTET Paper I and Paper II, filed by subject, class and lesson.</p>" +
      '<div class="hero-stats">' +
      '<span class="stat-pill">' + plural(catalog.papers.length, "paper") + "</span>" +
      '<span class="stat-pill">' + plural(total, "mock paper") + "</span>" +
      '<span class="stat-pill">Ready offline</span>' +
      "</div></div>";
    if (total) {
      html += row("All mock papers", "Search and open any paper", total, "all", "");
    }
    catalog.papers.forEach(function (paper) {
      html += row(
        paper.name,
        (paper.classRange || "") + " · " + plural(paper.subjects.length, "subject"),
        countMocks(paper),
        "paper",
        paper.id
      );
    });
    if (!total) {
      html +=
        '<div class="empty"><h3>No mock papers yet</h3>' +
        "<p>Drop generated mock files into the mocks folder and run the build " +
        "command to publish them here.</p></div>";
    }
    return html + "</section>";
  }

  function renderSubjects() {
    var paper = findPaper(state.paperId);
    if (!paper) return renderPapers();
    var html = '<section class="view-subjects">' +
      '<h2 class="view-head">' + esc(paper.name) + "</h2>" +
      '<p class="view-note">' + esc(paper.classRange || "") + "</p>";
    paper.subjects.forEach(function (subject) {
      html += row(
        subject.name,
        plural(subject.classes.length, "class"),
        countMocks(subject),
        "subject",
        subject.id
      );
    });
    return html + "</section>";
  }

  function renderClasses() {
    var paper = findPaper(state.paperId);
    var subject = findSubject(paper, state.subjectId);
    if (!subject) return renderSubjects();
    var html = '<section class="view-classes">' +
      '<h2 class="view-head">' + esc(subject.name) + "</h2>" +
      '<p class="view-note">' + esc(paper.name) + "</p>" +
      '<div class="grid-2">';
    subject.classes.forEach(function (klass) {
      html += row(
        klass.name,
        plural(klass.lessons.length, "lesson"),
        countMocks(klass),
        "class",
        klass.id
      );
    });
    return html + "</div></section>";
  }

  function renderLessons() {
    var paper = findPaper(state.paperId);
    var subject = findSubject(paper, state.subjectId);
    var klass = findClass(subject, state.classId);
    if (!klass) return renderClasses();
    var html = '<section class="view-lessons">' +
      '<h2 class="view-head">' + esc(klass.name) + "</h2>" +
      '<p class="view-note">' + esc(subject.name) + " · " + esc(paper.name) + "</p>";
    klass.lessons.forEach(function (lesson) {
      html += row(
        lesson.name,
        plural(lesson.mocks.length, "mock paper"),
        countMocks(lesson),
        "lesson",
        lesson.id
      );
    });
    return html + "</section>";
  }

  function renderMocksForLesson() {
    var paper = findPaper(state.paperId);
    var subject = findSubject(paper, state.subjectId);
    var klass = findClass(subject, state.classId);
    var lesson = findLesson(klass, state.lessonId);
    if (!lesson) return renderLessons();
    var html = '<section class="view-mocks">' +
      '<h2 class="view-head">' + esc(lesson.name) + "</h2>" +
      '<p class="view-note">' + esc(klass.name) + " · " + esc(subject.name) + "</p>";
    lesson.mocks.forEach(function (mock) { html += mockCard(mock); });
    return html + "</section>";
  }

  function renderAll() {
    var query = (state.query || "").toLowerCase().trim();
    var mocks = allMocks();
    if (query) {
      mocks = mocks.filter(function (mock) {
        return [mock.title, mock.paper, mock.subject, mock.lesson,
          mock.klass ? "class " + mock.klass : ""].join(" ")
          .toLowerCase().indexOf(query) >= 0;
      });
    }
    var html = '<section class="view-all">' +
      '<h2 class="view-head">' + (query ? "Search results" : "All mock papers") + "</h2>" +
      '<p class="view-note">' + mocks.length + " of " + allMocks().length + " papers</p>";
    if (!mocks.length) {
      html += '<div class="empty"><h3>Nothing matches that</h3>' +
        "<p>Try a subject, a class or a lesson name.</p></div>";
    }
    mocks.forEach(function (mock) { html += mockCard(mock); });
    return html + "</section>";
  }

  function renderCrumbs() {
    var crumbs = $("crumbs");
    var parts = [{ label: "Library", go: "home", id: "" }];
    var paper = findPaper(state.paperId);
    if (paper) {
      parts.push({ label: paper.name, go: "paper", id: paper.id });
      var subject = findSubject(paper, state.subjectId);
      if (subject) {
        parts.push({ label: subject.name, go: "subject", id: subject.id });
        var klass = findClass(subject, state.classId);
        if (klass) {
          parts.push({ label: klass.name, go: "class", id: klass.id });
          var lesson = findLesson(klass, state.lessonId);
          if (lesson) {
            parts.push({ label: lesson.name, go: "lesson", id: lesson.id });
          }
        }
      }
    }
    var html = "";
    parts.forEach(function (part, index) {
      var last = index === parts.length - 1;
      if (index) html += '<span class="crumb-sep" aria-hidden="true">›</span>';
      html += '<button class="crumb" type="button" data-go="' + part.go +
        '" data-id="' + esc(part.id) + '"' +
        (last ? ' aria-current="page"' : "") + ">" + esc(part.label) + "</button>";
    });
    crumbs.innerHTML = html;
    $("btnHome").hidden = parts.length <= 1;
  }

  function render() {
    if (!state.catalog) return;
    if (state.query) {
      viewEl.innerHTML = renderAll();
    } else if (state.view === "all") {
      viewEl.innerHTML = renderAll();
    } else if (state.view === "subjects") {
      viewEl.innerHTML = renderSubjects();
    } else if (state.view === "classes") {
      viewEl.innerHTML = renderClasses();
    } else if (state.view === "lessons") {
      viewEl.innerHTML = renderLessons();
    } else if (state.view === "mocks") {
      viewEl.innerHTML = renderMocksForLesson();
    } else {
      viewEl.innerHTML = renderPapers();
    }
    renderCrumbs();
  }

  /* ------------------------------------------------------------ navigation */

  var LEVELS = { papers: 0, subjects: 1, classes: 2, lessons: 3, mocks: 4, all: 0 };

  function navigate(next) {
    next = next || {};
    if (next.view) state.view = next.view;
    var level = LEVELS[state.view] === undefined ? 0 : LEVELS[state.view];
    // Drilling into a level drops everything below it, so a stale class or
    // lesson from the previous branch can never leak into the new one.
    if (level < 1) state.paperId = null;
    if (level < 2) state.subjectId = null;
    if (level < 3) state.classId = null;
    if (level < 4) state.lessonId = null;
    if (next.paperId !== undefined) state.paperId = next.paperId;
    if (next.subjectId !== undefined) state.subjectId = next.subjectId;
    if (next.classId !== undefined) state.classId = next.classId;
    if (next.lessonId !== undefined) state.lessonId = next.lessonId;
    render();
    window.scrollTo(0, 0);
  }

  function onViewClick(event) {
    var trigger = event.target.closest("[data-go]");
    if (!trigger) return;
    var go = trigger.getAttribute("data-go");
    var id = trigger.getAttribute("data-id") || "";
    if (go === "home") navigate({ view: "papers" });
    else if (go === "all") navigate({ view: "all" });
    else if (go === "paper") navigate({ view: "subjects", paperId: id });
    else if (go === "subject") navigate({ view: "classes", subjectId: id });
    else if (go === "class") navigate({ view: "lessons", classId: id });
    else if (go === "lesson") navigate({ view: "mocks", lessonId: id });
  }

  /* ------------------------------------------------------------- install */

  function showInstallHelp() {
    var sheet = $("installSheet");
    sheet.hidden = false;
    $("installSheetClose").focus();
  }

  function setupInstall() {
    var button = $("installBtn");
    var standalone = window.matchMedia &&
      (window.matchMedia("(display-mode: standalone)").matches ||
        window.navigator.standalone === true);
    if (standalone) return;
    button.hidden = false;
    button.textContent = "Install";
    window.addEventListener("beforeinstallprompt", function (event) {
      event.preventDefault();
      deferredPrompt = event;
      button.hidden = false;
      button.textContent = "Install app";
    });
    button.addEventListener("click", function () {
      if (!deferredPrompt) {
        showInstallHelp();
        return;
      }
      deferredPrompt.prompt();
      deferredPrompt.userChoice.then(function () {
        deferredPrompt = null;
        button.hidden = true;
      });
    });
    $("installSheetClose").addEventListener("click", function () {
      $("installSheet").hidden = true;
    });
    $("installSheet").addEventListener("click", function (event) {
      if (event.target === $("installSheet")) $("installSheet").hidden = true;
    });
  }

  /* ------------------------------------------------------ offline worker */

  function askCacheStatus(worker) {
    return new Promise(function (resolve) {
      if (!worker || !window.MessageChannel) { resolve(null); return; }
      var channel = new MessageChannel();
      var timer = window.setTimeout(function () { resolve(null); }, 1500);
      channel.port1.onmessage = function (event) {
        window.clearTimeout(timer);
        resolve(event.data);
      };
      worker.postMessage({ type: "CACHE_STATUS" }, [channel.port2]);
    });
  }

  function setStatus(text) {
    $("statusChip").textContent = text;
  }

  function showBanner(id, text) {
    var banner = $(id);
    if (!text) {
      banner.hidden = true;
      banner.textContent = "";
      return;
    }
    banner.textContent = text;
    banner.hidden = false;
  }

  function reportCache(status) {
    if (!status) return;
    if (status.cached >= status.expected) {
      showBanner("offlineBanner", "");
      setStatus(state.catalog.counts.mocks + " mock papers · ready offline");
      return;
    }
    showBanner("offlineBanner",
      "Preparing offline library · " + status.cached + "/" + status.expected);
    setStatus("Caching for offline · " + status.cached + "/" + status.expected);
  }

  function setupWorker(registration) {
    var worker = registration.active || registration.waiting || registration.installing;
    if (!worker) return;
    askCacheStatus(worker).then(reportCache);
    var timer = window.setInterval(function () {
      var active = registration.active;
      if (!active) return;
      askCacheStatus(active).then(function (status) {
        reportCache(status);
        if (status && status.cached >= status.expected) {
          window.clearInterval(timer);
        }
      });
    }, 2000);
  }

  function showUpdate(worker) {
    var banner = $("updateBanner");
    banner.hidden = false;
    $("updateBtn").onclick = function () {
      reloading = true;
      worker.postMessage({ type: "SKIP_WAITING" });
    };
  }

  function setupServiceWorker() {
    if (!("serviceWorker" in navigator)) return;
    navigator.serviceWorker.register("sw.js").then(function (registration) {
      if (registration.waiting && navigator.serviceWorker.controller) {
        showUpdate(registration.waiting);
      }
      registration.addEventListener("updatefound", function () {
        var installing = registration.installing;
        if (!installing) return;
        installing.addEventListener("statechange", function () {
          if (installing.state === "installed" && navigator.serviceWorker.controller) {
            showUpdate(installing);
          }
        });
      });
      navigator.serviceWorker.addEventListener("controllerchange", function () {
        if (reloading) window.location.reload();
      });
      setupWorker(registration);
    }).catch(function () {
      /* Offline support stays unavailable; the library still works online. */
    });
  }

  /* ----------------------------------------------------------------- boot */

  function load() {
    if (window.location.protocol === "file:") {
      viewEl.innerHTML =
        '<div class="empty"><h3>Open this over a web address</h3>' +
        "<p>CTET Mock needs a web server so the papers can be cached for " +
        "offline use. Run the build command and serve the public folder.</p></div>";
      setStatus("Offline library");
      return Promise.resolve(null);
    }
    return fetch("catalog.json", { cache: "no-cache" })
      .then(function (response) {
        if (!response.ok) throw new Error("catalogue unavailable");
        return response.json();
      })
      .then(function (catalog) {
        state.catalog = catalog;
        render();
        setStatus(catalog.counts.mocks + " mock papers");
        return catalog;
      })
      .catch(function () {
        viewEl.innerHTML =
          '<div class="empty"><h3>The library is not built yet</h3>' +
          "<p>Run the build command to create the catalogue and the offline " +
          "cache, then reload.</p></div>";
        setStatus("Not built yet");
        return null;
      });
  }

  viewEl.addEventListener("click", onViewClick);
  $("crumbs").addEventListener("click", onViewClick);
  $("btnHome").addEventListener("click", function () {
    navigate({ view: "papers" });
  });
  $("searchInput").addEventListener("input", function (event) {
    state.query = event.target.value || "";
    if (state.query) {
      state.view = "all";
      render();
    } else {
      render();
    }
  });

  setupInstall();
  setupServiceWorker();
  load();

  window.CTETMock = { load: load, navigate: navigate, state: state };
})();
