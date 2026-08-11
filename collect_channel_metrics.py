# -*- coding: utf-8 -*-
"""Collect real WordPress.com and Bluesky channel metrics for dashboards."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import requests

import wordpress_com_client
from threads_client import _load_env

BASE = Path(__file__).parent
OUTPUT = BASE / "state" / "channel_metrics.json"
WP_API = "https://public-api.wordpress.com"
BSKY_API = "https://public.api.bsky.app/xrpc"


def _integer(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def collect(session: requests.Session | None = None) -> dict:
    """Fetch only platform-reported numbers; never estimate missing metrics."""
    http = session or requests.Session()
    creds = wordpress_com_client.credentials()
    if not creds:
        raise RuntimeError("WordPress.com OAuth 연결값이 없습니다.")
    site, token = creds
    headers = {
        "Authorization": f"Bearer {token}",
        "User-Agent": "threads-kitchen-metrics/1.0",
    }
    encoded_site = quote(site, safe="")

    site_response = http.get(
        f"{WP_API}/rest/v1.1/sites/{encoded_site}", headers=headers, timeout=30
    )
    site_response.raise_for_status()
    site_info = site_response.json()

    stats_response = http.get(
        f"{WP_API}/rest/v1.1/sites/{encoded_site}/stats", headers=headers, timeout=30
    )
    stats_response.raise_for_status()
    stats = stats_response.json().get("stats") or {}

    week_response = http.get(
        f"{WP_API}/rest/v1.1/sites/{encoded_site}/stats/summary",
        headers=headers,
        params={"period": "day", "num": 7},
        timeout=30,
    )
    week_response.raise_for_status()
    week = week_response.json()

    result = {
        "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "wordpress": {
            "site": site,
            "name": site_info.get("name") or site,
            "url": site_info.get("URL") or f"https://{site}",
            # WordPress.com의 공개 site.post_count는 새 사이트에서 지연될 수 있다.
            # 인증된 Stats API의 posts가 발행 직후에도 실제 1개를 반환한다.
            "posts": _integer(stats.get("posts")),
            "views_all": _integer(stats.get("views")),
            "views_today": _integer(stats.get("views_today")),
            "views_7d": _integer(week.get("views")),
            "visitors_7d": _integer(week.get("visitors")),
            "followers": _integer(stats.get("followers_blog")),
        },
        "bluesky": None,
    }

    _load_env()
    handle = os.environ.get("BLUESKY_HANDLE", "").strip(" \t\r\n\ufeff\u200b")
    if not handle:
        config = json.loads((BASE / "publisher_config.json").read_text(encoding="utf-8"))
        handle = str((config.get("bluesky") or {}).get("handle") or "").strip()
    if handle:
        profile_response = http.get(
            f"{BSKY_API}/app.bsky.actor.getProfile",
            params={"actor": handle},
            timeout=30,
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

        result["bluesky"] = {
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
        }
    return result


def main() -> int:
    data = collect()
    OUTPUT.parent.mkdir(exist_ok=True)
    OUTPUT.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    wp = data["wordpress"]
    bsky = data.get("bluesky") or {}
    print(
        f"metrics saved: WordPress {wp['posts']} posts/{wp['views_all']} views"
        f" · Bluesky {bsky.get('posts', 0)} posts/{bsky.get('engagements', 0)} engagements"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())