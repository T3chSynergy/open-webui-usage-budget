#!/usr/bin/env python3
"""Kopiert den gemeinsamen Kern in alle Erweiterungen, die ihn enthalten.

Open WebUI lädt jede Datei einzeln; gemeinsamer Code muss deshalb in jeder
Datei stehen. Gepflegt wird er nur in shared/<name>.py zwischen den Zeilen
„# >>> <name> >>>“ und „# <<< <name> <<<“. Jede Erweiterung, die diese
Markierungen enthält, bekommt den Block unverändert.

Aufruf:
    python scripts/sync_core.py           Kopien aktualisieren
    python scripts/sync_core.py --check   nur prüfen (Rückgabe 1 bei Abweichung)
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHARED = ROOT / "shared"
TARGET_FOLDERS = ("tools", "functions/actions", "functions/filters", "functions/pipes")


def block_pattern(name: str) -> re.Pattern:
    return re.compile(
        rf"^# >>> {re.escape(name)} >>>.*?^# <<< {re.escape(name)} <<<[^\n]*\n?",
        re.MULTILINE | re.DOTALL,
    )


def shared_blocks(shared: Path = SHARED) -> dict[str, str]:
    blocks = {}
    for path in sorted(shared.glob("*.py")) if shared.is_dir() else []:
        match = block_pattern(path.stem).search(path.read_text(encoding="utf-8"))
        if match:
            text = match.group(0)
            blocks[path.stem] = text if text.endswith("\n") else text + "\n"
    return blocks


def targets(root: Path = ROOT) -> list[Path]:
    return [p for folder in TARGET_FOLDERS for p in sorted((root / folder).glob("*.py"))]


def outdated(root: Path = ROOT) -> list[tuple[Path, str]]:
    """(Datei, Name des Blocks) für alle Kopien, die vom Original abweichen."""
    result = []
    blocks = shared_blocks(root / "shared")
    for path in targets(root):
        content = path.read_text(encoding="utf-8")
        for name, block in blocks.items():
            match = block_pattern(name).search(content)
            if match and match.group(0).rstrip("\n") != block.rstrip("\n"):
                result.append((path, name))
    return result


def sync(root: Path = ROOT) -> list[Path]:
    changed = []
    blocks = shared_blocks(root / "shared")
    for path in targets(root):
        content = path.read_text(encoding="utf-8")
        updated = content
        for name, block in blocks.items():
            updated = block_pattern(name).sub(lambda _m, b=block: b, updated)
        if updated != content:
            path.write_text(updated, encoding="utf-8")
            changed.append(path)
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="nur prüfen, nichts schreiben")
    args = parser.parse_args()
    if args.check:
        stale = outdated()
        for path, name in stale:
            print(f"Veraltet: {path.relative_to(ROOT)} (Block {name})")
        return 1 if stale else 0
    for path in sync():
        print(f"Aktualisiert: {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
