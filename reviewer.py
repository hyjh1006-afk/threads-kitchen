# -*- coding: utf-8 -*-
"""감독관 게이트 — 게시 직전 검수 관문 (Lee_dogin 파이프라인 구조 이식, 2026-07-27).

2겹 구조:
  1) 하드 룰(휴리스틱): 글자수·플레이스홀더·표기 누락 등 기계적 결함 → 위반 시 무조건 차단
  2) LLM 판정(Gemini 텍스트): '심각한 문제'만 차단(block),
     스타일 지적은 경고(warnings)로 state/review_log.md에 축적만 한다.
     ⚠ Pollinations 텍스트 API는 2026-07 유료화(402 실측) — 이미지와 달리 텍스트는 Gemini 사용.
       텍스트 모델은 무료 쿼터가 살아있는 키여야 함 (검수 1콜/일 — 쿼터 영향 미미).

원칙:
  - 하드 룰은 fail-closed (기계 결함은 봐주지 않음)
  - LLM은 fail-open (검수 서비스 장애가 게시를 막으면 안 됨 — 하루 1개 원칙 보호)
  - 사용자 피드백은 review_rules.md에 축적 → LLM 프롬프트에 매번 주입 (규칙의 복리)
"""
from __future__ import annotations

import json
from pathlib import Path

BASE = Path(__file__).parent
RULES_PATH = BASE / "review_rules.md"
LOG_PATH = BASE / "state" / "review_log.md"

GEMINI_API = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"


def heuristic_check(body: str, reply: str, links_text: str | None,
                    image_urls: list[str], disclosure: str) -> list[str]:
    """기계적 결함 검사 — 하나라도 걸리면 게시 차단."""
    bad = []
    for name, text in [("본문", body), ("답글1", reply), ("답글2", links_text or "")]:
        if len(text) > 500:
            bad.append(f"{name} 500자 초과 ({len(text)}자)")
    if not body.strip():
        bad.append("본문이 비어 있음")
    if not reply.strip():
        bad.append("레시피 답글이 비어 있음")
    for name, text in [("본문", body), ("답글1", reply), ("답글2", links_text or "")]:
        if "[링크 자리" in text or "{" in text and "}" in text:
            bad.append(f"{name}에 플레이스홀더 흔적")
    if links_text and "🛒" in links_text and disclosure not in links_text:
        bad.append("링크 답글에 파트너스 표기 누락 (공정위)")
    if len(image_urls) not in (0, 1, 2, 3, 4):
        bad.append(f"이미지 수 이상 ({len(image_urls)}장)")
    return bad


def _rules() -> str:
    if RULES_PATH.exists():
        return RULES_PATH.read_text(encoding="utf-8")
    return ""


def llm_review(body: str, reply: str, links_text: str | None) -> tuple[bool, list[str]]:
    """LLM 판정. 반환: (차단 여부, 경고 목록). 서비스 장애 시 (False, [사유]) — fail-open."""
    import requests
    prompt = f"""너는 한국어 SNS 요리 계정의 게시물 검수 감독관이다.
아래 게시물 세트를 검토하고 JSON으로만 답하라: {{"block": true/false, "warnings": ["..."]}}

block=true 는 오직 심각한 문제일 때만:
- 위험한 조리법(식중독·화상 유발 등 실제 위해)
- 혐오·비하·차별 표현
- 명백한 거짓 정보
- 깨진 텍스트, 인코딩 오류, 잘린 문장, 템플릿 변수 노출

문체가 어색하다, 더 매력적으로 쓸 수 있다 같은 스타일 의견은 block이 아니라 warnings에 넣어라.
warnings는 최대 3개, 각 한 문장.

{_rules()}

[본문]
{body}

[답글1 - 레시피]
{reply}

[답글2 - 재료 링크]
{links_text or "(없음)"}"""
    from image_gen import _api_key  # 키 탐색 로직 재사용 (.env → Blogger_auto 폴백)
    key = _api_key()
    if not key:
        return False, ["(검수 LLM 키 없음 — 통과 처리)"]
    try:
        r = requests.post(GEMINI_API, params={"key": key}, json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.1},
        }, timeout=90)
        r.raise_for_status()
        content = r.json()["candidates"][0]["content"]["parts"][0]["text"]
        start, end = content.find("{"), content.rfind("}")
        verdict = json.loads(content[start:end + 1])
        return bool(verdict.get("block")), [str(w) for w in verdict.get("warnings", [])][:3]
    except Exception as e:
        msg = str(e).split("?key=")[0]  # 키 노출 방지
        return False, [f"(검수 LLM 불가 — 통과 처리: {msg[:80]})"]


def log_review(date: str, menu_id: str, blocked: bool, hard: list[str], warnings: list[str]):
    """판단 지점만 기록 (Lee_dogin의 '로그 방' 개념)."""
    LOG_PATH.parent.mkdir(exist_ok=True)
    lines = [f"## {date} {menu_id} — {'차단' if blocked else '통과'}"]
    lines += [f"- 하드 룰: {v}" for v in hard]
    lines += [f"- 경고: {w}" for w in warnings]
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n\n")


def gate(date: str, menu_id: str, body: str, reply: str, links_text: str | None,
         image_urls: list[str], disclosure: str) -> tuple[bool, str]:
    """게시 허가 여부. 반환: (허가, 사유 요약)."""
    hard = heuristic_check(body, reply, links_text, image_urls, disclosure)
    if hard:
        log_review(date, menu_id, True, hard, [])
        return False, "하드 룰 위반: " + " / ".join(hard)
    block, warnings = llm_review(body, reply, links_text)
    log_review(date, menu_id, block, [], warnings)
    if block:
        return False, "LLM 감독관 차단: " + " / ".join(warnings)
    return True, ("경고 " + str(len(warnings)) + "건 (로그 기록)") if warnings else "이상 없음"
