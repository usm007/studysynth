# StudySynth UI Redesign Specification (2026-10)

Scope: visual + responsive system for the standalone study module
(`templates/web/app.template.html`) and master library (`scripts/dashboard.py`).
No engine, pipeline, package-schema or JS-contract changes except the three
narrowly scoped behaviors listed in §6.

## 1. Identity

Material 3 Expressive–referenced, restrained editorial study aesthetic:
warm paper surfaces, single forest-green accent, serif display for the
question voice, system sans for structure and meta. Light theme only.
No gradients beyond the skeleton shimmer, no glass, no decorative cards.

## 2. Design tokens (CSS custom properties, unchanged names)

| Token | Value | Role |
|---|---|---|
| `--bg` | `#F3F0E7` | warm paper desk |
| `--surface` | `#FFFEFA` | sheets, cards |
| `--surface-2` | `#F6F4EB` | rail, quiet fills |
| `--surface-3` | `#EBE8DD` | chip/track fills |
| `--ink` | `#1F2620` | primary text (15.3:1 on surface) |
| `--ink-2` | `#414A44` | secondary text |
| `--muted` | `#5F6860` | muted text (5.7:1 on surface) |
| `--faint` | `#79837A` | decorative separators only |
| `--line` | `#D8DCD2` | rules, borders |
| `--line-soft` | `#E7E9DF` | soft rules |
| `--line-strong` | `#A2A9A0` | input borders |
| `--accent` | `#315D49` | actions + active state (7.4:1 on surface) |
| `--accent-2` | `#244B3A` | hover/pressed/focus |
| `--accent-soft` | `#DCE9DF` | selected containers |
| `--good` | `#205F35` | correct (7.6:1 incl. white text) |
| `--bad` | `#A63028` | incorrect (6.8:1 incl. white text) |
| `--warn` | `#8A5B00` | priority/hint (5.2:1 on warn bg) |
| `--focus` | `#244B3A` | focus-visible outline |

Radii: `--radius:16px` (cards), `--radius-s:10px` (controls). Motion:
`--ease:cubic-bezier(0.2,0,0,1)` on existing transitions only, reduced-motion
kill-switch retained. Shadows warm-tinted `rgba(31,38,32,…)`.

Type: body `--font-ui` = system sans (15.5px). Display serif
(`Iowan Old Style → Palatino Linotype → Georgia → Noto Serif → serif`) for
`.brand-name`, `.q-stem`, `.sheet-num` — the reading voice only. Meta sans
stays for labels, tabular numbers, uppercase structure.

## 3. Information architecture

Destinations (plain language; internal `data-mode` values unchanged):

Rail (≥861px): **Study** (Answer and review) · **Test** (Exam conditions) ·
**Revision** (Weak areas) · **Progress** (Performance).

Phones (≤860px): fixed **bottom navigation bar** with the same four
destinations (icon + label, ≥48px targets), plus a slim fixed **action bar**
(Previous · Mark · Submit/Next) docked above it. Analytics hides the action
bar (no question controls) but keeps destination nav.

Drawer/sheet behavior unchanged: navigator, filters, source, session remain
drawers; they render as bottom sheets ≤860px.

## 4. Responsive reference layout

- ≤480px: single column; topbar = hamburger, brand (truncated), compact
  progress, tools; sheet header carries question context; options ≥48px.
- 481–767px: same shell, wider gutters; progress row gains the numbers.
- 768–1023px: shell can show the rail at reduced width; drawers become
  side panels where width allows (existing behavior).
- ≥1024px: 210px rail + measure-limited workspace (1024px), focus ring,
  keyboard shortcuts in rail footer, collapsed-rail icon rail retained.
- Both portrait/landscape tablet cases land on the ≥861px shell.
- Safe-area insets on topbar (top) and bottom nav/action bar (bottom);
  `viewport-fit=cover`; workspace reserves `calc()` bottom padding so no
  fixed chrome ever obscures content.

## 5. Components (state coverage)

Primary button (accent fill, hover accent-2, pressed, disabled, focus ring),
secondary/tertiary/outline buttons, danger, sm variant. Answer option:
quiet → hover → selected (accent border + container + filled marker) →
correct/incorrect (green/red border, tint, filled marker, textual verdict
"C ✓ Correct" / "✕ Yours") → disabled. Confidence chips with `:has(input:checked)`.
Navigator grid states retained (`cur/is-right/is-wrong/is-marked/is-hipri/is-revneed`)
with legend. Feedback study-note with state top-rule. Revision priority chips.
Analytics plan list (decimal-leading-zero) + stat cells + bar rows
(low <60 red, mid <80 amber).

## 6. Narrowly scoped behavioral additions (declared, engine untouched)

1. **Bottom navigation** (phones): 4 destination buttons bound to the same
   `setMode()`/`showAnalytics()` functions the rail uses. No new state.
2. **Mobile mark action** (`#mMark`): same handler as `#markbtn`.
3. **Reading-size control**: `--read` custom property (0.925 / 1 / 1.15)
   applied via `html[data-read]`; multiplies the question-reading text only
   (stem, options, statements, explanations). Persisted in localStorage under
   its own key, applied at boot; Session drawer gains a 3-step segmented
   control. Does not interact with `state`/session schema.

## 7. Overflow & touch safeguards

`overflow-wrap:break-word; min-width:0` on question text, options, note
body, and match/statement cells. Never truncate stems/statements. Touch
targets ≥48px on phones (options 48–56px, nav items 56px, drawer controls ≥40px).

## 8. Master library (`scripts/dashboard.py`)

Same token system. Light theme; module cards as a responsive grid
(`repeat(auto-fill, minmax(300px,1fr))` → 1 column ≤640px). Card carries
title, status badge, question count, target profile, relative path,
updated date, "Launch Module" action. Search filters client-side (kept).
Empty state text kept. Registry markup, upsert, round-trip JSON untouched.
Focus-visible + keyboard reachable actions.

## 9. Gates that constrain styles (work-preserving contract)

- `.opt` keeps `border:1px solid var(--line)` + explicit `border-bottom`,
  no `var(--radius)`; verdict strings "✓ Correct"/"✕ Yours"-style kept.
- `.study-note.is-ok/.is-bad` + `border-top:3px solid var(--ink)`.
- `min-height:56px`, `430px`, `860px`, `decimal-leading-zero`,
  `@media print` + `break-inside:avoid` retained.
- No `http(s)://` URLs (except `w3.org` SVG namespaces).
- All IDs/classes used by tests and JS stay (opts, submitbtn, modebar,
  drawers, analytics section hooks, `rev-hce`, `rev-cog`, …).
