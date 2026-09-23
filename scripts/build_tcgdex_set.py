"""Build one pinned Japanese set catalog from TCGdex's public GitHub source.

Requires authenticated GitHub CLI. Fetches TypeScript metadata only; images
are never requested. Output defaults to internal matching (display disabled).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
from collections import Counter
from pathlib import Path

from pokemon_index.tcgdex_source import parse_card_source, parse_set_source

OWNER = "tcgdex"
REPO = "cards-database"


def _gh(*args: str) -> dict | list:
    for attempt in range(3):
        try:
            result = subprocess.run(["gh", "api", *args], capture_output=True, text=True,
                                    timeout=90, check=True)
            return json.loads(result.stdout)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            if isinstance(exc, subprocess.CalledProcessError) and "rate limit" in (exc.stderr or "").lower():
                raise RuntimeError("GitHub API rate limit reached") from exc
            if attempt == 2:
                if isinstance(exc, subprocess.TimeoutExpired):
                    detail = "request timeout"
                else:
                    detail = f"exit {exc.returncode}: {(exc.stderr or '').strip()[:160]}"
                raise RuntimeError(f"GitHub API request failed after three attempts ({detail})") from exc
            time.sleep(2 ** attempt)
    raise RuntimeError("unreachable GitHub retry state")


def _fetch_blobs(revision: str, paths: list[str], cache_dir: Path | None = None) -> dict[str, str]:
    cached = {}
    missing = []
    for path in paths:
        if not path.startswith("data-asia/") or ".." in Path(path).parts:
            raise ValueError("source path is outside data-asia")
        cache_path = cache_dir / revision / path if cache_dir else None
        if cache_path and cache_path.exists():
            cached[path] = cache_path.read_text(encoding="utf-8")
        else:
            missing.append(path)
    if not missing:
        return cached
    aliases = {f"f{index}": path for index, path in enumerate(missing)}
    fields = " ".join(
        f'{alias}:object(expression:"{revision}:{path}"){{... on Blob{{text}}}}'
        for alias, path in aliases.items()
    )
    query = f'query{{repository(owner:"{OWNER}",name:"{REPO}"){{{fields}}}}}'
    response = _gh("graphql", "-f", f"query={query}")
    if response.get("errors"):
        raise ValueError(f"GitHub GraphQL returned {len(response['errors'])} errors")
    blobs = response.get("data", {}).get("repository") or {}
    result = {}
    for alias, path in aliases.items():
        value = blobs.get(alias)
        if not isinstance(value, dict) or not isinstance(value.get("text"), str):
            raise ValueError(f"GitHub did not return text for {path}")
        result[path] = value["text"]
        if cache_dir:
            cache_path = cache_dir / revision / path
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(value["text"], encoding="utf-8")
    return cached | result


def build(set_path: str, revision: str, output: Path, audit_path: Path,
          max_cards: int | None, batch_size: int, cache_dir: Path | None = None) -> dict:
    if not re.fullmatch(r"data-asia/[A-Za-z0-9-]+/[A-Za-z0-9-]+", set_path):
        raise ValueError("set_path must be data-asia/<series>/<set>")
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("revision must be a full commit SHA")
    if not 1 <= batch_size <= 20:
        raise ValueError("batch_size must be between 1 and 20")
    if output.exists() or audit_path.exists():
        raise FileExistsError("output and audit paths must not exist")
    contents = _gh(f"repos/{OWNER}/{REPO}/contents/{set_path}?ref={revision}")
    if not isinstance(contents, list):
        raise ValueError("GitHub directory listing is not an array")
    paths = sorted(item["path"] for item in contents
                   if item.get("type") == "file" and item.get("name", "").endswith(".ts"))
    if not paths:
        raise ValueError("set directory has no TypeScript card files")
    total_source_files = len(paths)
    if max_cards is not None:
        if max_cards <= 0:
            raise ValueError("max_cards must be positive")
        paths = paths[:max_cards]
    header_path = f"{set_path}.ts"
    header = _fetch_blobs(revision, [header_path], cache_dir)[header_path]
    set_id, official_count = parse_set_source(header)
    if set_id != Path(set_path).name:
        raise ValueError("set id in source differs from path")
    rows = []
    errors = []
    for offset in range(0, len(paths), batch_size):
        batch = paths[offset:offset + batch_size]
        blobs = _fetch_blobs(revision, batch, cache_dir)
        for path in batch:
            try:
                rows.extend(parse_card_source(blobs[path], set_id=set_id,
                                              official_count=official_count,
                                              path=path, revision=revision))
            except ValueError as exc:
                errors.append({"path": path, "reason": str(exc)})
    identities = [(row["language"], row["set_code"], row["collector_number"], row["variant"])
                  for row in rows]
    if len(identities) != len(set(identities)):
        raise ValueError("duplicate normalized card identity across source files")
    audit = {
        "source": f"https://github.com/{OWNER}/{REPO}/tree/{revision}/{set_path}",
        "license": f"https://github.com/{OWNER}/{REPO}/blob/{revision}/LICENSE",
        "set_id": set_id, "official_card_count": official_count,
        "source_files_total": total_source_files, "source_files_fetched": len(paths),
        "source_files_parsed": len(paths) - len(errors),
        "normalized_printings": len(rows),
        "collector_number_format": "three_digit_minimum",
        "variant_counts": dict(Counter(row["variant"] for row in rows)),
        "display_approved": False, "errors": errors,
    }
    with output.open("x", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    with audit_path.open("x", encoding="utf-8") as handle:
        json.dump(audit, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return audit


def main() -> None:
    parser = argparse.ArgumentParser(description="Build pinned Japanese card metadata from TCGdex")
    parser.add_argument("--set-path", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--audit", required=True)
    parser.add_argument("--max-cards", type=int)
    parser.add_argument("--batch-size", type=int, default=20)
    parser.add_argument("--cache-dir", type=Path)
    args = parser.parse_args()
    print(json.dumps(build(args.set_path, args.revision, Path(args.output),
                           Path(args.audit), args.max_cards, args.batch_size, args.cache_dir),
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
