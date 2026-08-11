# -*- coding: utf-8 -*-
"""Daily recipe publisher: WordPress article, then optional Bluesky teaser."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import blog_recipe_publisher as recipe_publisher
import wordpress_com_client as wordpress_client

BASE = Path(__file__).parent
CONFIG = json.loads((BASE / "publisher_config.json").read_text(encoding="utf-8"))
MENUS = BASE / "menus.json"
LAST = BASE / "state" / "last_publish.json"
PROGRESS = BASE / "state" / "wordpress_progress.json"
PUBLISHED = BASE / "state" / "wordpress_published.json"
KST = timezone(timedelta(hours=9))


def log(message: str):
    print(f"[publisher] {message}")


def menu_by_id(menu_id: str) -> dict | None:
    data = json.loads(MENUS.read_text(encoding="utf-8"))
    return next((menu for menu in data["menus"] if menu["id"] == menu_id), None)


def mark_used(menu_id: str):
    data = json.loads(MENUS.read_text(encoding="utf-8"))
    for menu in data["menus"]:
        if menu["id"] == menu_id:
            menu["used"] = True
    MENUS.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def progress() -> dict:
    creds = wordpress_client.credentials()
    site = creds[0] if creds else ""
    default = {"site": site, "completed": []}
    if not PROGRESS.exists():
        return default
    try:
        data = json.loads(PROGRESS.read_text(encoding="utf-8"))
        return data if data.get("site") == site else default
    except Exception:
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


def save_success(menu: dict, result: dict, replaying: bool, today: str, count: int):
    if replaying:
        data = progress()
        completed = list(data.get("completed") or [])
        if menu["id"] not in completed:
            completed.append(menu["id"])
        data.update({"completed": completed, "last_date": today, "last_menu": menu["id"]})
        PROGRESS.parent.mkdir(exist_ok=True)
        PROGRESS.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    mark_used(menu["id"])
    entries = json.loads(PUBLISHED.read_text(encoding="utf-8")) if PUBLISHED.exists() else []
    entries.append({"date": today, "menu": menu["name"], "menu_id": menu["id"], **result})
    PUBLISHED.parent.mkdir(exist_ok=True)
    PUBLISHED.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
    LAST.write_text(json.dumps({"date": today, "count": count, "menu": menu["id"]}), encoding="utf-8")
    note = "WordPress 발행 완료"
    if result.get("bluesky_uri"):
        note += " · Bluesky 홍보 완료"
    elif result.get("bluesky_error"):
        note += " · Bluesky 실패(본문은 정상)"
    (BASE / "state" / "board_notice.json").write_text(
        json.dumps({"date": today, "menu": menu["name"], "note": note}, ensure_ascii=False),
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--menu", help="특정 메뉴 ID (예: m01)")
    parser.add_argument("--force", action="store_true", help="오늘 발행 잠금 무시")
    parser.add_argument("--no-generate", action="store_true", help="없는 이미지를 새로 만들지 않음")
    args = parser.parse_args()

    if not CONFIG.get("auto_post", False):
        log("auto_post=false - 자동 발행이 꺼져 있습니다.")
        return 0
    if not wordpress_client.is_configured():
        log("WordPress 연결값 없음 - 사이트 연결 전이라 안전하게 건너뜁니다.")
        return 0

    today = datetime.now(KST).date().isoformat()
    per_day = int(CONFIG.get("posting", {}).get("per_day", 1))
    posted_today = 0
    if LAST.exists():
        try:
            last = json.loads(LAST.read_text(encoding="utf-8"))
            if last.get("date") == today:
                posted_today = int(last.get("count", 1))
        except Exception:
            pass
    if not args.force and posted_today >= per_day:
        log(f"{today} 이미 {posted_today}개 발행됨 - 하루 {per_day}개 상한")
        return 0

    try:
        user = wordpress_client.WordPressClient.from_env().verify()
        log(f"WordPress 연결 확인: {user.get('name') or user.get('slug') or '사용자'}")
    except Exception as exc:
        log(str(exc))
        return 1

    menu, replaying = select_menu(args.menu)
    if not menu:
        log("발행할 메뉴가 없습니다. menus.json을 보충하세요.")
        return 1
    log(f"오늘의 메뉴: {menu['name']} ({menu['id']}) · {'과거글 재발행' if replaying else '새 메뉴'}")
    try:
        result = recipe_publisher.publish(menu, CONFIG, generate_images=not args.no_generate)
    except Exception as exc:
        log(f"발행 실패: {str(exc)[:300]}")
        return 1
    save_success(menu, result, replaying, today, posted_today + 1)
    log(f"WordPress 완료: {result['url']}")
    if result.get("bluesky_uri"):
        log(f"Bluesky 완료: {result['bluesky_uri']}")
    elif result.get("bluesky_error"):
        log(f"Bluesky만 실패(본문 정상): {result['bluesky_error']}")
    else:
        log("Bluesky 연결 전 - 홍보글은 건너뜀")
    return 0


if __name__ == "__main__":
    sys.exit(main())

