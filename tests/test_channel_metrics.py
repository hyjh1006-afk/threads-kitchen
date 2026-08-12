import os
import unittest
from unittest.mock import patch

import collect_channel_metrics


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeSession:
    def get(self, url, **kwargs):
        if url.endswith("/stats/summary"):
            return FakeResponse({"views": 7, "visitors": 3})
        if url.endswith("/stats"):
            return FakeResponse({"stats": {
                "posts": 2, "views": 12, "views_today": 4, "followers_blog": 1,
            }})
        if "app.bsky.actor.getProfile" in url:
            return FakeResponse({
                "handle": "cook.bsky.social", "displayName": "Cook",
                "postsCount": 3, "followersCount": 2, "followsCount": 5,
            })
        if "app.bsky.feed.getAuthorFeed" in url:
            return FakeResponse({"feed": [{"post": {
                "likeCount": 2, "repostCount": 1, "replyCount": 3, "quoteCount": 1,
                "record": {"createdAt": "2026-08-11T00:00:00Z"},
            }}]})
        return FakeResponse({"name": "Kitchen", "URL": "https://kitchen.example"})


class ChannelMetricsTests(unittest.TestCase):
    def test_collects_only_reported_platform_metrics(self):
        with patch.dict(os.environ, {"BLUESKY_HANDLE": "cook.bsky.social"}, clear=False):
            result = collect_channel_metrics.collect(FakeSession())

        self.assertIsNone(result["wordpress"])
        self.assertEqual(result["bluesky"]["posts"], 3)
        self.assertEqual(result["bluesky"]["engagements"], 7)


if __name__ == "__main__":
    unittest.main()
