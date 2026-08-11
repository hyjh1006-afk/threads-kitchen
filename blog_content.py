# -*- coding: utf-8 -*-
"""Generate and cache a grounded, blog-length expansion for each recipe."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

import requests

import image_gen

BASE = Path(__file__).parent
CACHE_DIR = BASE / "blog_articles"
MODEL = "gemini-2.5-flash"
API = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"


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


def _valid(data: dict | None, source: str) -> bool:
    if not isinstance(data, dict):
        return False
    if not isinstance(data.get("opening"), list) or len(data["opening"]) < 2:
        return False
    if not isinstance(data.get("why"), list) or len(data["why"]) < 2:
        return False
    if not isinstance(data.get("tips"), list) or len(data["tips"]) < 2:
        return False
    if not isinstance(data.get("uses"), list) or len(data["uses"]) < 2:
        return False
    joined = " ".join(
        [*data["opening"], *data["why"], *data["tips"], *data["uses"], str(data.get("closing", ""))]
    )
    if not 550 <= len(joined) <= 1400:
        return False
    if any(word in joined for word in ("답글", "댓글", "스레드", "AI가", "자동 생성", "황금 비율", "실패 없이", "근사한", "뚝딱", "걱정 마", "매우 직관적")):
        return False
    # A new digit often means the model invented a quantity, time, or temperature.
    source_numbers = set(re.findall(r"\d+(?:\.\d+)?", source))
    generated_numbers = set(re.findall(r"\d+(?:\.\d+)?", joined))
    return generated_numbers <= source_numbers


def _prompt(menu: dict) -> str:
    source = json.dumps({
        "메뉴명": menu["name"],
        "기존 도입": menu["body"],
        "검증된 레시피": menu["recipe"],
        "제휴 검색용 재료명": [x["label"] for x in menu.get("ingredients") or []],
    }, ensure_ascii=False, indent=2)
    return f"""너는 개인 집밥 블로그의 편집자다. 아래 제공 원문만 근거로 한국어 블로그 보충문을 작성하라.

반드시 지킬 것:
- 원문에 없는 재료, 양, 숫자, 온도, 시간, 보관 기간, 효능을 만들지 마라.
- 실제로 요리해 봤다는 허위 경험담이나 건강 효과를 쓰지 마라.
- 친근한 반말을 쓰되 띄어쓰기는 정상적으로 하고, ㅋㅋ·과한 오타·광고성 과장은 쓰지 마라.
- 스레드, 답글, 댓글, 자동 생성이라는 말을 쓰지 마라.
- 황금 비율, 실패 없이, 근사한, 뚝딱, 걱정 마, 매우 직관적 같은 AI식 상투어를 쓰지 마라.
- 기존 도입과 레시피를 그대로 반복하지 말고, 왜 편한지와 실수 방지 관점에서 설명을 보충하라.
- 전체 보충문은 공백 포함 650~950자 정도로 써라.
- JSON 이외의 문장은 출력하지 마라.

JSON 형식:
{{
  "opening": ["도입 문단 1", "도입 문단 2"],
  "why": ["이 방식이 편한 이유 1", "이유 2", "이유 3"],
  "tips": ["원문에 근거한 실패 방지 팁 1", "팁 2", "팁 3"],
  "uses": ["원문에 근거한 활용 아이디어 1", "활용 아이디어 2"],
  "closing": "짧은 마무리 문단"
}}

제공 원문:
{source}
"""


def generate(menu: dict, attempts: int = 3) -> dict | None:
    key = image_gen._api_key()
    if not key:
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
                params={"key": key},
                json={
                    "contents": [{"parts": [{"text": _prompt(menu)}]}],
                    "generationConfig": {"temperature": 0.45, "maxOutputTokens": 4096},
                },
                timeout=180,
            )
            if response.status_code in (429, 500, 503):
                continue
            response.raise_for_status()
            candidates = response.json().get("candidates") or []
            text = "".join(
                part.get("text", "")
                for part in (candidates[0].get("content", {}).get("parts", []) if candidates else [])
            ).strip()
            data = _extract_json(text)
            if _valid(data, source):
                return data
        except requests.RequestException:
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
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data

