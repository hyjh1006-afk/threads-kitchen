# -*- coding: utf-8 -*-
import tempfile
import unittest
from pathlib import Path

from PIL import Image

import bluesky_client
import recipe_publisher
from wordpress_client import WordPressClient


MENU = {
    "id": "m99",
    "name": "김치 <볶음밥>",
    "body": "퇴근하고 10분 컷\n진짜 쉬움",
    "recipe": "1. 김치를 볶기\n2. 밥 넣기",
    "ingredients": [],
    "image_prompt": "food",
}


class FakeResponse:
    def __init__(self, data, ok=True, status=200):
        self._data = data
        self.ok = ok
        self.status_code = status
        self.text = str(data)

    def json(self):
        return self._data


class FakeSession:
    def __init__(self, gets=None, posts=None):
        self.auth = None
        self.headers = {}
        self.gets = list(gets or [])
        self.posts = list(posts or [])
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        return self.gets.pop(0)

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return self.posts.pop(0)


class RecipeTests(unittest.TestCase):
    def test_article_escapes_text_and_disclosure_precedes_links(self):
        article = recipe_publisher.build_article(
            MENU,
            [{"source_url": "https://example.com/a.jpg"}],
            [{"label": "팬", "url": "https://example.com/product?a=1&b=2"}],
            "제휴 수수료를 받습니다.",
        )
        self.assertIn("김치 &lt;볶음밥&gt;", article)
        self.assertIn("rel=\"sponsored nofollow\"", article)
        self.assertLess(article.index("제휴 수수료"), article.index("https://example.com/product"))

    def test_bluesky_link_facet_uses_utf8_byte_offsets(self):
        text = "한글 링크 https://example.com/a"
        facet = bluesky_client._link_facet(text, "https://example.com/a")[0]
        self.assertEqual(facet["index"]["byteStart"], len("한글 링크 ".encode("utf-8")))
        self.assertEqual(facet["index"]["byteEnd"], len(text.encode("utf-8")))

    def test_bluesky_image_is_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "large.png"
            Image.new("RGB", (3000, 3000), (180, 90, 40)).save(path, "PNG")
            data, mime = bluesky_client._image_bytes(path)
            self.assertEqual(mime, "image/jpeg")
            self.assertLessEqual(len(data), 950_000)

    def test_wordpress_publish_is_idempotent(self):
        existing = {"id": 7, "link": "https://site.example/p/7"}
        session = FakeSession(gets=[FakeResponse([existing])])
        client = WordPressClient("https://site.example", "user", "pass", session)
        result = client.publish(title="t", content="c", slug="home-recipe-m99")
        self.assertEqual(result["id"], 7)
        self.assertTrue(result["_already_exists"])
        self.assertEqual([call[0] for call in session.calls], ["GET"])

    def test_wordpress_publish_payload(self):
        session = FakeSession(
            gets=[FakeResponse([])],
            posts=[FakeResponse({"id": 8, "link": "https://site.example/p/8"}, status=201)],
        )
        client = WordPressClient("https://site.example", "user", "pass", session)
        result = client.publish(
            title="제목", content="본문", slug="home-recipe-m99", featured_media=3
        )
        self.assertEqual(result["id"], 8)
        payload = session.calls[-1][2]["json"]
        self.assertEqual(payload["status"], "publish")
        self.assertEqual(payload["featured_media"], 3)


if __name__ == "__main__":
    unittest.main()
