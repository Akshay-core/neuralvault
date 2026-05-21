#!/usr/bin/env python3
"""
Fix PEP8 blank-line requirements: ensure two blank lines before top-level
function and class definitions (and before decorator blocks for them).

Usage: python scripts/fix_blanklines_pep8.py
"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".git", "__pycache__", "venv", "env", "build", "dist"}

def process_file(path: Path) -> bool:
    changed = False
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    out_lines = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        # Check for top-level def/class (no leading spaces) or decorator at col 0
        leading = len(line) - len(line.lstrip(' '))
        if leading == 0 and (line.startswith('def ') or line.startswith('class ') or line.startswith('@')):
            # If decorator, find the block start (decorators may precede a def/class)
            start = i
            if line.startswith('@'):
                j = i + 1
                while j < n and lines[j].startswith('@'):
                    j += 1
                if j < n and (lines[j].startswith('def ') or lines[j].startswith('class ')) and (len(lines[j]) - len(lines[j].lstrip(' ')) == 0):
                    start = i
                else:
                    out_lines.append(line)
                    i += 1
                    continue
            else:
                start = i
            # count blank lines before start
            blank_count = 0
            k = start - 1
            while k >= 0 and lines[k].strip() == '':
                blank_count += 1
                k -= 1
            need = 2 - blank_count
            if need > 0:
                out_lines.extend([''] * need)
                changed = True
            out_lines.append(line)
            i += 1
        else:
            out_lines.append(line)
            i += 1
    new_text = '\n'.join(out_lines) + ("\n" if text.endswith('\n') else "")
    if new_text != text:
        path.write_text(new_text, encoding='utf-8')
        return True
    return False


def should_skip(dirpath: str) -> bool:
    parts = set(Path(dirpath).parts)
    return bool(parts & SKIP_DIRS)


def main():
    modified = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        if should_skip(dirpath):
            continue
        if '.git' in dirpath:
            continue
        for fname in filenames:
            if not fname.endswith('.py'):
                continue
            fpath = Path(dirpath) / fname
            if fpath.resolve() == Path(__file__).resolve():
                continue
            try:
                if process_file(fpath):
                    modified.append(str(fpath.relative_to(ROOT)))
            except Exception:
                pass
    if modified:
        print('Modified files:')
        for m in modified:
            print(m)
    else:
        print('No changes made')

if __name__ == '__main__':
    main()
