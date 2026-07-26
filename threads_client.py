# -*- coding: utf-8 -*-
"""Threads 공식 API 클라이언트 (게시 + 답글).

필요 환경변수 (.env 또는 시스템 환경변수):
  THREADS_USER_ID      : 스레드 사용자 ID (숫자)
  THREADS_ACCESS_TOKEN : 장기 액세스 토큰 (60일, 갱신 필요)

발급 방법은 README.md 참고. 토큰이 없으면 dry-run만 가능.
게시 절차: 컨테이너 생성 → (대기) → 발행. 이미지는 공개 URL만 가능.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

BASE = "https://graph.threads.net/v1.0"
ENV_PATH = Path(__file__).parent / ".env"


def _load_env():
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def credentials() -> tuple[str, str] | None:
    _load_env()
    uid = os.environ.get("THREADS_USER_ID", "").strip()
    token = os.environ.get("THREADS_ACCESS_TOKEN", "").strip()
    return (uid, token) if uid and token else None


def is_configured() -> bool:
    return credentials() is not None


def _create_container(uid: str, token: str, text: str,
                      image_url: str | None = None,
                      reply_to_id: str | None = None) -> str:
    import requests
    params = {"access_token": token, "text": text}
    if image_url:
        params["media_type"] = "IMAGE"
        params["image_url"] = image_url
    else:
        params["media_type"] = "TEXT"
    if reply_to_id:
        params["reply_to_id"] = reply_to_id
    r = requests.post(f"{BASE}/{uid}/threads", data=params, timeout=30)
    r.raise_for_status()
    return r.json()["id"]


def _publish(uid: str, token: str, container_id: str) -> str:
    import requests
    r = requests.post(
        f"{BASE}/{uid}/threads_publish",
        data={"access_token": token, "creation_id": container_id},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["id"]


def post(text: str, image_url: str | None = None,
         reply_to_id: str | None = None, wait_seconds: int = 30) -> str:
    """게시(또는 답글) 후 게시물 ID 반환. 이미지 컨테이너는 처리 대기 권장(30초)."""
    creds = credentials()
    if not creds:
        raise RuntimeError("THREADS_USER_ID / THREADS_ACCESS_TOKEN이 없습니다 (.env 확인, README 참고)")
    uid, token = creds
    cid = _create_container(uid, token, text, image_url, reply_to_id)
    if image_url:
        time.sleep(wait_seconds)  # 미디어 처리 대기 (공식 권장 평균 30초)
    return _publish(uid, token, cid)
