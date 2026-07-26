# -*- coding: utf-8 -*-
"""완전 자동 모드 — 매일 1회 실행: 초안 생성 → 이미지 → 게시 → 답글 → 기록.

사용자가 자동 업로드를 명시 승인함 (2026-07-26). 끄려면 config.json의
"auto_post": false 로 바꾸면 즉시 승인형(make_draft + post_approved)으로 돌아간다.

안전 규칙:
- 하루 1개만 (state/last_auto.json으로 이중 실행 방지)
- 링크 생성 실패 재료는 답글에서 생략 (자리 문구 노출 사고 방지)
- 이미지 실패 시 텍스트-온리로 진행 (게시가 막히지 않음)
- Threads 토큰 없으면 아무것도 하지 않고 종료 코드 0 (스케줄러 에러 스팸 방지)
"""
import json
import sys
import time
from datetime import date
from pathlib import Path

import threads_client
from make_draft import CONFIG, build_reply, ensure_image, pick_menu, with_ad_tag
from post_approved import mark_used, record

BASE = Path(__file__).parent
LAST = BASE / "state" / "last_auto.json"


def log(msg: str):
    print(f"[auto] {msg}")


def main() -> int:
    if not CONFIG.get("auto_post", False):
        log("auto_post=false — 승인형 모드입니다. make_draft.py를 사용하세요.")
        return 0
    if not threads_client.is_configured():
        log("Threads 토큰 없음 — 초기 설정 전이므로 건너뜀 (README 참고)")
        return 0

    today = date.today().isoformat()
    if LAST.exists() and json.loads(LAST.read_text(encoding="utf-8")).get("date") == today:
        log(f"{today} 이미 게시됨 — 하루 1개 원칙으로 종료")
        return 0

    menu = pick_menu()
    if not menu:
        log("소재 은행 소진 — menus.json에 메뉴를 보충하세요 (실패로 처리)")
        return 1

    log(f"오늘의 메뉴: {menu['name']} ({menu['id']})")
    image_url = ensure_image(menu)
    body = with_ad_tag(menu["body"])
    reply_text, links = build_reply(menu, include_missing=False)
    ok_links = [l["label"] for l in links if l.get("url")]
    log(f"이미지: {'있음' if image_url else '없음(텍스트 게시)'} / 링크: {ok_links or '없음'}")

    log("본문 게시…")
    body_id = threads_client.post(body, image_url=image_url)
    log(f"  게시됨: {body_id}")
    delay = int(CONFIG["posting"].get("reply_delay_seconds", 45))
    time.sleep(delay)
    log("답글 게시…")
    reply_id = threads_client.post(reply_text, reply_to_id=body_id)
    log(f"  게시됨: {reply_id}")

    mark_used(menu["id"])
    record({"date": today, "menu": menu["name"], "body_id": body_id,
            "reply_id": reply_id, "mode": "auto", "links": ok_links})
    LAST.parent.mkdir(exist_ok=True)
    LAST.write_text(json.dumps({"date": today, "menu": menu["id"]}), encoding="utf-8")
    log("완료")
    return 0


if __name__ == "__main__":
    sys.exit(main())
