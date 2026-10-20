"""Build the CTET Mock PWA: classify the mocks, write the catalogue and the
offline service worker.

    python ctet-mock/build.py
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from . import catalog as catalog_mod
from . import intake
from . import sw as sw_mod

MOCKS_DIRNAME = "mocks"
CATALOG_NAME = "catalog.json"
WORKER_NAME = "sw.js"
SIDECAR_SUFFIX = ".meta.json"

# A mock file name ends up in a URL and in the generated worker, so it stays
# to letters, digits, dots, dashes and underscores.
SAFE_NAME = re.compile(r"^[A-Za-z0-9._-]+$")


def _read(path: Path) -> str:
    """Read a file without touching its line endings."""
    with open(path, "r", encoding="utf-8", errors="replace", newline="") as handle:
        return handle.read()


def _write(path: Path, text: str) -> None:
    """Write a file without touching its line endings."""
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)


def _table(rows: list[dict], problems: list[dict]) -> None:
    headers = ("paper", "subject", "class", "lesson", "mock", "questions", "source")
    widths = {key: len(key) for key in headers}
    for row in rows:
        for key in headers:
            value = str(row.get(key, "") or "")
            widths[key] = max(widths[key], len(value))
    print("  ".join(key.ljust(widths[key]) for key in headers))
    print("  ".join("-" * widths[key] for key in headers))
    for row in rows:
        cells = []
        for key in headers:
            value = str(row.get(key, "") or "")
            cells.append(value.ljust(widths[key]))
        print("  ".join(cells))
    for problem in problems:
        print(f"PROBLEM       {problem['name']}")
        print(f"             {problem['reason']}")


def _escalate(record: dict, level: int) -> str:
    """A more specific title, used when two papers would share a session."""
    label = record.get("mock_label") or ""
    lesson = record.get("lesson") or ""
    klass = record.get("klass")
    paper = record.get("paper") or ""
    if level <= 1:
        parts = [label, f"Class {klass}" if klass is not None else "", lesson]
    elif level <= 2:
        parts = [paper, f"Class {klass}" if klass is not None else "", label, lesson]
    else:
        parts = [paper, f"Class {klass}" if klass is not None else "", label, lesson,
                 Path(record.get("name") or "").stem]
    return " · ".join(part for part in parts if part)


def resolve_titles(records: list[dict]) -> None:
    """Give every mock a title whose saved session is its own.

    A title a previous build settled on is never changed, so adding a paper
    cannot rename an existing one or orphan the session saved under it.
    """
    used: dict[str, dict] = {}
    ordered = sorted(records, key=lambda r: (not r.get("title_locked"),
                                             r.get("name") or ""))
    for record in ordered:
        title = record.get("title") or ""
        key = catalog_mod.session_key(title)
        if key in used:
            level = 1
            while key in used and level < 6:
                title = _escalate(record, level)
                key = catalog_mod.session_key(title)
                level += 1
        record["title"] = title
        record["sessionKey"] = key
        used[key] = record


def build(public_dir: Path, mocks_dir: Path | None = None, retitle: bool = True,
          allow_unclassified: bool = False, quiet: bool = False) -> int:
    """Rebuild the catalogue and the offline worker. Returns a shell exit code."""
    public_dir = Path(public_dir)
    if mocks_dir is None:
        mocks_dir = public_dir / MOCKS_DIRNAME
    mocks_dir = Path(mocks_dir)
    mocks_dir.mkdir(parents=True, exist_ok=True)

    problems: list[dict] = []
    mock_files = sorted(mocks_dir.glob("*.html"))
    known = {path.name for path in mock_files}
    for path in sorted(mocks_dir.iterdir()):
        if not path.is_file():
            continue
        if path.name in known or path.name.endswith(SIDECAR_SUFFIX):
            continue
        problems.append({
            "name": path.name,
            "reason": "not a mock document (expected a .html file)",
        })

    records = []
    for path in mock_files:
        if not SAFE_NAME.match(path.name) or path.name.startswith("."):
            problems.append({
                "name": path.name,
                "reason": "the file name may only use letters, digits, dots, "
                          "dashes and underscores",
            })
            continue
        html = _read(path)
        record = intake.classify(path, html, intake.load_sidecar(path))
        if not record.get("questions"):
            problems.append({
                "name": path.name,
                "reason": "the document carries no questions (is it a "
                          "generated mock?)",
            })
        if not retitle:
            # The mock keeps its own title, so the catalogue and the saved
            # session must use that title too.
            package = intake.read_package(html) or {}
            meta = package.get("meta") or {}
            if isinstance(meta, dict) and isinstance(meta.get("title"), str):
                record["title"] = meta["title"]
                record["title_locked"] = True
        records.append(record)

    resolve_titles(records)
    built = catalog_mod.build_catalog(records, version="")

    # Write the settled title and the classification back into the mock, so a
    # later build reads the same thing instead of guessing again.
    if retitle:
        for record in records:
            path = mocks_dir / record["name"]
            html = _read(path)
            library = {
                "title": record["title"],
                "paper": record["paper"],
                "subject": record["subject"],
                "class": record["klass"],
                "lesson": record["lesson"],
                "mock": record["mock_label"],
            }
            updated = intake.rewrite_package_title(html, record["title"], library)
            if updated != html:
                _write(path, updated)

    for mock in built["mocks"]:
        name = Path(mock["file"]).name
        record = next((r for r in records if r["name"] == name), None)
        if record and record.get("sessionKey"):
            mock["sessionKey"] = record["sessionKey"]

    # The version covers the shell, the mocks and the catalogue body, so a
    # changed paper or a changed library always reaches the phone.
    entries: list[tuple[str, bytes]] = []
    for name in sw_mod.SHELL_FILES:
        path = public_dir / name
        if path.is_file():
            entries.append((name, path.read_bytes()))
    for path in mock_files:
        entries.append((f"{MOCKS_DIRNAME}/{path.name}", path.read_bytes()))
    hashable = {key: value for key, value in built.items()
                if key not in ("version", "cacheName")}
    entries.append((CATALOG_NAME,
                    json.dumps(hashable, sort_keys=True,
                               ensure_ascii=False).encode("utf-8")))
    version = sw_mod.compute_version(entries)
    built["version"] = version
    built["cacheName"] = sw_mod.cache_name(version)

    _write(public_dir / CATALOG_NAME,
           json.dumps(built, ensure_ascii=False, indent=1))

    precache = ["./"]
    for name in sw_mod.SHELL_FILES:
        if (public_dir / name).is_file():
            precache.append(name)
    precache.append(CATALOG_NAME)
    for path in mock_files:
        precache.append(f"{MOCKS_DIRNAME}/{path.name}")
    _write(public_dir / WORKER_NAME,
           sw_mod.render_service_worker(version, precache))

    rows = []
    incomplete = []
    for record in records:
        row = {
            "paper": record.get("paper") or "-",
            "subject": record.get("subject") or "-",
            "class": record.get("klass") if record.get("klass") is not None else "-",
            "lesson": record.get("lesson") or "-",
            "mock": record.get("mock_label") or "-",
            "questions": record.get("questions", 0),
            "source": record.get("source", ""),
        }
        if not intake.is_complete(record):
            incomplete.append(record)
        rows.append(row)
    if not quiet:
        _table(rows, problems)
        print(f"\n{built['counts']['mocks']} mock(s) - version {version} - "
              f"{len(precache)} files cached offline")
        missing = [name for name in sw_mod.SHELL_FILES
                   if not (public_dir / name).is_file()]
        for name in missing:
            print(f"note: shell file not found yet: {name}")

    failed = bool(incomplete) or bool(problems)
    if failed and not allow_unclassified:
        print("\nERROR: some mocks could not be published. "
              "Rename them, add a .meta.json sidecar, or pass "
              "--allow-unclassified.", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    default_public = Path(__file__).resolve().parent.parent / "public"
    parser = argparse.ArgumentParser(
        description="Classify the CTET Mock library and rebuild the offline worker."
    )
    parser.add_argument("--public-dir", default=str(default_public),
                        help="Directory the site is served from")
    parser.add_argument("--mocks-dir", default=None,
                        help="Directory holding the mock documents "
                             "(defaults to <public-dir>/mocks)")
    parser.add_argument("--no-retitle", action="store_true",
                        help="Do not rewrite the title inside the mock documents")
    parser.add_argument("--allow-unclassified", action="store_true",
                        help="Do not fail when a mock cannot be published")
    parser.add_argument("--quiet", action="store_true",
                        help="Only report errors")
    args = parser.parse_args(argv)
    return build(
        Path(args.public_dir),
        Path(args.mocks_dir) if args.mocks_dir else None,
        retitle=not args.no_retitle,
        allow_unclassified=args.allow_unclassified,
        quiet=args.quiet,
    )
