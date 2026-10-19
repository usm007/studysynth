"""StudySynth Master Dashboard (index.html) Generator & Updater.

Maintains a self-contained local library dashboard (index.html) in the root output directory.
Automatically appends or updates cards for generated Study Modules in a clean CSS grid layout.
"""
from __future__ import annotations

import argparse
import datetime
import html
import json
import os
import re
from pathlib import Path


REGISTRY_START = "<!-- STUDY_SYNTH_REGISTRY_START -->"
REGISTRY_END = "<!-- STUDY_SYNTH_REGISTRY_END -->"


DASHBOARD_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<link rel="icon" href="data:,">
<title>StudySynth Library — Master Dashboard</title>
<style>
/* StudySynth "Warm Study Desk" library tokens: same system as the study module
   (templates/web/app.template.html). Light paper surfaces, forest accent #315D49.
   Offline: system stacks only, no webfonts, no network requests. */
:root {
  --bg: #f3f0e6;
  --surface: #fffefa;
  --surface-2: #f6f4eb;
  --surface-3: #ebe8dd;
  --ink: #1f2620;
  --ink-2: #414a44;
  --muted: #5f6860;
  --line: #d8dcd2;
  --line-soft: #e7e9df;
  --line-strong: #a2a9a0;
  --accent: #315d49;
  --accent-2: #244b3a;
  --accent-soft: #dce9df;
  --good: #205f35;
  --good-bg: #e9f3e7;
  --good-line: #bfd9c4;
  --warn: #8a5b00;
  --warn-bg: #fbf1d9;
  --warn-line: #e8d5a4;
  --bad: #a63028;
  --bad-bg: #faecea;
  --bad-line: #ebc3bd;
  --focus: #244b3a;
  --radius: 16px;
  --radius-s: 10px;
  --ease: cubic-bezier(0.2, 0, 0, 1);
  --font-display: "Iowan Old Style", "Palatino Linotype", "Book Antiqua", Palatino, Georgia, serif;
  --font-ui: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Noto Sans", "Noto Sans Devanagari", "Helvetica Neue", Arial, sans-serif;
  --shadow-sm: 0 1px 2px rgba(31, 38, 32, .06);
  --shadow: 0 1px 3px rgba(31, 38, 32, .08), 0 4px 10px rgba(31, 38, 32, .05);
}
* { box-sizing: border-box; margin: 0; padding: 0; }
html { -webkit-text-size-adjust: 100%; }
body {
  font-family: var(--font-ui);
  background: var(--bg);
  color: var(--ink);
  line-height: 1.55;
  font-size: 15px;
  min-height: 100vh;
  min-height: 100dvh;
  padding: calc(2rem + env(safe-area-inset-top)) 1.5rem calc(2.5rem + env(safe-area-inset-bottom));
}
:focus { outline: none; }
:focus-visible { outline: 2px solid var(--focus); outline-offset: 2px; border-radius: 4px; }
::selection { background: var(--accent-soft); }

.container { max-width: 1160px; margin: 0 auto; }

/* header: brand + live count */
header {
  margin-bottom: 1.75rem;
  padding-bottom: 1.1rem;
  border-bottom: 1px solid var(--line);
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
}
.brand-section { display: flex; align-items: center; gap: .9rem; min-width: 0; }
.brand-icon {
  width: 44px;
  height: 44px;
  background: var(--accent);
  color: #ffffff;
  border-radius: var(--radius-s);
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  font-size: 1.05rem;
  letter-spacing: .5px;
  flex: none;
}
.brand-info h1 {
  font-family: var(--font-display);
  font-size: 1.5rem;
  font-weight: 700;
  letter-spacing: -0.02em;
  color: var(--accent-2);
  line-height: 1.25;
}
.brand-info p { color: var(--muted); font-size: .875rem; }
.stats-bar { display: flex; gap: .6rem; align-items: center; flex-wrap: wrap; }
.stat-pill {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 99px;
  padding: .35rem .9rem;
  font-size: .8rem;
  color: var(--muted);
  display: flex;
  gap: .45rem;
  align-items: center;
  font-variant-numeric: tabular-nums;
}
.stat-pill strong { color: var(--ink); font-weight: 700; }

/* search */
.search-section { margin-bottom: 1.5rem; max-width: 460px; }
.search-wrap { position: relative; }
.search-wrap .sw-icon {
  position: absolute;
  left: 12px;
  top: 50%;
  transform: translateY(-50%);
  color: var(--muted);
  pointer-events: none;
}
.search-input {
  width: 100%;
  max-width: 480px;
  padding: .68rem 1rem .68rem 2.4rem;
  background: var(--surface);
  border: 1px solid var(--line-strong);
  border-radius: var(--radius-s);
  color: var(--ink);
  font: inherit;
  font-size: .95rem;
  min-height: 44px;
  transition: border-color .15s var(--ease), box-shadow .15s var(--ease);
}
.search-input::placeholder { color: var(--muted); }
.search-input:focus {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-soft);
}

/* library grid: responsive cards, one per module */
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 1.1rem;
}
.card {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  padding: 1.25rem 1.35rem;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  gap: 1rem;
  transition: transform .18s var(--ease), box-shadow .18s var(--ease), border-color .18s var(--ease);
}
.card:hover {
  transform: translateY(-2px);
  border-color: var(--line-strong);
  box-shadow: var(--shadow);
}
.card-top { margin-bottom: 0; }
.card-badges { display: flex; flex-wrap: wrap; gap: .45rem; margin-bottom: .7rem; }
.badge {
  font-size: .7rem;
  font-weight: 700;
  letter-spacing: .06em;
  padding: .22rem .55rem;
  border-radius: 6px;
  text-transform: uppercase;
}
.badge-module { background: var(--surface-2); color: var(--ink-2); border: 1px solid var(--line); }
.badge-status { background: var(--good-bg); color: var(--good); border: 1px solid var(--good-line); }
.card-title {
  font-family: var(--font-display);
  font-size: 1.15rem;
  font-weight: 700;
  line-height: 1.4;
  margin-bottom: .45rem;
  color: var(--ink);
  overflow-wrap: break-word;
}
.card-meta {
  font-size: .835rem;
  color: var(--muted);
  display: flex;
  flex-direction: column;
  gap: .3rem;
  font-variant-numeric: tabular-nums;
  overflow-wrap: break-word;
}
.card-footer {
  padding-top: .9rem;
  border-top: 1px solid var(--line-soft);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: .75rem;
  flex-wrap: wrap;
}
.btn-launch {
  background: var(--accent);
  color: #ffffff;
  text-decoration: none;
  font-weight: 700;
  font-size: .875rem;
  padding: .5rem 1rem;
  border-radius: var(--radius-s);
  min-height: 40px;
  display: inline-flex;
  align-items: center;
  gap: .4rem;
  transition: background .15s var(--ease);
}
.btn-launch:hover { background: var(--accent-2); }
.btn-launch:focus-visible { outline-offset: 2px; }
.btn-launch .ic { width: 1rem; height: 1rem; fill: currentColor; flex: none; }
.date-text { font-size: .78rem; color: var(--muted); font-variant-numeric: tabular-nums; }

.empty-state {
  grid-column: 1 / -1;
  text-align: center;
  padding: 3.5rem 1.5rem;
  background: var(--surface);
  border: 1px dashed var(--line-strong);
  border-radius: var(--radius);
  color: var(--muted);
}

@media (max-width: 640px) {
  body { padding: 1.25rem 1rem 2rem; }
  .grid { grid-template-columns: 1fr; }
  .brand-info h1 { font-size: 1.3rem; }
  .btn-launch { flex: 1; justify-content: center; }
}
@media (prefers-reduced-motion: reduce) {
  * { transition: none !important; }
}
</style>
</head>
<body>
<div class="container">
  <header>
    <div class="brand-section">
      <div class="brand-icon" aria-hidden="true">SS</div>
      <div class="brand-info">
        <h1>StudySynth Library</h1>
        <p>Interactive Study Modules &amp; Revision Engine</p>
      </div>
    </div>
    <div class="stats-bar">
      <div class="stat-pill">
        <span>Modules:</span>
        <strong id="moduleCount">0</strong>
      </div>
      <div class="stat-pill">
        <span>Storage:</span>
        <strong>Local-First</strong>
      </div>
    </div>
  </header>

  <div class="search-section">
    <div class="search-wrap">
      <svg class="sw-icon" viewBox="0 0 20 20" width="16" height="16" fill="none" aria-hidden="true"><circle cx="9" cy="9" r="5.5" stroke="currentColor" stroke-width="1.8"/><path d="M13.5 13.5 17 17" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>
      <label class="skip-label" for="searchInput" style="position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0)">Search study modules</label>
      <input type="text" id="searchInput" class="search-input" placeholder="Search study modules…" onkeyup="filterCards()">
    </div>
  </div>

  <main class="grid" id="moduleGrid">
    <!-- STUDY_SYNTH_REGISTRY_START -->
    <div class="empty-state">
      <p>No Study Modules generated yet. Run the StudySynth pipeline to create interactive modules.</p>
    </div>
    <script type="application/json" id="studysynth-registry">{"modules":[]}</script>
    <!-- STUDY_SYNTH_REGISTRY_END -->
  </main>
</div>

<script>
function filterCards() {
  const query = (document.getElementById('searchInput').value || '').toLowerCase().trim();
  const cards = document.querySelectorAll('.card');
  cards.forEach(card => {
    const text = card.textContent.toLowerCase();
    card.style.display = text.includes(query) ? '' : 'none';
  });
}
</script>
</body>
</html>
"""


def _update_module_count(content: str, count: int) -> str:
    """Rewrite the header module counter regardless of its element tag."""
    new_value = f'<strong id="moduleCount">{count}</strong>'
    updated, n = re.subn(
        r'<(?:span|strong) id="moduleCount">\d*</(?:span|strong)>',
        new_value,
        content,
    )
    if not n:
        # counter missing (older/hand-edited dashboard): keep content usable
        raise SystemExit("ERROR: dashboard template lost the module count marker")
    return updated


def _load_registry_data(html_content: str) -> list[dict]:
    """Extract registered modules from JSON payload in dashboard HTML."""
    match = re.search(
        r'<script type="application/json" id="studysynth-registry">(.*?)</script>',
        html_content,
        re.DOTALL,
    )
    if match:
        try:
            data = json.loads(match.group(1))
            return data.get("modules", [])
        except Exception:
            pass
    return []


def read_dashboard_entries(dashboard_path: Path | str) -> list[dict]:
    """Read the registered study module entries from a dashboard file."""
    p = Path(dashboard_path)
    if not p.is_file():
        return []
    content = p.read_text(encoding="utf-8")
    return _load_registry_data(content)


def _render_cards(modules: list[dict]) -> str:
    """Render HTML cards and registry script for a list of modules."""
    if not modules:
        cards_html = """      <div class="empty-state">
        <p>No Study Modules generated yet. Run the StudySynth pipeline to create interactive modules.</p>
      </div>"""
    else:
        cards = []
        for m in modules:
            title = html.escape(m.get("title", "Untitled Module"))
            rel_path = html.escape(m.get("path", "#"))
            status = html.escape(m.get("status", "Active"))
            updated = html.escape(m.get("updated", datetime.date.today().isoformat()))
            q_cnt = m.get("question_count")
            q_meta = f"<span>Items: {q_cnt} questions</span>" if q_cnt is not None else ""
            profile = m.get("profile")
            prof_meta = f"<span>Target: {html.escape(str(profile))}</span>" if profile else ""

            card = f"""      <article class="card" data-title="{title}">
        <div class="card-top">
          <div class="card-badges">
            <span class="badge badge-module">Study Module</span>
            <span class="badge badge-status">{status}</span>
          </div>
          <h2 class="card-title">{title}</h2>
          <div class="card-meta">
            <span>File: {rel_path}</span>
            {q_meta}
            {prof_meta}
          </div>
        </div>
        <div class="card-footer">
          <span class="date-text">{updated}</span>
          <a href="{rel_path}" class="btn-launch">Launch Module <svg class="ic" aria-hidden="true" viewBox="0 -960 960 960"><path d="M647-440H200q-17 0-28.5-11.5T160-480q0-17 11.5-28.5T200-520h447L451-716q-12-12-11.5-28t12.5-28q12-11 28-11.5t28 11.5l264 264q6 6 8.5 13t2.5 15q0 8-2.5 15t-8.5 13L508-188q-11 11-27.5 11T452-188q-12-12-12-28.5t12-28.5l195-195Z"/></svg></a>
        </div>
      </article>"""
            cards.append(card)
        cards_html = "\n".join(cards)

    data_payload = json.dumps({"modules": modules}, ensure_ascii=False)
    registry_script = f'<script type="application/json" id="studysynth-registry">{data_payload}</script>'

    return f"\n{cards_html}\n      {registry_script}\n"


def generate_dashboard_html(modules: list[dict]) -> str:
    """Generate complete standalone master dashboard HTML for given modules."""
    rendered_block = _render_cards(modules)
    content = DASHBOARD_TEMPLATE
    s_idx = content.find(REGISTRY_START) + len(REGISTRY_START)
    e_idx = content.find(REGISTRY_END)
    updated_content = content[:s_idx] + rendered_block + content[e_idx:]
    updated_content = _update_module_count(updated_content, len(modules))
    return updated_content


def update_dashboard(
    dashboard_path: Path | str,
    module_path: Path | str,
    title: str,
    metadata: dict | None = None,
) -> Path:
    """Append or update a Study Module entry in the master dashboard index.html.

    Args:
        dashboard_path: Destination path for index.html (e.g. output/index.html)
        module_path: Absolute or relative path to the generated study module HTML
        title: Clean, human-readable title (e.g. 'Assam Geography v2')
        metadata: Optional dictionary with status, question_count, profile, etc.
    """
    dash_p = Path(dashboard_path).resolve()
    mod_p = Path(module_path).resolve()

    dash_p.parent.mkdir(parents=True, exist_ok=True)

    # Compute relative path from dashboard location to module
    try:
        rel_path = os.path.relpath(mod_p, dash_p.parent)
        # Normalize to web forward slashes
        rel_path = rel_path.replace("\\", "/")
    except ValueError:
        rel_path = str(mod_p)

    meta = metadata or {}
    new_entry = {
        "title": title,
        "path": rel_path,
        "status": meta.get("status", "Comprehensive"),
        "question_count": meta.get("question_count"),
        "profile": meta.get("profile", ""),
        "updated": datetime.date.today().isoformat(),
    }

    if dash_p.is_file():
        content = dash_p.read_text(encoding="utf-8")
    else:
        content = DASHBOARD_TEMPLATE

    # Ensure registry markers exist
    if REGISTRY_START not in content or REGISTRY_END not in content:
        content = DASHBOARD_TEMPLATE

    modules = _load_registry_data(content)

    # Upsert module: replace if existing matching path or title
    matched_idx = -1
    for i, m in enumerate(modules):
        if m.get("path") == rel_path or m.get("title") == title:
            matched_idx = i
            break

    if matched_idx >= 0:
        modules[matched_idx] = new_entry
    else:
        modules.append(new_entry)

    rendered_block = _render_cards(modules)

    # Update HTML between markers
    s_idx = content.find(REGISTRY_START) + len(REGISTRY_START)
    e_idx = content.find(REGISTRY_END)
    updated_content = content[:s_idx] + rendered_block + content[e_idx:]

    # Update module count in header
    updated_content = _update_module_count(updated_content, len(modules))

    dash_p.write_text(updated_content, encoding="utf-8")
    return dash_p


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Maintain master StudySynth index.html dashboard.")
    ap.add_argument("--dashboard", "-d", default="output/index.html", help="Path to master index.html")
    ap.add_argument("--module", "-m", required=True, help="Path to generated Study Module HTML")
    ap.add_argument("--title", "-t", required=True, help="Clean title for Study Module")
    ap.add_argument("--question-count", type=int, default=None, help="Question count")
    ap.add_argument("--status", default="Comprehensive", help="Package status")
    ap.add_argument("--profile", default="", help="Profile name")
    args = ap.parse_args(argv)

    meta = {
        "question_count": args.question_count,
        "status": args.status,
        "profile": args.profile,
    }

    out = update_dashboard(
        dashboard_path=args.dashboard,
        module_path=args.module,
        title=args.title,
        metadata=meta,
    )
    print(f"OK: Updated Master Dashboard at {out}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
