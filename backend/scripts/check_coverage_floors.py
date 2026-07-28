#!/usr/bin/env python
"""Fail if the money / AI / admin paths drop below their own coverage floor.

Why this exists
---------------
pytest.ini enforces ONE global gate (``--cov-fail-under=70``) over ~21.7k
statements. A global average is trivially subsidised: the well-tested CRUD
surface pays for whatever sits at 0-40 %, so a high-risk module can lose all
its tests — or arrive with none — without the gate noticing. The 2026-07-27
forensic audit found exactly that (docs/audit/2026-07-27-forensic/00-REPORT.md
finding "70 % global coverage gate hides critical modules at 0-40 %"):
``dedup_service`` at 0 %, ``transfer_service`` at 16.7 %, ``ai_settings`` at
39.6 %, all inside a package averaging 80 %.

This script re-reads the same coverage.xml the suite already writes and asserts
a floor per PATH, so a regression in the code that moves real money has to be
argued for explicitly (by lowering a number here) instead of being absorbed by
the average.

Usage
-----
    cd backend
    pytest                                   # writes coverage.xml
    python scripts/check_coverage_floors.py  # or: ... <path/to/coverage.xml>

Exit code 1 on any breach, or if a configured path matched no files at all —
a rename that silently empties a group would otherwise "pass" forever.

Maintaining the floors
----------------------
They are a ratchet, not a target: each one is a round number BELOW the value
measured on the 2026-07-27 full-suite run (recorded next to it). Raise a floor
when coverage rises; lower one only with a written reason.
"""
from __future__ import annotations

import os
import sys
import xml.etree.ElementTree as ET

# path prefix (repo-relative, as it appears under backend/) -> minimum percent
# of statements covered, aggregated over every file under that prefix.
#
# Measured 2026-07-27 (full suite, 1.7k tests):
#   app/services/budget          80.33 %  (3107/3868 statements)
#   app/services/admin           62.58 %  (194/310)
#   app/services/bank_service.py 80.74 %  (306/379)
# Floors sit a few points under those so ordinary refactoring does not turn CI
# red, while a newly-added untested service in any of them does.
FLOORS: dict[str, float] = {
    "app/services/budget": 75.0,
    "app/services/admin": 58.0,
    "app/services/bank_service.py": 75.0,
}

DEFAULT_XML = os.path.join(os.path.dirname(__file__), "..", "coverage.xml")


def repo_path(filename: str) -> str:
    """coverage.xml stores each ``filename`` relative to <sources>, which for
    this repo is the ``app`` package itself (pytest.ini: ``--cov=app``) — so
    the paths arrive as ``services/budget/x.py``. Re-attach the package name to
    get the ``app/services/budget/x.py`` form the floors are keyed on, and
    tolerate an absolute path (coverage emits those for files outside
    <sources>)."""
    norm = filename.replace(os.sep, "/")
    if norm.startswith("/"):
        i = norm.rfind("/app/")
        norm = norm[i + 1:] if i >= 0 else norm.lstrip("/")
    return norm if norm.startswith("app/") else "app/" + norm


def measure(xml_path: str) -> dict[str, tuple[int, int, list[tuple[float, str, int]]]]:
    """-> {prefix: (covered, total, [(percent, file, statements), ...])}"""
    root = ET.parse(xml_path).getroot()
    totals = {p: [0, 0, []] for p in FLOORS}

    for cls in root.iter("class"):
        path = repo_path(cls.get("filename", ""))
        for prefix in FLOORS:
            # A file path either IS the configured path or lives under it —
            # never a bare startswith, which would let app/services/adminX
            # count towards app/services/admin.
            if path != prefix and not path.startswith(prefix.rstrip("/") + "/"):
                continue
            lines = cls.find("lines")
            stmts = list(lines) if lines is not None else []
            hit = sum(1 for ln in stmts if int(ln.get("hits", "0")) > 0)
            totals[prefix][0] += hit
            totals[prefix][1] += len(stmts)
            if stmts:
                totals[prefix][2].append((100.0 * hit / len(stmts), path, len(stmts)))

    return {p: (c, t, files) for p, (c, t, files) in totals.items()}


def main(argv: list[str]) -> int:
    xml_path = argv[1] if len(argv) > 1 else DEFAULT_XML
    if not os.path.exists(xml_path):
        print(f"coverage.xml not found at {xml_path} — run pytest first")
        return 1

    results = measure(xml_path)
    failures: list[str] = []

    print(f"coverage floors ({xml_path})")
    print("-" * 70)
    for prefix, floor in sorted(FLOORS.items()):
        covered, total, files = results[prefix]
        if total == 0:
            failures.append(
                f"{prefix}: matched NO files — the path was renamed or moved, "
                f"so this floor has been silently unenforced"
            )
            print(f"  {'MISSING':>8}  {prefix}  (floor {floor:.1f} %)")
            continue
        pct = 100.0 * covered / total
        ok = pct >= floor
        print(
            f"  {pct:7.2f} %  {prefix}  "
            f"({covered}/{total} statements, floor {floor:.1f} %)"
        )
        if not ok:
            failures.append(
                f"{prefix}: {pct:.2f} % < {floor:.1f} % floor "
                f"({covered}/{total} statements)"
            )
            for fpct, fname, stmts in sorted(files)[:10]:
                print(f"        {fpct:6.2f} %  {fname} ({stmts} statements)")

    print("-" * 70)
    if not failures:
        print("coverage floors OK")
        return 0

    print("COVERAGE FLOOR FAILURE")
    for f in failures:
        print(f"  - {f}")
    print(
        "\nAdd tests for the least-covered files listed above. Lowering a floor "
        "in scripts/check_coverage_floors.py needs a written reason — these are "
        "the money, AI and cross-tenant admin paths."
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
