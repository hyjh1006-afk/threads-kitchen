# -*- coding: utf-8 -*-
"""승인된 초안을 실제로 게시 (승인형 워크플로 2단계).

사용: python post_approved.py --yes [--date YYYY-MM-DD]
--yes 없이는 절대 게시하지 않는다. 게시 = 외부 전송이므로 사용자가 초안을
확인한 뒤 직접 실행하는 것이 원칙이다.

동작: 본문 게시 → reply_delay_seconds 대기 → 답글(레시피+링크) 게시 → 기록.
"""
import argparse
import json
import time
from datetime import date
from pathlib import Path

import threads_client

BASE = Path(__file__).parent
CONFIG = json.loads((BASE / "config.json").read_text(encoding="utf-8"))
STATE = BASE / "state" / "posted.json"


def mark_used(menu_id: str):
    p = BASE / "menus.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    for m in data["menus"]:
        if m["id"] == menu_id:
            m["used"] = True
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def record(entry: dict):
    log = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else []
    log.append(entry)
    STATE.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--yes", action="store_true", help="게시 승인 (필수)")
    ap.add_argument("--date", default=date.today().isoformat())
    args = ap.parse_args()

    draft_path = BASE / "drafts" / f"{args.date}.json"
    if not draft_path.exists():
        print(f"초안이 없습니다: {draft_path.name} — 먼저 python make_draft.py")
        return
    draft = json.loads(draft_path.read_text(encoding="utf-8"))

    if not args.yes:
        print("미리보기 모드 (게시 안 함). 게시하려면 --yes")
        print("본문:", draft["body_text"][:80].replace("\n", " / "), "…")
        return
    if draft.get("status") == "POSTED":
        print("이미 게시된 초안입니다.")
        return
    if not threads_client.is_configured():
        print("Threads 토큰이 없습니다 — README의 '연결 1회 설정' 참고")
        return
    missing = [l["label"] for l in draft["links"] if not l.get("url")]
    if missing:
        print(f"경고: 링크 미생성 재료 {missing} — 이대로 게시하면 링크 자리 문구가 노출됩니다.")
        print("계속하려면 초안 JSON에서 reply_text를 수정하거나 파트너스 키를 설정 후 make_draft를 다시 실행하세요.")
        return

    print("1/2 본문 게시 중…")
    body_id = threads_client.post(draft["body_text"], image_url=draft.get("image_url"))
    print("   게시됨:", body_id)
    delay = int(CONFIG["posting"].get("reply_delay_seconds", 45))
    print(f"   {delay}초 대기 후 답글…")
    time.sleep(delay)
    print("2/2 답글(레시피+링크) 게시 중…")
    reply_id = threads_client.post(draft["reply_text"], reply_to_id=body_id)
    print("   게시됨:", reply_id)

    draft["status"] = "POSTED"
    draft["body_post_id"] = body_id
    draft["reply_post_id"] = reply_id
    draft_path.write_text(json.dumps(draft, ensure_ascii=False, indent=2), encoding="utf-8")
    mark_used(draft["menu_id"])
    record({"date": args.date, "menu": draft["menu_name"], "body_id": body_id, "reply_id": reply_id})
    print("완료. 성과는 스레드 인사이트에서 확인 → 수익은 파트너스 리포트 기준으로 랩에 기록하세요.")


if __name__ == "__main__":
    main()
