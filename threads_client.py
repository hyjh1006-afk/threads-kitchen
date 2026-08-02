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
    uid = os.environ.get("THREADS_USER_ID", "").strip(" \t\r\n\ufeff\u200b")
    token = os.environ.get("THREADS_ACCESS_TOKEN", "").strip(" \t\r\n\ufeff\u200b")
    return (uid, token) if uid and token else None


def is_configured() -> bool:
    return credentials() is not None


def _create_container(uid: str, token: str, text: str,
                      image_url: str | None = None,
                      reply_to_id: str | None = None,
                      topic_tag: str | None = None) -> str:
    import requests
    params = {"access_token": token, "text": text}
    if image_url:
        params["media_type"] = "IMAGE"
        params["image_url"] = image_url
    else:
        params["media_type"] = "TEXT"
    if reply_to_id:
        params["reply_to_id"] = reply_to_id
    if topic_tag:
        # 주제 태그: 포스트당 1개, 1~50자, 마침표·& 금지. 주제 팔로워에게 노출됨
        params["topic_tag"] = topic_tag.replace(".", "").replace("&", "")[:50]
    r = requests.post(f"{BASE}/{uid}/threads", data=params, timeout=30)
    if not r.ok:
        raise RuntimeError(f"컨테이너 생성 실패 {r.status_code}: {r.text[:200]}")
    return r.json()["id"]


def _create_carousel(uid: str, token: str, text: str, image_urls: list[str],
                     reply_to_id: str | None = None,
                     topic_tag: str | None = None) -> str:
    """캐러셀 컨테이너: 아이템 컨테이너들 → children으로 묶은 CAROUSEL 컨테이너."""
    import requests
    children = []
    for url in image_urls:
        r = requests.post(f"{BASE}/{uid}/threads",
                          data={"access_token": token, "media_type": "IMAGE",
                                "image_url": url, "is_carousel_item": "true"},
                          timeout=30)
        if not r.ok:
            raise RuntimeError(f"캐러셀 아이템 실패 {r.status_code}: {r.text[:200]}")
        children.append(r.json()["id"])
    params = {"access_token": token, "media_type": "CAROUSEL",
              "children": ",".join(children), "text": text}
    if reply_to_id:
        params["reply_to_id"] = reply_to_id
    if topic_tag:
        params["topic_tag"] = topic_tag.replace(".", "").replace("&", "")[:50]
    r = requests.post(f"{BASE}/{uid}/threads", data=params, timeout=30)
    if not r.ok:
        raise RuntimeError(f"컨테이너 생성 실패 {r.status_code}: {r.text[:200]}")
    return r.json()["id"]


def _publish(uid: str, token: str, container_id: str) -> str:
    import requests
    r = requests.post(
        f"{BASE}/{uid}/threads_publish",
        data={"access_token": token, "creation_id": container_id},
        timeout=30,
    )
    if not r.ok:  # API의 실제 사유를 로그에 남긴다 (raise_for_status는 본문을 버림)
        raise RuntimeError(f"발행 실패 {r.status_code}: {r.text[:200]}")
    return r.json()["id"]


def wait_until_ready(post_id: str, timeout_seconds: int = 300,
                     expect_children: int = 0) -> bool:
    """게시물이 답글을 받을 수 있는 상태가 될 때까지 대기.

    캐러셀은 발행 직후 ID가 나와도 내부 처리가 끝나지 않는다. 이 상태에서 답글을 달면
    ① 400 "The requested resource does not exist" 또는
    ② 더 나쁘게, 답글 연결이 조용히 사라진 채 독립 글로 발행된다 (2026-08-02 실측).
    그래서 id 조회만으로는 부족하고, 캐러셀이면 children의 media_url까지 나와야
    '처리 완료'로 본다.
    """
    import requests
    creds = credentials()
    if not creds:
        return False
    _, token = creds
    fields = "id,children{media_url}" if expect_children else "id"
    waited = 0
    while waited < timeout_seconds:
        try:
            r = requests.get(f"{BASE}/{post_id}",
                             params={"fields": fields, "access_token": token}, timeout=20)
            if r.ok:
                if not expect_children:
                    return True
                kids = (r.json().get("children") or {}).get("data", [])
                if len(kids) >= expect_children and all(k.get("media_url") for k in kids):
                    return True
        except Exception:
            pass
        time.sleep(15)
        waited += 15
    return False


def is_attached(post_id: str, parent_id: str) -> bool:
    """방금 올린 답글이 실제로 부모에 붙었는지 확인 (독립 글로 새어나갔는지 검사)."""
    import requests
    creds = credentials()
    if not creds:
        return False
    _, token = creds
    try:
        r = requests.get(f"{BASE}/{post_id}",
                         params={"fields": "replied_to", "access_token": token}, timeout=20)
        return r.ok and (r.json().get("replied_to") or {}).get("id") == parent_id
    except Exception:
        return False


def post(text: str, image_url: str | None = None,
         reply_to_id: str | None = None, wait_seconds: int = 30,
         topic_tag: str | None = None,
         image_urls: list[str] | None = None) -> str:
    """게시(또는 답글) 후 게시물 ID 반환. 이미지 컨테이너는 처리 대기 권장(30초).

    image_urls에 2장 이상을 주면 캐러셀(스와이프) 게시. 1장이면 단일 이미지.
    """
    creds = credentials()
    if not creds:
        raise RuntimeError("THREADS_USER_ID / THREADS_ACCESS_TOKEN이 없습니다 (.env 확인, README 참고)")
    uid, token = creds
    urls = image_urls or ([image_url] if image_url else [])
    if len(urls) > 1:
        cid = _create_carousel(uid, token, text, urls, reply_to_id, topic_tag)
        time.sleep(wait_seconds * 2)  # 캐러셀은 아이템 수만큼 처리 시간이 더 걸림
    else:
        cid = _create_container(uid, token, text, urls[0] if urls else None,
                                reply_to_id, topic_tag)
        if urls:
            time.sleep(wait_seconds)  # 미디어 처리 대기 (공식 권장 평균 30초)
    return _publish(uid, token, cid)
