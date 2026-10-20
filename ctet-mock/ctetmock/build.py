"""Build the CTET Mock PWA: classify the mocks, write the catalogue and the
offline service worker.

    python ctet-mock/build.py
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import catalog as catalog_mod
from . import intake
from . import sw as sw_mod

MOCKS_DIRNAME = "mocks"
CATALOG_NAME = "catalog.json"
WORKER_NAME = "sw.js"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _table(rows: list[dict], unclassified: list[dict]) -> None:
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
    for row in unclassified:
        print(f"INCOMPLETE    {row['name']}")
        print("             rename it to "
              "<paper>-<subject>-<class>-<lesson>-<mock>.html "
              "or add a .meta.json sidecar")


def build(public_dir: Path, mocks_dir: Path | None = None, retitle: bool = True,
          allow_unclassified: bool = False, quiet: bool = False) -> int:
    """Rebuild the catalogue and the offline worker. Returns a shell exit code."""
    public_dir = Path(public_dir)
    if mocks_dir is None:
        mocks_dir = public_dir / MOCKS_DIRNAME
    mocks_dir = Path(mocks_dir)
    mocks_dir.mkdir(parents=True, exist_ok=True)

    mock_files = sorted(mocks_dir.glob("*.html"))
    records = []
    actual_titles: dict[str, str] = {}
    for path in mock_files:
        html = _read(path)
        record = intake.classify(path, html, intake.load_sidecar(path))
        records.append(record)
        package = intake.read_package(html) or {}
        meta = package.get("meta") or {}
        if isinstance(meta, dict) and isinstance(meta.get("title"), str):
            actual_titles[path.name] = meta["title"]

    built = catalog_mod.build_catalog(records, version="")

    # Give every mock the title the catalogue shows, so no two mocks of the
    # same lesson share one saved session.
    title_by_file = {}
    for mock in built["mocks"]:
        title_by_file[Path(mock["file"]).name] = mock["title"]
    if retitle:
        for path in mock_files:
            new_title = title_by_file.get(path.name)
            if not new_title:
                continue
            html = _read(path)
            updated = intake.rewrite_package_title(html, new_title)
            if updated != html:
                path.write_text(updated, encoding="utf-8")
            actual_titles[path.name] = new_title

    for mock in built["mocks"]:
        name = Path(mock["file"]).name
        effective = actual_titles.get(name, mock["title"])
        mock["sessionKey"] = catalog_mod.session_key(effective)

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
                    json.dumps(hashable, sort_keys=True, ensure_ascii=False).encode("utf-8")))
    version = sw_mod.compute_version(entries)
    built["version"] = version
    built["cacheName"] = sw_mod.cache_name(version)

    (public_dir / CATALOG_NAME).write_text(
        json.dumps(built, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    precache = ["./"]
    for name in sw_mod.SHELL_FILES:
        if (public_dir / name).is_file():
            precache.append(name)
    precache.append(CATALOG_NAME)
    for path in mock_files:
        precache.append(f"{MOCKS_DIRNAME}/{path.name}")
    (public_dir / WORKER_NAME).write_text(
        sw_mod.render_service_worker(version, precache), encoding="utf-8"
    )

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
        _table(rows, incomplete)
        print(f"\n{built['counts']['mocks']} mock(s) - version {version} - "
              f"{len(precache)} files cached offline")
        missing = [name for name in sw_mod.SHELL_FILES
                   if not (public_dir / name).is_file()]
        for name in missing:
            print(f"note: shell file not found yet: {name}")

    if incomplete and not allow_unclassified:
        print("\nERROR: some mocks could not be classified. "
              "Rename them or add a .meta.json sidecar.", file=sys.stderr)
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
                        help="Do not fail when a mock cannot be classified")
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
