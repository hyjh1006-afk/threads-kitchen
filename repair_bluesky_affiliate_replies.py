# -*- coding: utf-8 -*-
"""Replace already-published final replies with monetized versions."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import bluesky_client
import bluesky_thread_content
import bluesky_thread_publisher

BASE = Path(__file__).parent
CONFIG = json.loads((BASE / "publisher_config.json").read_text(encoding="utf-8"))
MENUS = json.loads((BASE / "menus.json").read_text(encoding="utf-8"))["menus"]
PUBLISHED = BASE / "state" / "bluesky_published.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("menu_ids", nargs="*", help="Defaults to published entries without affiliate data")
    args = parser.parse_args()

    entries = json.loads(PUBLISHED.read_text(encoding="utf-8"))
    requested = set(args.menu_ids)
    targets = [
        entry for entry in entries
        if (entry["menu_id"] in requested if requested else not entry.get("affiliate"))
    ]
    if not targets:
        print("No affiliate replies need repair.")
        return 0

    menus = {menu["id"]: menu for menu in MENUS}
    client = bluesky_client.BlueskyClient.from_env()
    client.login()
    for entry in targets:
        menu = menus[entry["menu_id"]]
        copy = bluesky_thread_content.load_or_generate(menu)
        if not copy:
            raise RuntimeError(f"Validated English copy is unavailable for {entry['menu_id']}.")
        offer = bluesky_thread_publisher.affiliate_offer(menu, CONFIG)
        text = bluesky_thread_publisher.monetized_reply(copy["reply2"], offer, CONFIG)
        root = client.get_post(entry["bluesky_uri"])
        parent = client.get_post(entry["reply_uris"][0])
        replacement = client.post(
            text,
            link=offer["url"],
            reply_root=root,
            reply_parent=parent,
        )
        old_uri = entry["reply_uris"][1]
        try:
            client.delete_post(old_uri)
        except Exception:
            client.delete_post(replacement["uri"])
            raise
        entry["reply_uris"][1] = replacement["uri"]
        entry["affiliate"] = offer
        PUBLISHED.write_text(
            json.dumps(entries, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"Repaired {entry['menu_id']}: {entry['url']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
