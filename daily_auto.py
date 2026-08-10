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
REPLAY_PROGRESS = BASE / "state" / "replay_progress.json"


def log(msg: str):
    print(f"[auto] {msg}")


def replay_progress() -> dict:
    if not REPLAY_PROGRESS.exists():
        return {"account": CONFIG.get("target_threads_username", ""), "completed": []}
    try:
        data = json.loads(REPLAY_PROGRESS.read_text(encoding="utf-8"))
        if data.get("account") != CONFIG.get("target_threads_username", ""):
            return {"account": CONFIG.get("target_threads_username", ""), "completed": []}
        return data
    except Exception:
        return {"account": CONFIG.get("target_threads_username", ""), "completed": []}


def select_menu(skip_ids: set[str]) -> tuple[dict | None, bool]:
    """과거 게시물 재생이 남았으면 날짜순 메뉴, 끝났으면 새 메뉴를 선택한다."""
    replay = CONFIG.get("replay_old_posts") or {}
    if replay.get("enabled"):
        progress = replay_progress()
        completed = set(progress.get("completed") or [])
        for menu_id in replay.get("menu_ids") or []:
            if menu_id not in completed:
                menu = pick_menu(menu_id=menu_id)
                if menu:
                    return menu, True
                log(f"재생 계획의 {menu_id}를 menus.json에서 찾지 못해 건너뜀")
        log("과거 게시물 재생 완료 — 새 메뉴 은행으로 전환")
    return pick_menu(skip_ids=skip_ids), False


def mark_replay_posted(menu_id: str, body_id: str, today: str):
    progress = replay_progress()
    completed = list(progress.get("completed") or [])
    if menu_id not in completed:
        completed.append(menu_id)
    progress.update({"account": CONFIG.get("target_threads_username", ""),
                     "completed": completed, "last_date": today,
                     "last_menu": menu_id, "last_body_id": body_id})
    REPLAY_PROGRESS.parent.mkdir(exist_ok=True)
    REPLAY_PROGRESS.write_text(json.dumps(progress, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    if not CONFIG.get("auto_post", False):
        log("auto_post=false — 승인형 모드입니다. make_draft.py를 사용하세요.")
        return 0
    if not threads_client.is_configured():
        log("Threads 토큰 없음 — 초기 설정 전이므로 건너뜀 (README 참고)")
        return 0

    # 날짜는 KST 고정 — 러너(UTC)의 date.today()는 한국 아침에 어제 날짜가 되어
    # 하루 1개 잠금이 헛돈다 (7/30 크론 6연발 사건의 공범)
    from datetime import timedelta, timezone
    KST = timezone(timedelta(hours=9))
    from datetime import datetime as _dt
    today = _dt.now(KST).date().isoformat()
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
                         params={"fields": "id,username", "access_token": token}, timeout=30)
        if not r.ok:
            msg = r.json().get("error", {}).get("message", r.status_code)
            log(f"API 상태 확인 실패({msg}) — 오늘 게시 건너뜀 (차단 해제되면 자동 재개)")
            return 0
        expected = str(CONFIG.get("target_threads_username") or "").lstrip("@").lower()
        actual = str(r.json().get("username") or "").lstrip("@").lower()
        if expected and actual != expected:
            log(f"계정 불일치: 설정=@{expected}, API=@{actual or '확인불가'} — 게시 중단")
            return 0
        log(f"게시 대상 계정 확인: @{actual}")
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
    menu, replaying = select_menu(skip_ids=vetoes)
    if not menu:
        log("소재 은행 소진 — menus.json에 메뉴를 보충하세요 (실패로 처리)")
        return 1

    # 중복 게시 최종 방어선 (7/30 크론 6연발 사건): 상태 파일은 크래시·중복 크론에
    # 취약하므로, 계정의 실제 최근 글을 읽어 오늘 이 메뉴가 이미 나갔는지 확인한다.
    try:
        r = requests.get(f"https://graph.threads.net/v1.0/{uid}/threads",
                         params={"fields": "text,timestamp", "limit": 5,
                                 "access_token": token}, timeout=30)
        prefix = menu["body"][:20]
        for t in r.json().get("data", []):
            ts = _dt.fromisoformat(t["timestamp"].replace("+0000", "+00:00"))
            if (ts.astimezone(KST).date().isoformat() == today
                    and (t.get("text") or "").startswith(prefix)):
                log("오늘 이 메뉴가 이미 계정에 게시돼 있음 — 중복 방지 종료 (답글 누락 시 수동 수리)")
                return 0
    except Exception as e:
        log(f"(중복 확인 실패 — 계속 진행: {str(e)[:60]})")

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

    log(f"오늘의 메뉴: {menu['name']} ({menu['id']}) · {'과거글 재생' if replaying else '새 메뉴'}")
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

    def post_retry(label: str, **kw) -> str | None:
        """일시적 400(캐러셀 처리 지연 등) 대비 재시도 — 7/30·8/1 답글 400 사건.

        대기를 60→120→180초로 늘려가며 3회. 실측상 캐러셀 본문이 답글을 받기까지
        수 분이 걸리는 날이 있어, 짧은 재시도만으로는 부족했다.
        """
        for attempt, wait in ((1, 60), (2, 120), (3, 0)):
            try:
                return threads_client.post(**kw)
            except Exception as e:
                log(f"  {label} {attempt}차 실패: {str(e)[:160]}")
                if wait:
                    log(f"  {wait}초 후 재시도…")
                    time.sleep(wait)
        return None

    log("본문 게시…")
    body_id = post_retry("본문", text=body, image_urls=image_urls or None, topic_tag=topic)
    if not body_id:
        log("본문 게시 실패 — 종료 (계정에 올라간 것 없음)")
        return 1
    log(f"  게시됨: {body_id}")
    if replaying:
        # 본문이 이미 나갔으므로 이후 답글 단계가 실패해도 다음 날 중복 재게시하지 않는다.
        mark_replay_posted(menu["id"], body_id, today)
    delay = int(CONFIG["posting"].get("reply_delay_seconds", 45))
    time.sleep(delay)
    # 본문이 실제로 답글을 받을 수 있는 상태인지 확인 (캐러셀은 발행 후에도 처리 중).
    # 캐러셀이면 children의 media_url까지 나와야 처리 완료로 본다.
    if threads_client.wait_until_ready(body_id, expect_children=len(image_urls) if len(image_urls) > 1 else 0):
        log("  본문 처리 완료 확인 — 답글 진행")
        time.sleep(30)  # 처리 완료 직후에도 답글 연결이 불안정해 여유를 둔다
    else:
        log("  본문 처리 확인 실패 — 그래도 답글 시도")

    def reply_verified(label: str, text: str, parent: str) -> str | None:
        """답글 게시 + 부모 연결 검증. 독립 글로 새어나가면 실패로 처리하고 ID를 남긴다."""
        pid = post_retry(label, text=fit_500(text), reply_to_id=parent)
        if not pid:
            return None
        time.sleep(5)
        if threads_client.is_attached(pid, parent):
            return pid
        log(f"  ⚠ {label}이 부모에 안 붙고 독립 글로 발행됨 (id={pid}) — 수동 삭제 필요")
        return None

    log("답글1(레시피) 게시…")
    reply_id = reply_verified("답글1", reply_text, body_id)
    log(f"  게시됨: {reply_id or '실패'}")
    links_id = None
    if links_text and reply_id:
        time.sleep(delay)
        threads_client.wait_until_ready(reply_id, timeout_seconds=120)
        log("답글2(재료 링크) 게시…")
        links_id = reply_verified("답글2", links_text, reply_id)
        log(f"  게시됨: {links_id or '실패'}")

    # 답글이 실패해도 본문은 나갔으므로 상태는 반드시 커밋 — 다음 실행의 중복 게시 방지.
    # (7/30 사건: 답글 크래시로 상태 미커밋 → 다음 크론이 같은 메뉴 재게시 시도)
    mark_used(menu["id"])
    record({"date": today, "account": CONFIG.get("target_threads_username", ""),
            "menu": menu["name"], "menu_id": menu["id"], "body_id": body_id,
            "reply_id": reply_id, "links_id": links_id,
            "mode": ("replay" if replaying else "auto") if reply_id else
                    (("replay" if replaying else "auto") + "(답글 실패 — 수리 필요)"),
            "links": ok_links})
    LAST.parent.mkdir(exist_ok=True)
    LAST.write_text(
        json.dumps({"date": today, "count": posted_today + 1, "menu": menu["id"]}),
        encoding="utf-8",
    )
    # 클라우드 랩 보드용 게시 메모 — '의도된 생략'이 사고로 오해받지 않게 (2026-08-04 사용자 요청)
    notes = []
    if not links_text:
        notes.append("링크 없는 날 (의도된 생략 — 봇 패턴 완화)" if ok_links
                     else "링크 생성 실패로 답글2 없음")
    if not reply_id:
        notes.append("답글 실패 — 수리 필요")
    (BASE / "state" / "board_notice.json").write_text(
        json.dumps({"date": today, "menu": menu["name"],
                    "note": " · ".join(notes) if notes else "정상 (본문+답글 전부)"},
                   ensure_ascii=False),
        encoding="utf-8",
    )
    if not reply_id:
        log("본문만 게시됨 — 답글 수리 필요 (빨간불로 표시)")
        return 1
    log("완료")
    return 0


if __name__ == "__main__":
    sys.exit(main())
