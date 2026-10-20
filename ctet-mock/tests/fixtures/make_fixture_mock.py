"""Write a small but real mock document for the browser tests.

The mock is a miniature of the generated study modules: it carries an
embedded package, a question stem and a little styling, so the player and the
offline worker are exercised against something that behaves like a real paper.
"""
from __future__ import annotations

import json
from pathlib import Path

TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<title>{title}</title>
<style>
  :root {{ --ink: #1f2620; --muted: #5f6860; --accent: #315d49; }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
    color: var(--ink); background: #f3f0e6; padding: 1rem; line-height: 1.5;
  }}
  .head {{ font-size: .8rem; color: var(--muted); margin-bottom: .8rem; }}
  .stem {{ font-size: 1.05rem; font-weight: 600; margin-bottom: 1rem; }}
  .opt {{
    display: block; width: 100%; text-align: left; margin-bottom: .5rem;
    padding: .7rem .8rem; min-height: 44px; background: #fffefa;
    border: 1px solid #d8dcd2; border-radius: 10px; font: inherit;
  }}
</style>
</head>
<body>
  <p class="head">{title} &middot; {questions} questions</p>
  <p class="stem" id="qstem">{stem}</p>
  <button class="opt" type="button">Option one</button>
  <button class="opt" type="button">Option two</button>
  <button class="opt" type="button">Option three</button>
  <button class="opt" type="button">Option four</button>
<script>
var PKG = /*__PACKAGE__*/{package};
</script>
</body>
</html>
"""


def write_fixture_mock(directory: Path, name: str, title: str,
                       stem: str = "Which option is correct?",
                       questions: int = 2) -> Path:
    """Write a fixture mock into ``directory`` and return its path."""
    package = {
        "meta": {
            "title": title,
            "source": "Fixture source",
            "source_title": title,
            "profile": "CTET",
            "status": "COMPREHENSIVE",
            "coverage": f"{questions} questions",
        },
        "questions": [
            {"id": f"Q-{index + 1:04d}", "stem": stem, "type": "factual_mcq",
             "topic": "Fixture", "difficulty": "easy", "tier": 1,
             "options": [
                 {"key": "A", "text": "Option one", "is_correct": True},
                 {"key": "B", "text": "Option two", "is_correct": False},
                 {"key": "C", "text": "Option three", "is_correct": False},
                 {"key": "D", "text": "Option four", "is_correct": False},
             ],
             "answer": "A", "explanation": "Because."}
            for index in range(questions)
        ],
    }
    path = Path(directory) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        TEMPLATE.format(
            title=title,
            stem=stem,
            questions=questions,
            package=json.dumps(package, ensure_ascii=False, separators=(",", ":")),
        ),
        encoding="utf-8",
    )
    return path
