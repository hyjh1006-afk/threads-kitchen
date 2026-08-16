# -*- coding: utf-8 -*-
"""Publish one English recipe thread to Bluesky each scheduled day."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import bluesky_client
import bluesky_thread_content
import bluesky_thread_publisher as recipe_publisher

BASE = Path(__file__).parent
CONFIG = json.loads((BASE / "publisher_config.json").read_text(encoding="utf-8"))
MENUS = BASE / "menus.json"
LAST = BASE / "state" / "last_publish.json"
PROGRESS = BASE / "state" / "bluesky_progress.json"
PUBLISHED = BASE / "state" / "bluesky_published.json"
ATTEMPTS = BASE / "state" / "publish_attempts.json"
NOTICE = BASE / "state" / "board_notice.json"
KST = timezone(timedelta(hours=9))
DEFAULT_MAX_ATTEMPTS = 3


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


def publish_order() -> list[tuple[dict, bool]]:
    """앞으로 발행될 순서 그대로 (메뉴, 재방송여부) 목록.

    발행에 실패한 날은 어떤 상태도 갱신되지 않으므로, 밀린 메뉴가 사라지지 않고
    맨 앞에 그대로 남는다 — 즉 중단됐던 지점부터 순서대로 이어서 나간다.
    """
    ordered: list[tuple[dict, bool]] = []
    replay = CONFIG.get("replay_old_posts", {})
    if replay.get("enabled"):
        completed = set(progress().get("completed") or [])
        for candidate in replay.get("menu_ids") or []:
            if candidate not in completed:
                menu = menu_by_id(candidate)
                if menu:
                    ordered.append((menu, True))
    chosen = {menu["id"] for menu, _ in ordered}
    for menu in json.loads(MENUS.read_text(encoding="utf-8"))["menus"]:
        if not menu.get("used") and menu["id"] not in chosen:
            ordered.append((menu, False))
    return ordered


def select_menu(menu_id: str | None = None) -> tuple[dict | None, bool]:
    if menu_id:
        replay_ids = CONFIG.get("replay_old_posts", {}).get("menu_ids") or []
        return menu_by_id(menu_id), menu_id in replay_ids
    order = publish_order()
    return order[0] if order else (None, False)


def attempts_today(today: str) -> int:
    if not ATTEMPTS.exists():
        return 0
    try:
        data = json.loads(ATTEMPTS.read_text(encoding="utf-8"))
    except ValueError:
        return 0
    return int(data.get("attempts", 0)) if data.get("date") == today else 0


def max_attempts() -> int:
    return int(CONFIG.get("posting", {}).get("max_attempts_per_day", DEFAULT_MAX_ATTEMPTS))


def record_failure(today: str, reason: str, menu: dict | None = None) -> None:
    """실패를 상태로 남긴다 — 쿼터 자폭 루프 차단(상한 계산)과 실패 가시화를 겸한다.

    8/14~8/16 사고: 실패가 아무 흔적을 남기지 않아 게이트가 하루 종일 재시도했고,
    커밋 메시지는 '발행 기록'이라 3일간 정상으로 오해됐다.
    """
    count = attempts_today(today) + 1
    ATTEMPTS.parent.mkdir(exist_ok=True)
    ATTEMPTS.write_text(
        json.dumps({"date": today, "attempts": count, "max": max_attempts(),
                    "menu": (menu or {}).get("id"), "last_error": reason[:300]},
                   ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    NOTICE.write_text(
        json.dumps({"date": today, "menu": (menu or {}).get("name"),
                    "note": f"발행 실패 {count}/{max_attempts()} — {reason[:200]}"},
                   ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    log(f"실패 기록 {count}/{max_attempts()}: {reason[:200]}")


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
    NOTICE.write_text(
        json.dumps(
            {"date": today, "menu": menu["name"], "note": "Bluesky English recipe thread published"},
            ensure_ascii=False,
        ) + "\n",
        encoding="utf-8",
    )
    ATTEMPTS.write_text(
        json.dumps({"date": today, "attempts": 0, "max": max_attempts(),
                    "menu": menu["id"], "last_error": ""}, ensure_ascii=False) + "\n",
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
    today = datetime.now(KST).date().isoformat()
    if not bluesky_client.is_configured():
        record_failure(today, "Bluesky 자격증명 없음 (BLUESKY_HANDLE / BLUESKY_APP_PASSWORD)")
        return 1

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

    # 하루 재시도 상한 — 15분 크론이 하루 종일 재시도하며 Gemini 일일 쿼터(20회)를
    # 스스로 태워버린 8/14 사고 재발 방지. 상한에 걸리면 조용히 종료해 내일 몫을 남긴다.
    tried = attempts_today(today)
    if not args.force and tried >= max_attempts():
        log(f"{today}: 오늘 이미 {tried}/{max_attempts()}회 실패 — 재시도 중단 (내일 재개)")
        return 0

    try:
        user = bluesky_client.BlueskyClient.from_env().login()
        log(f"Bluesky connected: {user.get('handle')}")
    except Exception as exc:
        record_failure(today, f"Bluesky 로그인 실패: {exc}")
        return 1

    menu, replaying = select_menu(args.menu)
    if not menu:
        record_failure(today, "발행할 레시피가 없음 — menus.json 보충 필요")
        return 1
    log(f"Selected recipe: {menu['name']} ({menu['id']})")
    try:
        result = recipe_publisher.publish(menu, CONFIG, generate_images=not args.no_generate)
    except Exception as exc:
        detail = str(exc)[:300]
        if bluesky_thread_content.LAST_ERROR:
            detail += f" | 생성 단계: {bluesky_thread_content.LAST_ERROR}"
        record_failure(today, detail, menu)
        return 1
    save_success(menu, result, replaying, today, posted_today + 1)
    log(f"Bluesky thread published: {result['url']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
