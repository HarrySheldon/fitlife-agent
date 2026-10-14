"""Digest-only provenance; never expose source text or workspace diffs."""
import hashlib
import json
from pathlib import Path


def source_digest():
    root = Path(__file__).resolve().parents[2]
    digest = hashlib.sha256()
    for path in sorted((root / "backend").rglob("*")):
        if not path.is_file() or path.suffix not in {".py", ".json", ".yaml", ".yml", ".md", ".txt"} or any(part in {"data", "__pycache__"} for part in path.relative_to(root).parts):
            continue
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def prompt_digest():
    root = Path(__file__).resolve().parents[1] / "agent"
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix in {".py", ".md", ".txt"}:
            digest.update(path.relative_to(root).as_posix().encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def catalog_digest():
    root = Path(__file__).resolve().parents[1] / "data"
    digest = hashlib.sha256()
    for directory in (root / "catalog", root / "safety"):
        if directory.exists():
            for path in sorted(directory.rglob("*")):
                if path.is_file() and path.suffix in {".json", ".yaml", ".yml", ".csv"}:
                    digest.update(path.relative_to(root).as_posix().encode())
                    digest.update(path.read_bytes())
    return digest.hexdigest()
