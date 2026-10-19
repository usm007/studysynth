# DESIGN.md (Stitch "Study Desk Editorial" visual language, 2026-10-09)

Direction source: Stitch project "Competitive Study Quiz Design System"
(screens + code in `.stitch/designs/`), applied as visual language only onto
the StudySynth product structure (Practice Deck / Test / Revision Engine /
Analytics; no Learn / Rapid Recall / Mistake Journal per PRODUCT.md).

- Metaphor (structural, never literal decoration): question = study sheet,
  shell = study desk, rail = study organizer/index, action row = desk control
  strip, feedback = study note, source = reference evidence, analytics = study
  plan.
- Palette (Stitch Material tokens): background `#faf8ff` family
  (`#ffffff` sheet, `#f2f3ff` rail, `#e2e7ff` track), ink `#131b2e`,
  single navy accent `#022448` / `#1e3a5f`, outline `#c4c6cf`. Green
  `#006d33` / red `#ba1a1a` reserved for correct/incorrect. Canvas `#e9edfb`
  deepens the desk behind the white sheet. All text pairs AA.
- Typography: Hanken Grotesk display (sheet number 34px/800, stem 20-24px/700,
  brand 17px/700, stat values 24px/700) with system fallbacks; Space Grotesk
  meta (11px/700 eyebrows, pills, mono numbers). Body system-ui. Offline file:
  no webfonts. Body never uppercase, never all-bold.
- Grammar: white sheet card with 3px navy top accent; bordered option rows
  (2px radius) with square letter markers; tinted correct/incorrect study
  notes; white analytics cards with numbered plan rows; ruled drawers.
- Radius: 4px cards/buttons, 2px markers/small controls, pills for metadata.
- Motion: `--ease` on existing transitions only. No loops.

Dial: ENERGY 2 / RHYTHM 2 / MOTION 1.

- Metaphor (structural, never literal decoration): question = study sheet,
  shell = study desk, rail = study organizer/index, action row = desk control
  strip, feedback = study note, source = reference evidence, analytics = study
  plan.
- Palette: light desk canvas `#e9edfb`, white sheet `#ffffff`, rail
  `#f2f3ff`, track `#e2e7ff`, ink `#131b2e`, single navy accent `#022448` /
  `#1e3a5f`, outline `#c4c6cf`. Green `#006d33` / red `#ba1a1a` reserved for
  correct/incorrect. No gradients (shimmer placeholder excepted), glass,
  neon, pastels. All text pairs AA.
- Typography: Hanken Grotesk display + Space Grotesk meta with system
  fallbacks (offline file, no webfonts). Sheet number 34px/800, stem
  20-24px/700, eyebrows 11px/700 wide-track. Uppercase wide-track labels
  mark structure only. Body never uppercase, never all-bold.
- Grammar: white sheet card with navy top accent; bordered option rows with
  square letter markers; tinted study notes; white analytics cards; ruled
  drawers. Statements, revision queue, and plan items separated by thin rules.
- Option marker: 30px square, 2px radius, bordered, subordinate to answer
  text. States: bordered quiet / navy border + tint (selected) / green
  (correct) / red (incorrect). Never color alone: verdict text + marker
  fill + border.
- Mode identities: Practice = active work; Test = inverted exam strip, aids suppressed; Revision = diagnostic board
  (why + weakness + action); Analytics = numbered study plan first, metrics second.
- Confidence meter: overall accuracy in the rail (percent + thin bar + correct/answered text, never color alone).
- Radius: 4px cards/buttons, 2px markers/small controls, pills for metadata.
- Motion: hover/selection/drawer/focus transitions only. No loops.

Dial: ENERGY 2 / RHYTHM 2 / MOTION 1.

Reason log (R-31):
- Navy only for primary actions, active mode, and structural rules. Reason:
  one accent marks action and structure.
- Ink (near-black) top rules on sheet, banner, drawers, plan sections.
  Reason: the rule is the desk's authority signal.
- Green/red only for correctness; amber only for priority/warning edges.
  Reason: exam-result semantics.
- Sheet number + topic/difficulty/tier margin on every question. Reason:
  workbook identity without engine IDs.
- Arrows mark forward movement only. Reason: direction cue for advance
  affordances.
- Shimmer only as boot loading placeholder mirroring question layout.
  Reason: loading-state shape match.
- Grotesk display/meta confined to numbers, stems, brands, eyebrows.
  Reason: Stitch voice where authority lives; body stays system-ui.
- Analytics stays 3-col equal cards per Stitch. Reason: plan markup and
  strings are product-owned; hierarchy comes from the numbered plan above.
- Next keeps a text arrow; Submit stays plain; Mark untouched. Reason:
  Stitch buttons carry direction in text; Mark's label is JS-owned.

## 2026-10-18 — Warm Study Desk (current direction)

Supersedes the navy "Study Desk Editorial" palette above and the uncommitted
generic-M3-purple swap. Structure, metaphor, and information architecture are
unchanged; this revision re-skins the same system and adds desktop fit rules,
a real icon set, and two phone affordances.

- Palette (light-first, warm paper + forest green): background `#f3f0e6`,
  sheet `#fffefa`, rail/wells `#f6f4eb` / `#ebe8dd`, ink `#1f2620` /
  `#414a44`, muted `#5f6860`, hairlines `#d8dcd2` / `#e7e9df`, single forest
  accent `#315d49` (`#244b3a` pressed), accent tint `#dce9df`. Correct
  `#205f35`, incorrect `#a63028`, warning/priority `#8a5b00`. Focus `#244b3a`.
  Measured contrast: ink 15.3:1, muted 5.7:1, accent 7.5:1, good 7.6:1,
  bad 6.8:1, warn 5.2:1 — all AA for body text. `--faint` (2.98:1) is used
  for decorative rules only.
- Typography: system stacks only (offline file, no webfonts). Serif display
  stack for the brand, the question stem, the sheet number and analytic
  figures; system sans for all UI, meta, and body copy. Reading metric is one
  variable, `--read`, applied as `calc(<size> * var(--read))`.
- Grammar: paper sheet on a paper desk, hairline rules instead of shadows,
  16px card radius / 10px control radius, no gradients, glass, neon, or
  heavy shadow. Option rows keep a square letter marker and a bottom rule.
- Icons: Material Symbols Rounded, **inlined as a 29-symbol SVG sprite**
  (`viewBox="0 -960 960 960"`). No icon webfont, no CDN, no network at
  runtime. Outlined/filled pairs swap on state (`.is-on`, `.active`,
  `[aria-selected="true"]`); every icon is `aria-hidden` and every control
  keeps a text or `aria-label` name, so nothing depends on the glyph.
- Desktop app shell (`≥861px`): the page never scrolls. The question sheet
  fills the window, the action row and confidence chips are pinned, and
  `.q-flow` is the only region that may scroll — and only when content
  genuinely overflows. Width caps rise to `--max:1800px` / `--measure:1180px`
  so wide monitors are used. Two compaction tiers (≤900px and ≤700px viewport
  height) tighten padding, option height, and match columns; at ≤700px the
  redundant mode banner and instruction line are dropped rather than the
  content.
- Space use on desktop: short answers (`≤4` options, all `≤16` characters)
  render as a two-column option grid, and the progress report reads in two
  columns above 1024px. Both exist to fit real content without scrolling.
- Phone: bottom destination bar (Study / Test / Revision / Progress) plus a
  phone action bar (previous, mark, submit, next) that delegates to the same
  handlers as the desktop controls. Match-the-following columns stack below
  620px. Safe-area insets respected; touch targets ≥48px for options.
- Reading size: Small / Default / Large control persisted per module under
  `quiz_readscale_<title>`; it scales reading text only, never chrome.

Reason log (R-32 … R-41):
- Warm paper + one forest accent. Reason: a long-form study surface reads
  better on warm neutral paper, and a single desaturated green carries both
  action and structure without competing with the red/green result colours.
- Serif confined to brand, stem, sheet number, figures. Reason: gives the
  sheet a printed-paper voice while UI and meta stay in the system sans.
- Icons inlined as sprite rather than an icon font. Reason: `file://`
  offline modules cannot fetch a font, and a font would fail silently to
  tofu; inlined paths always render and stay crisp.
- Bookmark, not a star, for "mark for review". Reason: star reads as
  rating/favourite; bookmark is the conventional exam-review token.
- Question heading highlight instead of a full focus box. Reason: the heading
  is a programmatic focus target for the skip link and the question list;
  a band marks it without drawing a large empty rectangle around the measure.
- No page scroll on desktop; one inner scroll region only when needed.
  Reason: desktop users read the whole sheet at once; the scroll indicator on
  the sheet is the honest signal that this one question is unusually long.
- Two-column option grid for very short answers. Reason: short answer codes
  ("1 and 3 only", "c-d-e-a-b") waste a full row each; pairing them uses the
  width and halves the option block height.
- Mode banner and instruction line dropped below 700px viewport height.
  Reason: the rail and sheet header already name the destination; the banner
  is the cheapest thing to remove, content is not.
- Read scale as a variable, not duplicated font sizes. Reason: one control
  scales every reading surface consistently and the choice is per module.
- Progress report columns above 1024px. Reason: the report is a dashboard,
  not a document; two columns halve its height on desktop.
- Focus returns to the opener when a drawer closes, and Enter keeps its native
  meaning while a link or button holds focus. Reason: a keyboard user must be
  able to leave a drawer and use the "Skip to question" link without the
  shortcut layer fighting the control they are on.

