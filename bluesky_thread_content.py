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
MAX_METHOD_CHARS = 165  # Leave room for the required affiliate disclosure and URL.


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
    if not isinstance(data, dict) or any(not isinstance(data.get(k), str) for k in FIELDS):
        return False
    posts = [data["main"].strip(), data["reply1"].strip(), data["reply2"].strip()]
    if any(not text or len(text) > 300 for text in posts):
        return False
    if len(posts[2]) > MAX_METHOD_CHARS:
        return False
    joined = " ".join(posts)
    if re.search(r"[가-힣]", joined) or "http://" in joined or "https://" in joined:
        return False
    if len(data["alt_text"].strip()) > 1000:
        return False
    source_numbers = set(re.findall(r"\d+(?:\.\d+)?", source))
    generated_numbers = set(re.findall(r"\d+(?:\.\d+)?", joined))
    return generated_numbers <= source_numbers


def _prompt(menu: dict) -> str:
    source = json.dumps(
        {"name": menu["name"], "intro": menu["body"], "verified_recipe": menu["recipe"]},
        ensure_ascii=False,
        indent=2,
    )
    return f"""Turn the Korean source below into a natural English Bluesky recipe thread.

Rules:
- Return JSON only, with main, reply1, reply2, and alt_text.
- Each of main, reply1, and reply2 must be no more than 300 characters including spaces.
- main: an appetizing hook and what makes the dish useful. Do not say 'thread' or mention AI.
- reply1: ingredients and ratios, using compact line breaks or bullets.
- reply2: cooking method and the most useful source-grounded tip. Keep it to no more than {MAX_METHOD_CHARS} characters so a required affiliate disclosure can be appended later.
- Use clear global English. Briefly explain Korean ingredients when helpful.
- Do not invent ingredients, quantities, temperatures, times, storage claims, experiences, or health benefits.
- Preserve every important quantity exactly. Do not include any URL.
- alt_text: a concise English description based only on the supplied image prompt and dish name.

Source:
{source}

Image prompt:
{menu.get('image_prompt', '')}
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
                    "generationConfig": {"temperature": 0.35, "maxOutputTokens": 2048},
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
                return {key: data[key].strip() for key in FIELDS}
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
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return data
