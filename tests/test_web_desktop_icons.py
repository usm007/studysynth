"""Desktop fit, Material icon sprite, phone destination nav and reading size.

Static (stdlib only) checks against templates/web/app.template.html and the
generated module. These complement tests/test_web_visual.py, which covers the
broader visual system.
"""
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


def tpl_text():
    return TPL.read_text(encoding="utf-8")


def built_html():
    """Build the reference module through the real pipeline and return the text."""
    with tempfile.TemporaryDirectory() as tmp:
        out = str(Path(tmp, "quiz.html"))
        p = subprocess.run(
            [PY, "scripts/build_web.py", "examples/sample_package.json",
             "--out", out, "--title", "T"],
            capture_output=True, text=True, cwd=str(ROOT), timeout=300)
        if p.returncode != 0:
            raise AssertionError("build failed: " + p.stdout + p.stderr)
        return Path(out).read_text(encoding="utf-8")


def desktop_shell_block():
    m = re.search(r"@media \(min-width:861px\)\{\n(.*?)\n\}", tpl_text(), re.S)
    if not m:
        raise AssertionError("desktop shell media block not found")
    return m.group(1)


class TestMaterialIconSprite(unittest.TestCase):
    """Real Material Symbols, inlined - never an icon webfont or a CDN."""

    def test_sprite_is_inline_and_marked(self):
        t = tpl_text()
        self.assertIn("material-symbols-sprite:start", t)
        self.assertIn("material-symbols-sprite:end", t)
        self.assertIn('<svg class="sprite" aria-hidden="true" focusable="false">', t)

    def test_no_icon_webfont_or_remote_font(self):
        t = tpl_text()
        self.assertNotIn("@font-face", t)
        for bad in ["fonts.googleapis.com", "fonts.gstatic.com",
                    "Material+Symbols", "material-icons", "font-family:'Material"]:
            self.assertNotIn(bad, t, bad)

    def test_every_icon_reference_is_defined_and_used(self):
        html = built_html()
        defined = set(re.findall(r'<symbol id="(ic-[a-z0-9-]+)"', html))
        used = set(re.findall(r'<use href="#(ic-[a-z0-9-]+)"', html))
        dynamic = set("ic-" + n for n in re.findall(r'ICO\("([a-z0-9-]+)"', html))
        self.assertTrue(defined, "icon sprite is empty")
        self.assertEqual(sorted((used | dynamic) - defined), [],
                         "icon used but not defined")
        self.assertEqual(sorted(defined - used - dynamic), [],
                         "icon defined but never used")

    def test_symbols_carry_material_symbol_viewbox(self):
        views = re.findall(r'<symbol id="ic-[a-z0-9-]+"[^>]*viewBox="([^"]+)"',
                           built_html())
        self.assertGreaterEqual(len(views), 25, "expected a full icon set")
        self.assertEqual(set(views), {"0 -960 960 960"})

    def test_no_ascii_glyph_standins(self):
        t = tpl_text()
        for glyph in ["\u2605", "\u2715", "\u25be", "\u25b4", "\u2328",
                      "\u2713", "\u2192", "\u2190"]:
            self.assertEqual(t.count(glyph), 0, "glyph icon left: %r" % glyph)

    def test_decorative_icons_are_hidden_from_assistive_tech(self):
        t = tpl_text()
        inline = re.findall(r'<svg class="ic[^"]*"[^>]*>', t)
        self.assertGreater(len(inline), 20)
        for tag in inline:
            self.assertIn('aria-hidden="true"', tag, tag)

    def test_sprite_stays_small(self):
        html = built_html()
        i = html.find("material-symbols-sprite:start")
        j = html.find("material-symbols-sprite:end")
        self.assertGreater(j, i)
        self.assertLess(j - i, 16000, "inline sprite block unexpectedly large")


class TestDesktopFit(unittest.TestCase):
    """Desktop fills the window and the question sheet does not scroll the page."""

    def test_page_and_workspace_do_not_scroll(self):
        block = desktop_shell_block()
        self.assertIn(".workspace{overflow:hidden}", block)
        self.assertIn("#quizview,#qwork{min-height:0;overflow:hidden}", block)

    def test_question_flow_is_the_only_scroll_region(self):
        block = desktop_shell_block()
        m = re.search(r"\.q-flow\{([^}]*)\}", block)
        self.assertIsNotNone(m, ".q-flow rule missing from the desktop shell")
        decl = m.group(1)
        self.assertIn("overflow-y:auto", decl)
        self.assertIn("min-height:0", decl)
        self.assertIn("scrollbar-gutter:stable", decl)

    def test_revision_queue_cannot_squeeze_the_sheet(self):
        block = desktop_shell_block()
        self.assertIn("#revQueue{flex:0 0 auto}", block)
        self.assertIn("#revQueue:not(:empty){flex:1 1 auto", block)

    def test_action_bar_is_pinned_inside_the_sheet(self):
        self.assertIn(".actions{position:static;margin:0 -20px 0}",
                      desktop_shell_block())

    def test_full_width_is_used_at_desktop_sizes(self):
        t = tpl_text()
        self.assertIn("--max:1800px", t)
        self.assertIn("--measure:1180px", t)

    def test_short_window_compaction_tiers(self):
        t = tpl_text()
        self.assertIn("@media (min-width:861px) and (max-height:900px)", t)
        self.assertIn("@media (min-width:861px) and (max-height:700px)", t)

    def test_two_column_option_grid_for_short_answers(self):
        t = tpl_text()
        self.assertIn(".opts.opts-grid{display:grid;grid-template-columns:1fr 1fr",
                      t)
        self.assertIn('form.classList.toggle("opts-grid", isCombo);', t)
        m = re.search(r"var isCombo\s*=\s*(.*?);", t, re.S)
        self.assertIsNotNone(m, "opts-grid decision missing")
        self.assertIn("sp.stmts.length", m.group(1))

    def test_progress_report_uses_columns_on_wide_desktop(self):
        t = tpl_text()
        m = re.search(r"@media \(min-width:1024px\)\{\n(.*?)\n\}", t, re.S)
        self.assertIsNotNone(m, "wide desktop report block missing")
        self.assertIn(".an-cols{display:grid;grid-template-columns:1fr 1fr",
                      m.group(1))

    def test_match_columns_stack_on_phones(self):
        self.assertIn("@media (max-width:620px){.match-cols{grid-template-columns:1fr",
                      tpl_text())


class TestPhoneDestinationNav(unittest.TestCase):
    """Phones get a bottom destination bar; desktop keeps the rail."""

    def test_bottom_nav_destinations(self):
        t = tpl_text()
        self.assertIn('id="bottomnav"', t)
        nav = t[t.find('id="bottomnav"'):]
        nav = nav[:nav.find("</nav>")]
        for value, label in (("practice", "Study"), ("test", "Test"),
                             ("revision", "Revision")):
            self.assertIn('data-bnav="%s"' % value, nav)
            self.assertIn(">%s<" % label, nav)
        self.assertIn('id="bnavAnalytics"', nav)
        self.assertIn(">Progress<", nav)

    def test_bottom_nav_reuses_existing_navigation(self):
        t = tpl_text()
        self.assertIn('document.querySelectorAll("#bottomnav .bnav-item[data-bnav]")',
                      t)
        self.assertIn("setMode(b.getAttribute(\"data-bnav\"))", t)
        m = re.search(r'getElementById\("bnavAnalytics"\)\.onclick=([^;]+);', t)
        self.assertIsNotNone(m, "Progress destination is not wired")
        self.assertIn("showAnalytics", m.group(1))

    def test_phone_action_bar_delegates_to_desktop_controls(self):
        t = tpl_text()
        for eid in ["mPrev", "mMark", "mSubmit", "mNext"]:
            self.assertIn('id="%s"' % eid, t, eid)
        self.assertIn('document.getElementById("markbtn").click()', t)
        self.assertIn('document.getElementById("mSubmit").onclick=submit', t)
        self.assertIn('document.getElementById("mPrev").onclick=goPrev', t)
        self.assertIn('document.getElementById("mNext").onclick=goNext', t)

    def test_phone_bar_replaces_the_desktop_row(self):
        t = tpl_text()
        self.assertIn(".mobilebar{display:none", t)
        self.assertIn(".desktop-actions{display:none!important}", t)
        self.assertGreaterEqual(t.count(".mobilebar{display:flex}"), 1)

    def test_phone_bar_and_nav_clear_the_safe_area(self):
        t = tpl_text()
        self.assertIn("env(safe-area-inset-bottom)", t)


class TestReadingSizeControl(unittest.TestCase):
    def test_reading_size_controls_exist(self):
        t = tpl_text()
        for eid, label in (("readS", "Smaller question text"),
                           ("readM", "Default question text"),
                           ("readL", "Larger question text")):
            m = re.search(r'id="%s"[^>]*' % eid, t)
            self.assertIsNotNone(m, eid)
            self.assertIn('aria-label="%s"' % label, m.group(0))

    def test_scale_variable_drives_reading_text(self):
        t = tpl_text()
        self.assertIn("--read:1", t)
        self.assertIn('html[data-read="s"]{--read:.925}', t)
        self.assertIn('html[data-read="l"]{--read:1.15}', t)
        self.assertIn("font-size:calc(15px*var(--read))", t)
        self.assertIn("calc(20px,2vw,24px)*var(--read)", t.replace("clamp(", ""))

    def test_choice_is_remembered_per_module(self):
        t = tpl_text()
        self.assertIn('var readKey = "quiz_readscale_"', t)
        self.assertIn(".replace(/\\W+/g,\"_\").slice(0,40)", t)
        self.assertIn("localStorage", t)


class TestDashboardTheme(unittest.TestCase):
    """The library index shares the study module's warm paper + forest identity."""

    @classmethod
    def setUpClass(cls):
        cls.src = (ROOT / "scripts" / "dashboard.py").read_text(encoding="utf-8")

    def test_warm_paper_forest_tokens(self):
        for token in ["--bg: #f3f0e6", "--surface: #fffefa", "--ink: #1f2620",
                      "--accent: #315d49", "--accent-2: #244b3a",
                      "--accent-soft: #dce9df"]:
            self.assertIn(token, self.src, token)

    def test_light_first_not_dark_slate(self):
        self.assertIn("color: var(--ink);", self.src)
        self.assertIn("background: var(--bg);", self.src)

    def test_launch_button_carries_a_material_icon_not_a_glyph(self):
        self.assertIn('<svg class="ic" aria-hidden="true"', self.src)
        self.assertIn(".btn-launch .ic", self.src)
        for glyph in ["\u2192", "\u2190", "\u2605", "\u2713", "\u2715",
                      "\u25be", "\u25b4", "\u2328"]:
            self.assertEqual(self.src.count(glyph), 0,
                             "glyph stand-in left in the dashboard: %r" % glyph)

    def test_library_affordances_preserved(self):
        for needle in ["badge-module", "badge-status", "btn-launch",
                       "empty-state", "moduleCount", "STUDY_SYNTH_REGISTRY_START",
                       "STUDY_SYNTH_REGISTRY_END"]:
            self.assertIn(needle, self.src, needle)


if __name__ == "__main__":
    unittest.main()
