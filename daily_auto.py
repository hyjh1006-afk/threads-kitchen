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

import reviewer
import threads_client
from make_draft import CONFIG, build_reply, ensure_images, fetch_vetoes, pick_menu, with_ad_tag
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
    per_day = int(CONFIG.get("posting", {}).get("per_day", 1))
    posted_today = 0
    if LAST.exists():
        last = json.loads(LAST.read_text(encoding="utf-8"))
        if last.get("date") == today:
            posted_today = int(last.get("count", 1))  # 옛 형식({date,menu})은 1로 간주
    if posted_today >= per_day:
        log(f"{today} 이미 {posted_today}개 게시됨 — 하루 {per_day}개 상한으로 종료")
        return 0

    # API 상태 확인 (2026-07-28 메타 차단 사건 이후): 차단 중이면 조용히 건너뛰고,
    # 풀리는 날 자동으로 게시가 재개된다. 확인은 가벼운 읽기 1회뿐.
    import requests
    uid, token = threads_client.credentials()
    try:
        r = requests.get(f"https://graph.threads.net/v1.0/{uid}",
                         params={"fields": "id", "access_token": token}, timeout=30)
        if not r.ok:
            msg = r.json().get("error", {}).get("message", r.status_code)
            log(f"API 상태 확인 실패({msg}) — 오늘 게시 건너뜀 (차단 해제되면 자동 재개)")
            return 0
    except Exception as e:
        log(f"API 상태 확인 오류({str(e)[:60]}) — 오늘 게시 건너뜀")
        return 0

    # 봇 패턴 완화 (2026-07-29, 차단 사건 재발 방지):
    # ① 게시 시각 지터 — 러너 지연 위에 0~35분 랜덤을 더해 시각 패턴을 흐린다
    #    (파이프라인 HQ '지금 게시' 수동 버튼은 즉시성이 목적이라 지터 생략)
    import os
    import random
    if os.environ.get("DISPATCH_SOURCE") == "manual":
        log("수동 실행 — 지터 생략, 바로 게시")
    else:
        jitter = random.randint(0, 2100)
        log(f"지터 대기 {jitter // 60}분 — 게시 시각 랜덤화")
        time.sleep(jitter)

    vetoes = fetch_vetoes()
    if vetoes:
        log(f"폰 반려 목록: {sorted(vetoes)} — 건너뜀")
    menu = pick_menu(skip_ids=vetoes)
    if not menu:
        log("소재 은행 소진 — menus.json에 메뉴를 보충하세요 (실패로 처리)")
        return 1

    def fit_500(text: str) -> str:
        """스레드 글자수 한도(500자) 가드 — 초과 시 링크 줄부터 덜어낸다.

        실측: 첫 게시에서 원본 딥링크(300자+)로 답글이 500 에러. 단축링크로
        해결했지만, 레시피가 길어질 때를 대비한 최종 안전장치.
        안내문구(공정위) 줄은 절대 잘리지 않도록 줄 단위로 처리한다.
        """
        lines = text.split("\n")
        while len("\n".join(lines)) > 500:
            idx = max((i for i, l in enumerate(lines) if l.startswith("🛒")), default=None)
            if idx is None:
                break
            lines.pop(idx)
        return "\n".join(lines)[:500]

    def pick_topic() -> str | None:
        """주제 태그 로테이션 — 게시 수 기준으로 순환."""
        tags = CONFIG.get("topic_tags") or []
        if not tags:
            return None
        posted = 0
        rec = BASE / "state" / "posted.json"
        if rec.exists():
            posted = len(json.loads(rec.read_text(encoding="utf-8")))
        return tags[posted % len(tags)]

    log(f"오늘의 메뉴: {menu['name']} ({menu['id']})")
    image_urls = ensure_images(menu)
    body = with_ad_tag(menu["body"])
    topic = pick_topic()
    reply_text, links_text, links = build_reply(menu, include_missing=False)
    # ② 링크 없는 날 섞기 — 3일에 1일꼴로 답글2(쿠팡 링크)를 생략해 제휴 발자국을 줄인다
    if links_text and random.random() < float(CONFIG.get("link_skip_ratio", 0.33)):
        log("오늘은 링크 없는 날 — 답글2 생략 (봇 패턴 완화)")
        links_text = None
    ok_links = [l["label"] for l in links if l.get("url")]
    log(f"이미지: {len(image_urls)}장 / 주제: {topic or '없음'} / 링크: {ok_links or '없음'}")

    ok, why = reviewer.gate(today, menu["id"], body, reply_text, links_text,
                            image_urls, CONFIG["disclosure"])
    log(f"감독관 게이트: {'통과' if ok else '차단'} — {why}")
    if not ok:
        return 1  # Actions 빨간불 → 사옥 감시망이 잡음. 오늘 게시는 건너뜀

    log("본문 게시…")
    body_id = threads_client.post(body, image_urls=image_urls or None, topic_tag=topic)
    log(f"  게시됨: {body_id}")
    delay = int(CONFIG["posting"].get("reply_delay_seconds", 45))
    time.sleep(delay)
    log("답글1(레시피) 게시…")
    reply_id = threads_client.post(fit_500(reply_text), reply_to_id=body_id)
    log(f"  게시됨: {reply_id}")
    links_id = None
    if links_text:
        time.sleep(delay)
        log("답글2(재료 링크) 게시…")
        links_id = threads_client.post(fit_500(links_text), reply_to_id=reply_id)
        log(f"  게시됨: {links_id}")

    mark_used(menu["id"])
    record({"date": today, "menu": menu["name"], "body_id": body_id,
            "reply_id": reply_id, "links_id": links_id, "mode": "auto", "links": ok_links})
    LAST.parent.mkdir(exist_ok=True)
    LAST.write_text(
        json.dumps({"date": today, "count": posted_today + 1, "menu": menu["id"]}),
        encoding="utf-8",
    )
    log("완료")
    return 0


if __name__ == "__main__":
    sys.exit(main())
