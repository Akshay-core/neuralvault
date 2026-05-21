# Akshay-core
__author__ = "Akshay-core"

from pathlib import Path


OWNER = "Akshay-core"
AUTHOR_LINE = '__author__ = "Akshay-core"'
ROOT = Path(__file__).resolve().parent.parent
TARGET_DIRS = [
    "analytics",
    "app",
    "orchestration",
    "plugins",
    "runtime",
    "scripts",
    "security",
    "tests",
    "users",
    "voice",
    "workflows",
]
TARGET_FILES = ["run.py"]


def _insert_index(lines: list[str]) -> int:
    idx = 0
    if lines and lines[0].startswith("#!"):
        idx = 1
    if len(lines) > idx and "coding" in lines[idx].lower():
        idx += 1
    while len(lines) > idx and not lines[idx].strip():
        idx += 1
    if len(lines) > idx and lines[idx].lstrip().startswith(('"""', "'''")):
        quote = lines[idx].lstrip()[:3]
        idx += 1
        while idx < len(lines) and quote not in lines[idx]:
            idx += 1
        if idx < len(lines):
            idx += 1
    while len(lines) > idx and lines[idx].startswith("from __future__ import"):
        idx += 1
    return idx


def watermark_file(path: Path) -> bool:
    text = path.read_text(encoding="utf-8", errors="ignore")
    if OWNER in text and AUTHOR_LINE in text:
        return False
    lines = text.splitlines()
    insert_at = _insert_index(lines)
    block = []
    if OWNER not in text:
        block.append(f"# {OWNER}")
    if AUTHOR_LINE not in text:
        block.append(AUTHOR_LINE)
    block.append("")
    lines[insert_at:insert_at] = block
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return True


def iter_targets():
    for folder in TARGET_DIRS:
        root = ROOT / folder
        if root.exists():
            yield from root.rglob("*.py")
    for filename in TARGET_FILES:
        path = ROOT / filename
        if path.exists():
            yield path


def main() -> int:
    changed = 0
    for path in sorted(set(iter_targets())):
        if "__pycache__" in path.parts:
            continue
        if watermark_file(path):
            changed += 1
    print(f"Akshay-core watermark applied to {changed} files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
