# -*- coding: utf-8 -*-
"""Collect real Bluesky metrics for dashboards; never estimate missing values."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import requests

from threads_client import _load_env

BASE = Path(__file__).parent
OUTPUT = BASE / "state" / "channel_metrics.json"
BSKY_API = "https://public.api.bsky.app/xrpc"


def _integer(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def collect(session: requests.Session | None = None) -> dict:
    http = session or requests.Session()
    _load_env()
    handle = os.environ.get("BLUESKY_HANDLE", "").strip(" \t\r\n\ufeff\u200b")
    if not handle:
        config = json.loads((BASE / "publisher_config.json").read_text(encoding="utf-8"))
        handle = str((config.get("bluesky") or {}).get("handle") or "").strip()
    if not handle:
        raise RuntimeError("Bluesky handle is missing.")

    profile_response = http.get(
        f"{BSKY_API}/app.bsky.actor.getProfile", params={"actor": handle}, timeout=30
    )
    profile_response.raise_for_status()
    profile = profile_response.json()

    feed_response = http.get(
        f"{BSKY_API}/app.bsky.feed.getAuthorFeed",
        params={"actor": handle, "limit": 100, "filter": "posts_no_replies"},
        timeout=30,
    )
    feed_response.raise_for_status()
    feed = feed_response.json().get("feed") or []
    likes = reposts = replies = quotes = 0
    latest_at = None
    for item in feed:
        post = item.get("post") or {}
        likes += _integer(post.get("likeCount"))
        reposts += _integer(post.get("repostCount"))
        replies += _integer(post.get("replyCount"))
        quotes += _integer(post.get("quoteCount"))
        if latest_at is None:
            latest_at = (post.get("record") or {}).get("createdAt")

    return {
        "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "wordpress": None,
        "bluesky": {
            "handle": profile.get("handle") or handle,
            "display_name": profile.get("displayName") or handle,
            "url": f"https://bsky.app/profile/{profile.get('handle') or handle}",
            "posts": _integer(profile.get("postsCount")),
            "followers": _integer(profile.get("followersCount")),
            "follows": _integer(profile.get("followsCount")),
            "likes": likes,
            "reposts": reposts,
            "replies": replies,
            "quotes": quotes,
            "engagements": likes + reposts + replies + quotes,
            "engagement_scope": "latest_100_original_posts",
            "latest_at": latest_at,
        },
    }


def _payload(data: dict | None) -> dict:
    """updated_at을 뺀 실제 지표만 — 변화 판정용."""
    return {key: value for key, value in (data or {}).items() if key != "updated_at"}


def main() -> int:
    data = collect()
    OUTPUT.parent.mkdir(exist_ok=True)
    previous = None
    if OUTPUT.exists():
        try:
            previous = json.loads(OUTPUT.read_text(encoding="utf-8"))
        except ValueError:
            previous = None
    bsky = data["bluesky"]
    # 지표가 그대로면 파일을 건드리지 않는다. 타임스탬프만 바뀐 파일이 15분마다
    # "레시피 자동 발행 기록" 커밋으로 쌓여, 3일간 발행이 멈춘 걸 정상으로
    # 오해하게 만든 사고(8/14~8/16)를 원천 차단한다.
    if previous is not None and _payload(previous) == _payload(data):
        print(f"metrics unchanged: Bluesky {bsky['posts']} posts/{bsky['engagements']} engagements")
        return 0
    OUTPUT.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"metrics saved: Bluesky {bsky['posts']} posts/{bsky['engagements']} engagements")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
