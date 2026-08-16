# -*- coding: utf-8 -*-
"""Generate and cache grounded English three-post recipe threads."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

import requests

import image_gen

BASE = Path(__file__).parent
CACHE_DIR = BASE / "bluesky_threads"
MODEL = "gemini-2.5-flash"
API = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
FIELDS = ("main", "reply1", "reply2", "alt_text")
# Bluesky 300자에서 제휴 푸터(빈 줄 + 고지문 69자 + "\n🛒 " + 단축링크 37자 = 111자)를
# 뺀 189자가 실제 여유. 링크 길이가 흔들릴 경우를 대비해 4자를 남긴다.
# tests/test_bluesky_thread.py 가 이 값과 실제 푸터 길이의 정합성을 검사한다.
MAX_METHOD_CHARS = 185
NUMBER_RE = r"\d+(?:\.\d+)?"

# 2026-08-16 사고: maxOutputTokens 2048 을 사고(thinking) 토큰이 거의 다 소비해
# finishReason=MAX_TOKENS 로 JSON이 잘려 파싱이 실패했다 (실측: thoughts 1962/2048).
# 이 작업은 추론이 필요 없는 번역·요약이므로 사고 예산을 0으로 두고 출력만 넉넉히 준다.
GENERATION_CONFIG = {
    "temperature": 0.35,
    "maxOutputTokens": 4096,
    "thinkingConfig": {"thinkingBudget": 0},
}
RETRY_STATUS = (429, 500, 503)
LAST_ERROR = ""  # 마지막 생성 실패 사유 (로그·상태 파일용)


def _extract_json(text: str) -> dict | None:
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        return json.loads(text[start:end + 1], strict=False)
    except ValueError:
        return None


def _source_numbers(source: str) -> set[str]:
    """원문이 '허용하는' 숫자 집합.

    한국어 수량 표현을 영어로 옮기면 표기가 달라진다 — 지어낸 수치가 아닌데도
    차단되던 오탐을 막는다 (실측: '반 스푼' → '0.5 spoon', '1.5스푼' → '1 and a half').
    """
    numbers = set(re.findall(NUMBER_RE, source))
    for token in list(numbers):
        if "." in token:
            numbers.add(str(int(float(token))))  # 1.5 → 1
    for word, decimals in (("반", ("0.5",)), ("절반", ("0.5",)),
                           ("4분의 1", ("0.25",)), ("3분의 1", ("0.33",)),
                           ("4분의 3", ("0.75",))):
        if word in source:
            numbers.update(decimals)
    # 같은 수량의 단위만 바꾼 표기도 허용 — "1분 30초" → "1.5 minutes" 또는 "90 seconds"
    for pattern in (r"(\d+)분\s*(\d+)초", r"(\d+)시간\s*(\d+)분"):
        for whole, part in re.findall(pattern, source):
            numbers.add(f"{int(whole) + int(part) / 60:g}")
            numbers.add(str(int(whole) * 60 + int(part)))
    return numbers


def _trim_to_limit(text: str, limit: int) -> str:
    """한도를 넘으면 문장 단위로 뒤에서 덜어낸다 — 문장 중간은 절대 자르지 않는다.

    모델이 길이 지시를 자주 어기는데(실측 175~329자), 그때마다 재생성하면
    Gemini 일일 한도만 태운다. 호출 없이 결정론적으로 맞춘다.
    """
    text = text.strip()
    if len(text) <= limit:
        return text
    kept = ""
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        candidate = f"{kept} {sentence}".strip()
        if len(candidate) > limit:
            break
        kept = candidate
    return kept


def _invalid_reason(data: dict | None, source: str) -> str | None:
    """검증 실패 사유를 한 줄로 돌려준다 (통과하면 None).

    사유를 남기는 이유: 실패가 조용히 None으로 삼켜지면 Actions 로그만 봐서는
    쿼터 문제인지 문구 문제인지 구분할 수 없다 (8/14~8/16 3일 정지 사고).
    """
    if not isinstance(data, dict) or any(not isinstance(data.get(k), str) for k in FIELDS):
        return "필드 누락 또는 문자열 아님"
    posts = [data["main"].strip(), data["reply1"].strip(), data["reply2"].strip()]
    for name, text in zip(("main", "reply1", "reply2"), posts):
        if not text:
            return f"{name} 비어 있음"
        if len(text) > 300:
            return f"{name} {len(text)}자 — Bluesky 300자 초과"
    if len(posts[2]) > MAX_METHOD_CHARS:
        return f"reply2 {len(posts[2])}자 — 제휴 문구 자리 확보 한도 {MAX_METHOD_CHARS}자 초과"
    joined = " ".join(posts)
    if re.search(r"[가-힣]", joined):
        return "한국어가 남아 있음"
    if "http://" in joined or "https://" in joined:
        return "본문에 URL 포함 (링크는 제휴 문구에서만)"
    if len(data["alt_text"].strip()) > 1000:
        return "alt_text 1000자 초과"
    extra = set(re.findall(NUMBER_RE, joined)) - _source_numbers(source)
    if extra:
        return f"원문에 없는 숫자 {sorted(extra)} — 지어낸 수치 차단"
    return None


def _valid(data: dict | None, source: str) -> bool:
    return _invalid_reason(data, source) is None


def _prompt(menu: dict) -> str:
    source = json.dumps(
        {"name": menu["name"], "intro": menu["body"], "verified_recipe": menu["recipe"]},
        ensure_ascii=False,
        indent=2,
    )
    return f"""Turn the Korean source below into a natural English Bluesky recipe thread.

HARDEST RULE — reply2 must be at most {MAX_METHOD_CHARS} characters (about 30 English words,
two or three short sentences). A disclosure and a link are appended to it later, and the
platform rejects the post above 300 characters. Draft reply2 first, count its characters, and
cut it down until it fits. Prefer dropping detail over exceeding the limit.

Rules:
- Return JSON only, with main, reply1, reply2, and alt_text.
- main and reply1 must each be no more than 300 characters including spaces.
- main: an appetizing hook and what makes the dish useful. Do not say 'thread' or mention AI.
- reply1: ingredients and ratios, using compact line breaks or bullets. Put the full detail here,
  because reply2 has almost no room.
- reply2: only the essential cooking order in brief, plus the single most useful source-grounded
  tip. No ingredient list, no restating the intro.
- Use clear global English. Briefly explain Korean ingredients when helpful.
- Do not invent ingredients, quantities, temperatures, times, storage claims, experiences, or health benefits.
- Preserve every important quantity exactly. Do not include any URL.
- Every number you write must already appear in the Korean source. If you would need a new
  number, describe it in words instead.
- alt_text: a concise English description based only on the supplied image prompt and dish name.

Example of a correctly sized reply2 (159 characters):
"Fry only the kimchi first, then add rice over high heat. Pour soy sauce around the pan edge, not
the center, so it caramelizes instead of steaming."

Source:
{source}

Image prompt:
{menu.get('image_prompt', '')}
"""


def generate(menu: dict, attempts: int = 3) -> dict | None:
    """영어 스레드 1건 생성. 실패 사유는 LAST_ERROR에 남는다.

    ⚠ 호출 1회가 Gemini 무료 한도(모델·프로젝트당 하루 20회)를 그대로 갉아먹는다.
      매일 새로 만들지 말고 prefetch_threads.py로 미리 캐시해 둘 것.
    """
    global LAST_ERROR
    api_key = image_gen._api_key()
    if not api_key:
        LAST_ERROR = "GEMINI_API_KEY 없음"
        return None
    source = menu["body"] + "\n" + menu["recipe"]
    wait = 8
    for attempt in range(attempts):
        if attempt:
            time.sleep(wait)
            wait *= 2
        try:
            response = requests.post(
                API,
                params={"key": api_key},
                json={
                    "contents": [{"parts": [{"text": _prompt(menu)}]}],
                    "generationConfig": GENERATION_CONFIG,
                },
                timeout=180,
            )
            if response.status_code in RETRY_STATUS:
                detail = response.json().get("error", {}).get("message", "")
                LAST_ERROR = f"HTTP {response.status_code} {detail[:160]}"
                # 일일 쿼터가 바닥나면 같은 실행 안에서 더 시도해도 소용이 없다.
                # 남은 시도까지 태우면 다음 실행의 몫까지 잃는다 (8/14 쿼터 자폭 루프).
                if response.status_code == 429:
                    return None
                continue
            response.raise_for_status()
            candidates = response.json().get("candidates") or []
            finish = candidates[0].get("finishReason") if candidates else "NO_CANDIDATE"
            text = "".join(
                part.get("text", "")
                for part in (candidates[0].get("content", {}).get("parts", []) if candidates else [])
            ).strip()
            data = _extract_json(text)
            if data is None:
                LAST_ERROR = f"JSON 파싱 실패 (finishReason={finish}, {len(text)}자)"
                continue
            if isinstance(data.get("reply2"), str) and len(data["reply2"].strip()) > MAX_METHOD_CHARS:
                original = len(data["reply2"].strip())
                data["reply2"] = _trim_to_limit(data["reply2"], MAX_METHOD_CHARS)
                print(f"  reply2 {original}자 → {len(data['reply2'])}자로 문장 단위 축약")
            reason = _invalid_reason(data, source)
            if reason is None:
                LAST_ERROR = ""
                return {field: data[field].strip() for field in FIELDS}
            LAST_ERROR = f"검증 실패: {reason}"
        except requests.RequestException as exc:
            LAST_ERROR = f"요청 오류: {str(exc)[:160]}"
            continue
    return None


def load_or_generate(menu: dict) -> dict | None:
    path = CACHE_DIR / f"{menu['id']}.json"
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if _valid(data, menu["body"] + "\n" + menu["recipe"]):
                return data
        except ValueError:
            pass
    data = generate(menu)
    if data:
        CACHE_DIR.mkdir(exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return data
