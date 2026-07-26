# -*- coding: utf-8 -*-
"""Gemini API로 메뉴 이미지 자동 생성 (무료 등급, gemini-2.5-flash-image).

키 탐색 순서:
  1) .env / 환경변수 GEMINI_API_KEY  ← 권장 (threads-kitchen 전용 키)
  2) ../Blogger_auto/gemini_key.txt  ← 임시 폴백 (사용자 지시로 허용)

⚠ 무료 한도는 '키'가 아니라 구글 클라우드 '프로젝트' 단위다. 블로그 자동화와
키를 공유하면 서로 한도를 갉아먹으므로, 안정화되면 전용 프로젝트 키를 만들 것
(README 참고 — 과거 같은 원인으로 429 장애 이력 있음).

실패 시 None 반환 — 파이프라인은 텍스트-온리로 계속 진행된다 (게시를 막지 않음).
"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path

BASE_DIR = Path(__file__).parent
FALLBACK_KEY_PATH = BASE_DIR.parent / "Blogger_auto" / "gemini_key.txt"
API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

STYLE_SUFFIX = (" , realistic smartphone food photo, vertical composition, no text,"
                " no watermark, appetizing, natural warm light")


def _api_key() -> str | None:
    from threads_client import _load_env
    _load_env()
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if key:
        return key
    if FALLBACK_KEY_PATH.exists():
        k = FALLBACK_KEY_PATH.read_text(encoding="utf-8").strip().splitlines()
        return k[0].strip() if k else None
    return None


def is_configured() -> bool:
    return _api_key() is not None


def generate(prompt: str, out_path: Path, model: str = "gemini-2.5-flash-image") -> bool:
    """프롬프트로 이미지 1장 생성해 out_path(png)에 저장. 성공 여부 반환."""
    key = _api_key()
    if not key:
        return False
    import requests
    try:
        r = requests.post(
            API.format(model=model),
            params={"key": key},
            json={"contents": [{"parts": [{"text": prompt + STYLE_SUFFIX}]}],
                  "generationConfig": {"responseModalities": ["IMAGE"]}},
            timeout=120,
        )
        r.raise_for_status()
        for cand in r.json().get("candidates", []):
            for part in (cand.get("content") or {}).get("parts", []):
                inline = part.get("inlineData") or part.get("inline_data")
                if inline and inline.get("data"):
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    out_path.write_bytes(base64.b64decode(inline["data"]))
                    return True
        return False
    except Exception as e:  # 어떤 실패든 텍스트-온리 진행
        msg = str(e).split("?key=")[0]  # 로그에 API 키 노출 방지
        print(f"  (이미지 생성 실패 — 텍스트로 진행: {msg})")
        return False


if __name__ == "__main__":
    ok = generate("Korean doenjang jjigae bubbling in a small earthen pot, steam",
                  BASE_DIR / "images" / "_test.png")
    print("생성:", ok)
