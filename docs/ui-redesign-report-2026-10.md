# StudySynth UI redesign — engineering report (2026-10-18)

Two deliverables were re-skinned and re-fitted against the same product
structure:

- the generated study module (`templates/web/app.template.html` → any
  `<title>.html` produced by `scripts/build_web.py`), and
- the master library page (`scripts/dashboard.py` → `index.html`).

Nothing in the question engine, scoring, session persistence, revision engine,
or the embedding pipeline was changed.

---

## 1. What you can do now

- **Open a module and study without scrolling on a desktop.** The question
  sheet fills the window: the question, its statements/options, the confidence
  chips and the action row are all on screen at once. The page itself never
  scrolls; if one question is genuinely taller than the window, only the
  question area scrolls, and the action row plus the confidence row stay put.
- **See real Material icons everywhere.** Menu, search, question grid, filters,
  overflow, the four destinations, previous/next, bookmark, print, keyboard,
  reading size, verdicts and disclosure chevrons are Material Symbols Rounded
  glyphs drawn from an inlined sprite. No emoji, no `★`, no `✕`, no `▾`, no
  `⌨`, no tofu box. Icons that belong in a pair (outlined/filled) swap when
  their item becomes active.
- **Use the full width.** Short answer codes (`1 and 2 only`, `c-d-e-a-b`)
  are laid out two per row, match-the-following uses a wider two-column pair,
  and the Progress report reads as two columns on a wide window.
- **Navigate by destination on a phone.** Study · Test · Revision · Progress
  sit in a bottom bar with filled icons on the active tab, plus a phone action
  bar (previous · mark · submit · next).
- **Choose a reading size** (Small / Default / Large) that is remembered per
  module.
- **Use the master library** in the same warm-paper look, with the module
  count, status badges and launch buttons unchanged.

Generate or refresh a module (from the repo root):

```
python scripts/build_web.py examples/quiz_package.json --out examples/quiz.html --title StudySynth
```

The result is one self-contained `file://` document — no server, no network
call, no build step at open time.

---

## 2. Files changed

| File | Change |
| --- | --- |
| `templates/web/app.template.html` | Design tokens, Material icon sprite, desktop app shell, compaction tiers, two-column option grid, phone destination bar, reading-size control, analytics columns |
| `scripts/dashboard.py` | Library page re-skinned to the same tokens; module count fixed; launch button now carries a Material arrow icon |
| `examples/quiz.html` | Rebuilt from the new template (embedded package byte-identical) |
| `tests/test_web_desktop_icons.py` | **New** — 28 tests for icons, desktop fit, phone nav, reading size, dashboard theme |
| `DESIGN.md` | Current direction + reason log R-32…R-42 |
| `docs/ui-redesign-spec-2026-10.md` | Phase-B specification (unchanged) |
| `build/ui-verify/` (untracked) | Verification harnesses, stress fixtures, screenshots |

---

## 3. Design tokens

| Token | Value | Use |
| --- | --- | --- |
| `--bg` | `#f3f0e6` | desk / page canvas |
| `--surface` / `--surface-2` / `--surface-3` | `#fffefa` / `#f6f4eb` / `#ebe8dd` | sheet, wells, tracks |
| `--ink` / `--ink-2` / `--muted` | `#1f2620` / `#414a44` / `#5f6860` | text |
| `--line` / `--line-soft` / `--line-strong` | `#d8dcd2` / `#e7e9df` / `#a2a9a0` | rules |
| `--accent` / `--accent-2` / `--accent-soft` | `#315d49` / `#244b3a` / `#dce9df` | action + structure |
| `--good` / `--bad` / `--warn` | `#205f35` / `#a63028` / `#8a5b00` | right / wrong / priority |
| `--focus` | `#244b3a` | focus ring |
| `--radius` / `--radius-s` | `16px` / `10px` | cards / controls |
| `--read` | `1` (`.925` / `1.15`) | reading-size scale |
| `--max` / `--measure` | `1240px` / `1024px` — **`1800px` / `1180px` on desktop** | width caps |

Contrast (measured): ink 15.3:1, muted 5.7:1, accent 7.5:1, good 7.6:1,
bad 6.8:1, warn 5.2:1 — AA for body text. `--faint` (2.98:1) is decorative
only.

Typography: system stacks only; serif for brand, question stem, sheet number
and analytic figures; system sans for UI, meta and body. No webfonts.

---

## 4. Icons

- 29 Material Symbols Rounded symbols are inlined as a single `<symbol>`
  sprite (`viewBox="0 -960 960 960"`) in the template. There is no icon font,
  no `@font-face`, no CDN, and no remote request — verified on the built file.
- Usage is `<svg class="ic" aria-hidden="true"><use href="#ic-name"/></svg>`;
  the JS helper `ICO(name)` builds the same markup.
- Outlined/filled pairs swap on `.is-on` / `.active` / `[aria-selected="true"]`
  (rail and bottom-nav destinations, mark-for-review).
- Every icon is `aria-hidden="true"`; every control keeps a visible label or an
  `aria-label`, so nothing depends on the glyph.
- Replaced stand-ins: `★` → bookmark, `✓`/`✕` → check/close, `▾`/`▴` →
  expand chevrons, `⌨` → keyboard, `→`/`←` → chevrons, `+`/`–` → add/remove.

---

## 5. Behaviour by form factor

| | Phone (≤480) | Small tablet (481–767) | Tablet (768–1023) | Desktop (≥1024) |
| --- | --- | --- | --- | --- |
| Navigation | bottom destination bar + rail drawer | same | same | fixed rail + workspace |
| Action row | phone bar, fixed above the nav | phone bar | phone bar | in-sheet row, pinned at the bottom |
| Page scroll | scrolls naturally | scrolls | scrolls | **never** |
| Sheet scroll | n/a | n/a | n/a | only the question area, only if needed |
| Options | one per row, ≥56px | one per row | one per row | two per row when all answers are ≤16 characters |
| Match columns | stacked (≤620px) | stacked | two columns | two columns, wider right column |
| Progress report | single stack | single stack | single stack | two columns ≥1024px |
| Confidence chips | own row | own row | own row | inline strip above the action row |
| Safe areas | `env(safe-area-inset-bottom)` respected | yes | yes | n/a |

Desktop height tiers: ≤900px tightens metrics; ≤700px additionally drops the
redundant mode banner and the instruction line, tightens statements, options,
confidence chips and the action row, and scales reading text to `.94`.

---

## 6. Verification (commands and actual results)

All commands run from the repo root on Windows.

| Command | Result |
| --- | --- |
| `python -m unittest tests.test_web_visual tests.test_dashboard tests.test_web_desktop_icons` | **69 tests, OK** (39 + 2 + 28) |
| `python tests/run_all.py` | **342 tests run, 0 failures, 0 errors, 0 skipped — `RESULT: PASS`** (314 before this work; +28 new) |
| `python scripts/build_web.py examples/quiz_package.json --out examples/quiz.html --title StudySynth` | `OK: wrote examples\quiz.html` |
| `python scripts/release_gate.py` | **OVERALL V1.0 RELEASE STATUS: PASS** (7/7 checks: full suite, schemas, node parity, quality benchmark, end-to-end pipeline, delivery artifacts, documentation) |

Measured behaviour of the built module (`build/ui-verify/` harnesses):

- **Question sheet, all 64 questions, `.q-flow` scroll:** 0px at
  1024×600, 1024×768, 1280×620, 1280×800, 1366×768, 1440×900, 1600×900 and
  1920×1080. Nothing clipped or off-screen at any of them.
- **Destinations:** 13 viewports × 4 destinations (Study, Test, Revision,
  Progress) — 0 failures. On desktop the document never scrolls; no viewport
  produced horizontal overflow; on phones the bottom bar is present in all four.
- **Progress report:** fits with no scrolling at every desktop size tested
  (1024×600 leaves 31px). The Revision landing fits at every size, empty and
  with real answer history.
- **Answered state:** the correct option and a wrong pick are marked with tint,
  border and a text badge (`CORRECT` / `YOURS`), plus the study note — in both
  the one- and two-column option layouts.
- **Stress fixtures** (`long` stems ~300 chars + ~90-char options, `unicode`
  Devanagari/Bengali/Tamil/Punjabi/Malayalam, `tiny` 3 questions COMPLETE,
  `many` 600 questions): no page errors, no external requests, no horizontal
  scroll, 0 sheet overflow at rest; the extreme long fixture scrolls inside the
  question area only after answering.
- **Phone destination bar:** each tab switches destination, marks the active
  tab, swaps to its filled icon, and Progress opens the report
  (`data-mode="analytics"`); 0 page errors.
- **Reading size:** Small/Default/Large changes reading text
  (15px → 13.875 / 17.25), persists in `localStorage` across reload, and does
  not make the sheet scroll.
- **Keyboard:** digit keys select and focus an option, Enter submits, focus
  rings are visible on interactive controls. Two keyboard defects found during
  this pass were fixed: Escape now returns focus to the control that opened a
  drawer, and Enter no longer hijacks focused links/buttons — which also
  revived the "Skip to question" link (it now lands on the question heading).
- **Accessibility pass:** first tab stop is the skip link; every visible
  control has an accessible name; four polite live regions announce answers,
  confidence, exam state and feedback; drawers expose `aria-hidden` state and
  take focus on open; reduced motion collapses transitions to 0s; 0 page
  errors.
- **Offline:** all requests are `file:` (3 requests, 0 external); no external
  `src`/`href` in the document.
- **Example parity:** the embedded package and meta in `examples/quiz.html` are
  identical to the committed version — 64 questions, same title.

---

## 7. Preserved functionality

Build pipeline (`prepare_package`, placeholders `/*__PACKAGE__*/{}`,
`/*__STATUS__*/""`, `/*__REVISION_ENGINE__*/` inlined), dynamic title/source
metadata, all four destinations and their `data-mode` values
(`practice` / `test` / `revision` / `analytics`), option evaluation, confidence
tracking, hints, test-mode rules, scoring and negative marking, mark-for-review,
question navigator with search and filters, source drawer, session drawer,
import/export, print stylesheet, keyboard shortcuts, `localStorage` keys
(`quiz_session_v2_…`, `quiz_readscale_…`), `file://` operation, and every
existing visual gate (option borders, study-note accents, 56px option height,
430px/860px breakpoints, `decimal-leading-zero`, `break-inside:avoid`, no
external URLs other than `w3.org`).

---

## 8. Known limitations

- The Progress report is a data report: it fits with no scrolling in the
  default state and at 1024×600 leaves 31px, but with a lot of history
  (14 answered questions produced ~340px at 1366×768) it scrolls inside the
  report. The study sheet is unaffected.
- A single question whose content is several times the normal length (e.g. a
  300-character stem with 90-character options) still needs the question area
  to scroll on a short window once the answered state adds its study note.
  Removing text size or the note would be worse than scrolling here.
- Two-column option grid applies only when every option is ≤16 characters and
  the count is even; longer or odd sets stay single column.
- 1024×600 (an unusually short desktop window) is the only tested size where
  the report needs a small scroll.
- The phone action bar and bottom bar are new chrome; the desktop action row
  is hidden on phones instead of duplicated.

---

## 9. Full suite

`python tests/run_all.py`:

```
tests run: 342, failures: 0, errors: 0, skipped: 0
RESULT: PASS
```

Static gate checks re-run for this work:

```
python -m unittest tests.test_web_visual tests.test_dashboard tests.test_web_desktop_icons
Ran 69 tests in 2.194s
OK
```

---

## 10. Try next

- If the Progress report should also never scroll, the next step is a compact
  section switcher (show one report group at a time) rather than more
  shrinking.
- If you want the two-column option grid always available, the character
  threshold (`≤16`) is the single number to raise.
