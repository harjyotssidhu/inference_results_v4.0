#!/usr/bin/env python3
"""
Create a CSV inventory of all files in a repository directory.

Columns:
- path (relative to repo root)
- filename
- extension
- size_bytes
- line_count (None for non-text/binary)
- sha256 (optional via --include-sha256)

Usage examples (run from repo root):
  python make_repo_inventory.py
  python make_repo_inventory.py --out repo_file_inventory.csv
  python make_repo_inventory.py --include-sha256
  python make_repo_inventory.py --include-hidden --exclude-dirs .git .github
"""

import os
import csv
import sys
import argparse
import hashlib
from typing import Iterable, Set

# ---------- Defaults tuned for big repos ----------
DEFAULT_EXCLUDE_DIRS: Set[str] = {
    ".git", ".hg", ".svn", "__pycache__", "node_modules", ".venv", "venv",
    ".mypy_cache", ".pytest_cache", ".idea", ".vscode",
    "build", "dist", "target", "out",
    # MLPerf-ish bulky areas (adjust as needed if you want them)
    "logs", "log", "artifacts", "results", "extern", "external",
}

# Treat these as likely binary (skip line counts)
BINARY_EXT_HINTS = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".tiff", ".webp",
    ".pdf", ".zip", ".gz", ".bz2", ".xz", ".7z", ".rar", ".tar",
    ".mp3", ".wav", ".flac", ".ogg",
    ".mp4", ".mov", ".avi", ".mkv", ".webm",
    ".woff", ".woff2", ".ttf", ".otf",
    ".exe", ".dll", ".so", ".dylib", ".bin", ".class", ".o", ".a",
    ".pb", ".onnx", ".plan", ".npy", ".npz"
}

# Treat these as likely text
TEXT_EXT_HINTS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".go", ".rb", ".rs",
    ".c", ".cc", ".cpp", ".h", ".hpp", ".cs", ".php",
    ".html", ".css", ".md", ".rst",
    ".yml", ".yaml", ".toml", ".json", ".xml", ".ini", ".cfg",
    ".txt", ".log", ".sh", ".ps1", ".sql", ".R", ".ipynb", ".kt", ".kts",
    ".makefile", "makefile", ".mk", ".cmake"
}

def guess_is_text_file(path: str, sample_bytes: int = 2048) -> bool:
    """
    Heuristic to decide if a file is text:
    - Extension hints (fast path)
    - Fallback: read a small chunk and look for NULs, decode as UTF-8
    """
    ext = os.path.splitext(path)[1].lower()
    if ext in TEXT_EXT_HINTS:
        return True
    if ext in BINARY_EXT_HINTS:
        return False
    try:
        with open(path, "rb") as f:
            chunk = f.read(sample_bytes)
        if not chunk:
            return True  # empty file -> treat as text
        if b"\x00" in chunk:
            return False
        # try decode
        try:
            chunk.decode("utf-8")
            return True
        except UnicodeDecodeError:
            return False
    except Exception:
        return False

def safe_line_count(path: str) -> int:
    if not guess_is_text_file(path):
        return None
    # Skip extremely large files for performance
    try:
        if os.path.getsize(path) > 50 * 1024 * 1024:  # 50 MB
            return None
    except Exception:
        pass
    for enc in ("utf-8", "latin-1"):
        try:
            with open(path, "r", encoding=enc, errors="ignore") as f:
                return sum(1 for _ in f)
        except Exception:
            continue
    return None

def file_sha256(path: str, blocksize: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(blocksize), b""):
            h.update(chunk)
    return h.hexdigest()

def normalize_excludes(user_excludes: Iterable[str]) -> Set[str]:
    # allow both absolute and relative names; we compare last path segment
    cleaned = set()
    for item in user_excludes:
        cleaned.add(os.path.basename(item.rstrip("/\\")))
    return cleaned

def main():
    ap = argparse.ArgumentParser(description="Create CSV inventory of repository files.")
    ap.add_argument("--repo", default=".", help="Path to the repository root (default: .)")
    ap.add_argument("--out", default="repo_file_inventory.csv", help="Output CSV filename")
    ap.add_argument("--include-hidden", action="store_true", help="Include hidden files/dirs (.*)")
    ap.add_argument("--exclude-dirs", nargs="*", default=[], help="Additional directories to exclude")
    ap.add_argument("--include-sha256", action="store_true", help="Include sha256 column (slower)")
    ap.add_argument("--follow-symlinks", action="store_true", help="Follow symlinks during walk")
    args = ap.parse_args()

    repo_dir = os.path.abspath(args.repo)
    if not os.path.isdir(repo_dir):
        print(f"Error: --repo '{args.repo}' is not a directory", file=sys.stderr)
        sys.exit(1)

    exclude_dirs = set(DEFAULT_EXCLUDE_DIRS) | normalize_excludes(args.exclude_dirs)

    rows = []
    for root, dirs, files in os.walk(repo_dir, followlinks=args.follow_symlinks):
        # prune dirs
        pruned = []
        for d in dirs:
            if d in exclude_dirs:
                continue
            if not args.include_hidden and d.startswith("."):
                continue
            pruned.append(d)
        dirs[:] = pruned

        for fname in files:
            if not args.include_hidden and fname.startswith("."):
                continue

            fpath = os.path.join(root, fname)
            if not os.path.isfile(fpath):
                continue

            rel_path = os.path.relpath(fpath, repo_dir).replace("\\", "/")
            try:
                size_bytes = os.path.getsize(fpath)
            except OSError:
                size_bytes = None

            ext = os.path.splitext(fname)[1].lower() or ""
            line_count = safe_line_count(fpath)

            sha = None
            if args.include_sha256:
                try:
                    sha = file_sha256(fpath)
                except Exception:
                    sha = None

            rows.append({
                "path": rel_path,
                "filename": fname,
                "extension": ext,
                "size_bytes": size_bytes,
                "line_count": line_count,
                "sha256": sha
            })

    # write CSV
    fieldnames = ["path", "filename", "extension", "size_bytes", "line_count"]
    if args.include_sha256:
        fieldnames.append("sha256")

    with open(args.out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Saved {len(rows)} rows to {args.out}")

if __name__ == "__main__":
    main()