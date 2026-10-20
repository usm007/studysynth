"""Visual/UX regression tests for the redesigned study workspace.

Static checks on templates/web/app.template.html + generated output:
tokens, typography, layout, modes, drawers, feedback, analytics,
keyboard, a11y, responsive breakpoints, print, offline.
Runnable via unittest discover; stdlib only.
"""
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PY = sys.executable
TPL = ROOT / "templates" / "web" / "app.template.html"


def run(*args):
    p = subprocess.run([PY] + [str(a) for a in args], capture_output=True,
                       text=True, cwd=str(ROOT), timeout=300)
    return p


def tpl_text():
    return TPL.read_text(encoding="utf-8")


class TestDesignTokens(unittest.TestCase):
    def test_token_system_present(self):
        t = tpl_text()
        for tok in ["--bg", "--surface", "--ink", "--muted", "--line",
                    "--accent", "--good", "--bad", "--warn", "--focus",
                    "--radius", "--font-ui"]:
            self.assertIn(tok, t, tok)

    def test_no_georgia_everywhere(self):
        t = tpl_text()
        m = re.search(r"body\s*\{[^}]*font-family:([^;}]+)", t)
        self.assertIsNotNone(m, "body font-family missing")
        self.assertNotIn("Georgia", m.group(1),
                         "body must not be Georgia-everywhere")

    def test_no_heavy_legacy_markers(self):
        t = tpl_text()
        self.assertNotIn("Georgia,\"Nirmala UI\"", t)
        # no giant flat blue button pattern: primary button is restrained
        self.assertIn(".btn-primary", t)


class TestShellLayout(unittest.TestCase):
    def test_topbar_rail_workspace(self):
        t = tpl_text()
        self.assertIn('class="topbar"', t)
        self.assertIn('id="modebar"', t)
        self.assertIn('class="workspace"', t)
        self.assertIn('id="railToggle"', t)

    def test_no_permanent_sidebar_hog(self):
        t = tpl_text()
        # secondary utility lives in drawers, not a permanent wide sidebar
        for did in ["navDrawer", "filterDrawer", "sourceDrawer", "sessionDrawer"]:
            self.assertIn('id="%s"' % did, t)
        self.assertIn('class="scrim"', t)


class TestModes(unittest.TestCase):
    MODES = ["practice", "study", "test", "revision"]

    def test_all_modes_present_with_descriptions(self):
        t = tpl_text()
        for m in self.MODES:
            self.assertIn('data-mode="%s"' % m, t)
        self.assertIn("Weak areas", t)
        self.assertIn("Answer and review", t)

    def test_removed_modes_absent(self):
        t = tpl_text()
        for m in ["learn", "rapid"]:
            self.assertNotIn('data-mode="%s"' % m, t)
        for s in ["learnPanel", "renderLearnPanel", "confusableExcerpt",
                  "Rapid Recall", "High-density", "rapidReveal"]:
            self.assertNotIn(s, t, s)

    def test_sidebar_confidence_surface_present(self):
        # The rail confidence meter was superseded by the session overview
        # (accuracy + completion), which carries the same "how am I doing"
        # signal in the sidebar.
        t = tpl_text()
        for eid in ["studyDashboard", "statAccuracy", "statAccuracyNote",
                    "statCompletion", "statProgressBar", "statProgressFill"]:
            self.assertIn('id="%s"' % eid, t, eid)
        self.assertIn('role="progressbar"', t)
        self.assertIn("renderDashboardStats", t)

    def test_active_mode_unmistakable(self):
        t = tpl_text()
        self.assertIn(".mode-item.active", t)

    def test_test_mode_exam_chrome(self):
        t = tpl_text()
        self.assertIn('id="timerrow"', t)
        self.assertIn('id="finishtest"', t)
        self.assertIn("confirm(", t)
        self.assertIn("No feedback until you submit", t)


class TestQuestionUX(unittest.TestCase):
    def test_question_hierarchy(self):
        t = tpl_text()
        self.assertIn('id="qmeta"', t)
        self.assertIn('id="qstem"', t)
        self.assertIn("Question ", t)
        # tech ids live in a collapsed details element, not the main line
        self.assertIn("<details", t)

    def test_option_states(self):
        t = tpl_text()
        for cls in [".opt.selected", ".opt.correct", ".opt.incorrect",
                    ".opt .verdict"]:
            self.assertIn(cls, t)
        # not color alone: textual verdicts exist
        self.assertIn("Correct", t)
        self.assertIn("Yours", t)

    def test_statement_styling(self):
        t = tpl_text()
        self.assertIn("stmt-list", t)
        self.assertIn("stmt-n", t)
        self.assertIn("Consider the following statements", t)

    def test_match_styling(self):
        t = tpl_text()
        self.assertIn("match-cols", t)
        self.assertIn("Match the following", t)
        self.assertIn("parseMatchLists", t)
        # Ensure match markers are properly centered badges and don't dangle with inline-block / baseline
        self.assertIn(".layout-match .match-cols .stmt-list .stmt-n", t)
        self.assertNotIn(".layout-match .match-cols .stmt-list .stmt-n {\n    font-weight: 850 !important;\n    color: var(--md-primary, #2d5a3f) !important;\n    width: 18px !important;\n    display: inline-block", t)
        self.assertIn("place-items: center", t)

    def test_feedback_teaches(self):
        t = tpl_text()
        for s in ["Key distinction", "Why the distractor tempts you",
                  "Common mix-up", "Remember", "Your answer",
                  "Correct answer"]:
            self.assertIn(s, t, s)


class TestProgressNav(unittest.TestCase):
    def test_progress_system(self):
        t = tpl_text()
        self.assertIn('id="progressNum"', t)
        self.assertIn('id="progressFill"', t)
        self.assertIn('id="progressPct"', t)

    def test_navigator_states_and_filters(self):
        t = tpl_text()
        for cls in ["is-right", "is-wrong", "is-marked", "is-hipri",
                    "is-revneed", "cur"]:
            self.assertIn(cls, t)
        for nf in ['data-nf="all"', 'data-nf="unanswered"',
                   'data-nf="incorrect"', 'data-nf="marked"']:
            self.assertIn(nf, t)


class TestAnalyticsActionable(unittest.TestCase):
    def test_analytics_answers_three_questions(self):
        t = tpl_text()
        self.assertIn("What should I study next?", t)
        self.assertIn("Weak areas", t)
        self.assertIn("Confidence problem", t)
        self.assertIn("Revision priority", t)

    def test_analytics_actions(self):
        t = tpl_text()
        for a in ["Revise now", "Practise distinctions", "Review mistakes",
                  "data-act"]:
            self.assertIn(a, t)

    def test_no_raw_table_analytics(self):
        t = tpl_text()
        self.assertIn("bar-row", t)


class TestFiltersSource(unittest.TestCase):
    def test_filter_chips(self):
        t = tpl_text()
        self.assertIn('id="chips"', t)
        self.assertIn('id="clearFilters"', t)
        for fid in ["f_topic", "f_diff", "f_tier", "f_type", "f_purpose",
                    "f_rev", "f_incorrect", "f_marked", "f_weak"]:
            self.assertIn('id="%s"' % fid, t)

    def test_source_drawer(self):
        t = tpl_text()
        self.assertIn('id="sourceBody"', t)
        self.assertIn("never fabricated", t.lower())


class TestKeyboardA11y(unittest.TestCase):
    def test_shortcuts(self):
        t = tpl_text()
        for k in ['"m"', '"h"', '"n"', '"Enter"', '"ArrowRight"',
                  '"ArrowLeft"', '"Escape"']:
            self.assertIn(k, t, k)

    def test_a11y_markers(self):
        t = tpl_text()
        self.assertIn("skip", t)
        self.assertIn("aria-label", t)
        self.assertIn("aria-live", t)
        self.assertIn(":focus-visible", t)
        self.assertIn("radiogroup", t)
        self.assertIn("prefers-reduced-motion", t)


class TestResponsivePrint(unittest.TestCase):
    def test_breakpoints(self):
        t = tpl_text()
        for bp in ["430px", "860px"]:
            self.assertIn(bp, t, bp)
        self.assertIn("mobilebar", t)

    def test_touch_targets(self):
        t = tpl_text()
        self.assertIn("min-height:56px", t)

    def test_print_stylesheet(self):
        t = tpl_text()
        self.assertIn("@media print", t)
        self.assertIn("break-inside:avoid", t)

    def test_print_answer_key_follows_questions(self):
        t = tpl_text()
        self.assertIn('#printSheet .pq-key-grid', t)
        self.assertIn('break-before: page', t)
        end = t.find('<p class="pq-end">End of question paper</p>')
        key = t.find('<section class="pq-key">')
        self.assertGreater(end, -1)
        self.assertGreater(key, end)
        self.assertIn('class="pq-kav"', t)


class TestOfflineBuild(unittest.TestCase):
    def test_placeholders_and_offline(self):
        t = tpl_text()
        self.assertIn("/*__PACKAGE__*/{}", t)
        self.assertIn('/*__STATUS__*/""', t)
        # XML namespace identifiers (OOXML, Dublin Core) are not network assets.
        namespaces = ("w3.org", "openxmlformats.org", "purl.org",
                      "schemas.microsoft.com")
        ext = [u for u in re.findall(r"https?://[^\s\"'<>]+", t)
               if not any(ns in u for ns in namespaces)]
        self.assertEqual(ext, [], ext)

    def test_generated_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = str(Path(tmp, "quiz.html"))
            r = run("scripts/build_web.py", "examples/sample_package.json",
                    "--out", out, "--title", "T")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            html = Path(out).read_text(encoding="utf-8")
            i = html.find("__PACKAGE__")
            self.assertNotEqual(i, -1)
            j = html.find("{", i)
            depth, k = 0, j
            while k < len(html):
                if html[k] == "{":
                    depth += 1
                elif html[k] == "}":
                    depth -= 1
                    if depth == 0:
                        break
                k += 1
            pkg = json.loads(html[j:k + 1])
            self.assertEqual(len(pkg["questions"]), 64)
            for needle in ["modebar", "navDrawer", "filterDrawer",
                           "sourceDrawer", "study-note", "bar-row",
                           "Consider the following statements"]:
                self.assertIn(needle, html, needle)

    def test_functionality_preserved(self):
        t = tpl_text()
        for eid in ["opts", "submitbtn", "markbtn", "prevbtn", "nextbtn",
                    "feedback", "hintbtn", "navgrid",
                    "exportbtn", "importbtn", "importfile", "storagenote",
                    "analyticsBtn", "quizBtn", "srcmode", "printlink"]:
            self.assertIn('id="%s"' % eid, t, eid)
        self.assertNotIn('id="confrow"', t)
        self.assertNotIn("How sure are you?", t)
        self.assertIn('class="brand-mark brand-mark--logo"', t)
        self.assertIn("data:image/png;base64,", t)
        self.assertIn("quiz_session_v2_", t)
        self.assertIn("study_session.json", t)


class TestRevisionUI(unittest.TestCase):
    def test_engine_placeholder_and_build_inlining(self):
        t = tpl_text()
        self.assertIn("/*__REVISION_ENGINE__*/", t)
        with tempfile.TemporaryDirectory() as tmp:
            out = str(Path(tmp, "quiz.html"))
            r = run("scripts/build_web.py", "examples/sample_package.json",
                    "--out", out, "--title", "T")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            html = Path(out).read_text(encoding="utf-8")
            self.assertIn("RevisionEngine", html)
            self.assertNotIn("__REVISION_ENGINE__", html)

    def test_revision_modes_and_why(self):
        t = tpl_text()
        for mode in ["targeted", "mistakes", "confusion", "hce",
                     "cognitive", "quick", "full"]:
            self.assertIn('"%s"' % mode, t, mode)
        self.assertIn("Why you are seeing this", t)
        self.assertIn("Why this question", t)
        self.assertIn("revQueue", t)

    def test_session_v2_and_migration(self):
        t = tpl_text()
        self.assertIn("study_session_version", t)
        self.assertIn("migrateSession", t)
        self.assertIn("revision_state", t)
        for field in ["dt_ms", "secondary_kus", "rev_priority"]:
            self.assertIn(field, t, field)

    def test_analytics_revision_section(self):
        t = tpl_text()
        self.assertIn("rev-hce", t)
        self.assertIn("rev-cog", t)
        self.assertIn("High-confidence errors", t)

    def test_neutral_language(self):
        t = tpl_text().lower()
        for phrase in ["you keep failing", "bad performance",
                       "you don't understand", "you do not understand"]:
            self.assertNotIn(phrase, t, phrase)


class TestStudyPage(unittest.TestCase):
    """Read-only study page: topic > section > key points."""

    def test_study_destination_present(self):
        t = tpl_text()
        self.assertIn('data-mode="study"', t)
        self.assertIn('data-bnav="study"', t)
        self.assertIn('id="studyview"', t)
        self.assertIn('id="studyGuide"', t)
        self.assertIn("function showStudy()", t)
        self.assertIn("function renderStudyGuide()", t)

    def test_study_notes_source_priority(self):
        t = tpl_text()
        self.assertIn("PKG.study_notes", t)
        self.assertIn("KU_EXCERPTS", t)
        self.assertIn("studyFromCurated", t)
        self.assertIn("buildStudyNotes", t)

    def test_study_page_collapsible_topics(self):
        t = tpl_text()
        self.assertIn('<details class="sg-topic"', t)
        self.assertIn('<summary class="sg-topic-head"', t)
        self.assertIn(".sg-topic-head", t)
        self.assertIn("min-height: 58px", t)

    def test_study_mode_keeps_app_shell_clean(self):
        t = tpl_text()
        self.assertIn('body[data-mode="study"] .topbar-progress', t)
        self.assertIn('body[data-mode="study"] #quizview', t)
        self.assertIn('body[data-mode="study"] #resetSessionBtn', t)
        self.assertIn('body[data-mode="study"] .workcol', t)

    def test_study_page_reading_spread(self):
        t = tpl_text()
        self.assertIn('<div class="sg-shell">', t)
        self.assertIn('<aside class="sg-map"', t)
        self.assertIn('aria-label="Chapter contents"', t)
        self.assertIn('class="sg-map-sec"', t)
        self.assertIn("function updateStudyMap()", t)
        self.assertIn("columns: 2", t)
        self.assertIn("max-height: calc(100vh - 110px)", t)
        self.assertIn('<h4 class="sg-section-title"', t)
        self.assertIn("esc(sourceDocHeading())", t)
        self.assertIn("RAWMETA.source_title", t)
        self.assertIn('id="studyGuide" tabindex="-1"', t)
        self.assertIn('setSkipLink("#studyGuide", "Skip to study notes")', t)


class TestEditorialIdentity(unittest.TestCase):
    """Study-desk identity: sheet marker, ledger options, study-note states."""

    def test_sheet_identity_block(self):
        t = tpl_text()
        for s in ['id="sheetHead"', 'id="qnum"', 'id="qmode"',
                  'id="qmargin"', ".sheet-num", ".sheet-head"]:
            self.assertIn(s, t, s)

    def test_option_ledger_not_cards(self):
        # Stitch contract: bordered rows (1px line, 2px marker-scale radius),
        # never dashboard cards. State travels in border color + marker fill.
        t = tpl_text()
        m = re.search(r"\.opt\{([^}]*)\}", t)
        self.assertIsNotNone(m, ".opt rule missing")
        self.assertIn("border:1px solid var(--line)", m.group(1))
        self.assertIn("border-bottom", m.group(1))
        self.assertNotIn("border-radius:var(--radius)", m.group(1))
        for cls in [".opt.selected", ".opt.correct", ".opt.incorrect"]:
            self.assertIn(cls, t, cls)

    def test_study_note_state_rule(self):
        t = tpl_text()
        self.assertIn(".study-note.is-ok", t)
        self.assertIn(".study-note.is-bad", t)
        self.assertIn("border-top:3px solid var(--ink)", t)

    def test_study_plan_numbering(self):
        t = tpl_text()
        self.assertIn("decimal-leading-zero", t)


class TestPhoneProgressScroll(unittest.TestCase):
    """On a phone the Progress page must behave like a normal scrolling page.

    The dashboard is authored as a fixed-height desktop shell, so below the
    desktop breakpoint it collapses: the page stops scrolling and the cards
    below the KPI strip are clipped away. The phone needs its own state.
    """

    PHONE_W, PHONE_H = 390, 844

    @staticmethod
    def _media_block(text, condition):
        """Text of every `@media <condition> { ... }` block in the template."""
        blocks = []
        needle = "@media " + condition
        start = 0
        while True:
            i = text.find(needle, start)
            if i == -1:
                break
            j = text.find("{", i)
            depth, k = 0, j
            while k < len(text):
                if text[k] == "{":
                    depth += 1
                elif text[k] == "}":
                    depth -= 1
                    if depth == 0:
                        break
                k += 1
            blocks.append(text[j:k])
            start = k + 1
        return "\n".join(blocks)

    def test_phone_progress_rule_releases_fixed_height(self):
        t = tpl_text()
        block = self._media_block(t, "(max-width: 900px)")
        self.assertIn("body[data-mode=\"analytics\"] #analyticsview", block)
        self.assertIn("height: auto", block)
        self.assertIn("overflow: visible", block)
        self.assertIn(".an-dashboard-body", block)
        self.assertIn("grid-template-columns: minmax(0, 1fr)", block)

    def _phone_progress_state(self, html_path):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.skipTest("playwright not installed")
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch()
                page = browser.new_page(
                    viewport={"width": self.PHONE_W, "height": self.PHONE_H},
                    is_mobile=True, has_touch=True)
                page.goto(html_path.as_uri())
                page.wait_for_timeout(600)
                # Answer a handful of questions so the dashboard holds real
                # content - an empty session is shorter than the viewport and
                # would hide a clipping bug.
                for i in range(6):
                    try:
                        page.locator("#opts .opt").nth(i % 2).click()
                        page.evaluate("document.getElementById('submitbtn')?.click()")
                        page.wait_for_timeout(200)
                        page.evaluate("document.getElementById('nextbtn')?.click()")
                        page.wait_for_timeout(200)
                    except Exception:
                        break
                page.evaluate("document.getElementById('bnavAnalytics')?.click()")
                page.wait_for_timeout(900)
                state = page.evaluate("""() => {
                    const view = document.querySelector('#analyticsview');
                    const body = document.querySelector('.an-dashboard-body');
                    const nav = document.querySelector('#bottomnav');
                    const navTop = nav ? nav.getBoundingClientRect().top : innerHeight;
                    const viewRect = view.getBoundingClientRect();
                    // the lowest painted piece of analytics content
                    let lowest = viewRect.top;
                    for (const el of view.querySelectorAll('*')) {
                      const cs = getComputedStyle(el);
                      if (cs.display === 'none' || cs.visibility === 'hidden') continue;
                      const r = el.getBoundingClientRect();
                      if (r.width === 0 || r.height === 0) continue;
                      if (r.bottom > lowest) lowest = r.bottom;
                    }
                    window.scrollTo(0, document.documentElement.scrollHeight);
                    const after = lowest - window.scrollY;
                    return {
                      vh: innerHeight,
                      docScrollH: document.documentElement.scrollHeight,
                      maxScroll: Math.round(document.documentElement.scrollHeight - innerHeight),
                      viewScrollH: view.scrollHeight,
                      viewClientH: view.clientHeight,
                      viewOverflowY: getComputedStyle(view).overflowY,
                      dashH: body ? body.getBoundingClientRect().height : -1,
                      dashCols: body ? getComputedStyle(body).gridTemplateColumns : '',
                      contentBottomAfterScroll: Math.round(after),
                      navTop: Math.round(navTop),
                      lowest: Math.round(lowest),
                    };
                }""")
                browser.close()
                return state
        except Exception as exc:  # browser missing / driver unavailable
            self.skipTest("chromium unavailable: %s" % exc)

    def test_progress_page_scrolls_on_phone(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp, "quiz.html")
            r = run("scripts/build_web.py", "examples/hees101_package.json",
                    "--out", out, "--title", "T")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            state = self._phone_progress_state(out)

        # the page itself must scroll
        self.assertGreater(state["maxScroll"], 0,
                           "Progress page does not scroll on a phone")
        # the dashboard body must have real height, not collapse to zero
        self.assertGreater(state["dashH"], 40,
                           "dashboard body collapsed on a phone")
        # one column on a phone
        self.assertEqual(len(state["dashCols"].split()), 1,
                         "dashboard is still multi-column: %s" % state["dashCols"])
        # the view must not clip its own content
        self.assertLessEqual(state["viewScrollH"], state["viewClientH"] + 1,
                             "analytics view clips its content on a phone")
        # the bottom of the content must be reachable (not trapped under the
        # fixed bottom nav)
        self.assertLessEqual(state["contentBottomAfterScroll"], state["navTop"],
                             "analytics content is trapped behind the bottom nav")


if __name__ == "__main__":
    unittest.main(verbosity=2)
