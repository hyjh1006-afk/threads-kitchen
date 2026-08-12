# -*- coding: utf-8 -*-
"""Publish one English recipe thread to Bluesky each scheduled day."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import bluesky_client
import bluesky_thread_publisher as recipe_publisher

BASE = Path(__file__).parent
CONFIG = json.loads((BASE / "publisher_config.json").read_text(encoding="utf-8"))
MENUS = BASE / "menus.json"
LAST = BASE / "state" / "last_publish.json"
PROGRESS = BASE / "state" / "bluesky_progress.json"
PUBLISHED = BASE / "state" / "bluesky_published.json"
KST = timezone(timedelta(hours=9))


def log(message: str) -> None:
    print(f"[publisher] {message}")


def menu_by_id(menu_id: str) -> dict | None:
    data = json.loads(MENUS.read_text(encoding="utf-8"))
    return next((menu for menu in data["menus"] if menu["id"] == menu_id), None)


def mark_used(menu_id: str) -> None:
    data = json.loads(MENUS.read_text(encoding="utf-8"))
    for menu in data["menus"]:
        if menu["id"] == menu_id:
            menu["used"] = True
    MENUS.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def progress() -> dict:
    handle = str((CONFIG.get("bluesky") or {}).get("handle") or "")
    default = {"handle": handle, "completed": []}
    if not PROGRESS.exists():
        return default
    try:
        data = json.loads(PROGRESS.read_text(encoding="utf-8"))
        return data if data.get("handle") == handle else default
    except ValueError:
        return default


def select_menu(menu_id: str | None = None) -> tuple[dict | None, bool]:
    replay_ids = CONFIG.get("replay_old_posts", {}).get("menu_ids") or []
    if menu_id:
        return menu_by_id(menu_id), menu_id in replay_ids
    if CONFIG.get("replay_old_posts", {}).get("enabled"):
        completed = set(progress().get("completed") or [])
        for candidate in replay_ids:
            if candidate not in completed:
                return menu_by_id(candidate), True
    data = json.loads(MENUS.read_text(encoding="utf-8"))
    return next((menu for menu in data["menus"] if not menu.get("used")), None), False


def save_success(menu: dict, result: dict, replaying: bool, today: str, count: int) -> None:
    if replaying:
        data = progress()
        completed = list(data.get("completed") or [])
        if menu["id"] not in completed:
            completed.append(menu["id"])
        data.update({"completed": completed, "last_date": today, "last_menu": menu["id"]})
        PROGRESS.parent.mkdir(exist_ok=True)
        PROGRESS.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    mark_used(menu["id"])
    entries = json.loads(PUBLISHED.read_text(encoding="utf-8")) if PUBLISHED.exists() else []
    entries.append({"date": today, "menu": menu["name"], "menu_id": menu["id"], **result})
    PUBLISHED.parent.mkdir(exist_ok=True)
    PUBLISHED.write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    LAST.write_text(json.dumps({"date": today, "count": count, "menu": menu["id"]}) + "\n", encoding="utf-8")
    (BASE / "state" / "board_notice.json").write_text(
        json.dumps(
            {"date": today, "menu": menu["name"], "note": "Bluesky English recipe thread published"},
            ensure_ascii=False,
        ) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--menu", help="Specific menu ID, for example m01")
    parser.add_argument("--force", action="store_true", help="Ignore today's posting limit")
    parser.add_argument("--no-generate", action="store_true", help="Do not generate missing images")
    args = parser.parse_args()

    if not CONFIG.get("auto_post", False):
        log("Automatic publishing is disabled.")
        return 0
    if not bluesky_client.is_configured():
        log("Bluesky credentials are missing.")
        return 1

    today = datetime.now(KST).date().isoformat()
    per_day = int(CONFIG.get("posting", {}).get("per_day", 1))
    posted_today = 0
    if LAST.exists():
        try:
            last = json.loads(LAST.read_text(encoding="utf-8"))
            if last.get("date") == today:
                posted_today = int(last.get("count", 1))
        except ValueError:
            pass
    if not args.force and posted_today >= per_day:
        log(f"{today}: already published {posted_today}/{per_day} threads.")
        return 0

    try:
        user = bluesky_client.BlueskyClient.from_env().login()
        log(f"Bluesky connected: {user.get('handle')}")
    except Exception as exc:
        log(str(exc))
        return 1

    menu, replaying = select_menu(args.menu)
    if not menu:
        log("No recipe remains to publish.")
        return 1
    log(f"Selected recipe: {menu['name']} ({menu['id']})")
    try:
        result = recipe_publisher.publish(menu, CONFIG, generate_images=not args.no_generate)
    except Exception as exc:
        log(f"Publish failed: {str(exc)[:300]}")
        return 1
    save_success(menu, result, replaying, today, posted_today + 1)
    log(f"Bluesky thread published: {result['url']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
