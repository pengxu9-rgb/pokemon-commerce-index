"""Build a private, matcher-blind review queue from old demo test cassettes.

The queue contains listing text and captured photo URLs. Keep it under work/;
do not distribute it with the public catalog artifact.
"""

from __future__ import annotations

import argparse
import json
import xml.etree.ElementTree as ET
from pathlib import Path


def _clean_images(values: list[object]) -> list[str]:
    result = []
    for value in values:
        if isinstance(value, str) and value.startswith("https://") and value not in result:
            result.append(value)
    return result[:12]


def build(labels_path: Path, fixture_dir: Path, output: Path) -> dict:
    if output.exists():
        raise FileExistsError(f"queue already exists: {output}")
    labels = [json.loads(line) for line in labels_path.read_text(encoding="utf-8").splitlines()]
    wanted = {(row["source"], str(row["native_id"])): row for row in labels}
    found: dict[tuple[str, str], dict] = {}
    for path in sorted(fixture_dir.glob("*cassette*.json")):
        try:
            interactions = json.loads(path.read_text(encoding="utf-8"))["interactions"]
        except (ValueError, KeyError):
            continue
        for interaction in interactions:
            request_url = interaction.get("request", {}).get("url", "")
            body = interaction.get("response", {}).get("body", "")
            if "/mercari/" in request_url:
                try:
                    payload = json.loads(body)
                except (ValueError, TypeError):
                    continue
                if not isinstance(payload, dict):
                    continue
                items = payload.get("data") if isinstance(payload.get("data"), list) else [payload]
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    key = ("mercari", str(item.get("id", "")))
                    if key not in wanted:
                        continue
                    photos = item.get("photos") if isinstance(item.get("photos"), list) else []
                    images = _clean_images(photos + [item.get("thumbnail")])
                    row = {
                        "item_key": ":".join(key), "source": key[0], "native_id": key[1],
                        "title": str(item.get("name") or ""),
                        "url": wanted[key]["url"],
                        "description": str(item.get("description") or ""),
                        "image_urls": images,
                    }
                    if key not in found or len(row["description"]) > len(found[key]["description"]):
                        found[key] = row
            elif "auctions.yahooapis.jp" in request_url:
                try:
                    tree = ET.fromstring(body)
                except (ET.ParseError, TypeError):
                    continue
                for node in tree.iter():
                    if node.tag.split("}")[-1] not in {"Item", "Result"}:
                        continue
                    fields = {child.tag.split("}")[-1]: child.text for child in node}
                    key = ("yahoo", str(fields.get("AuctionID") or ""))
                    if key not in wanted:
                        continue
                    row = {
                        "item_key": ":".join(key), "source": key[0], "native_id": key[1],
                        "title": str(fields.get("Title") or ""),
                        "url": wanted[key]["url"],
                        "description": str(fields.get("Description") or ""),
                        "image_urls": _clean_images([fields.get("Image")]),
                    }
                    if key not in found or len(row["description"]) > len(found[key]["description"]):
                        found[key] = row
    missing = sorted(set(wanted) - set(found))
    if missing:
        raise ValueError(f"{len(missing)} labeled listing IDs are absent from fixtures")
    output.parent.mkdir(parents=True, exist_ok=True)
    rows = [found[key] for key in sorted(found)]
    output.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
                      encoding="utf-8")
    return {"items": len(rows), "with_images": sum(bool(row["image_urls"]) for row in rows),
            "images": sum(len(row["image_urls"]) for row in rows), "output": str(output)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--fixtures", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.labels, args.fixtures, args.output), ensure_ascii=False))


if __name__ == "__main__":
    main()
