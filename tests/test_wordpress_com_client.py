# -*- coding: utf-8 -*-
import unittest

from wordpress_com_client import WordPressClient


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


class WordPressComTests(unittest.TestCase):
    def test_uses_bearer_and_public_api(self):
        session = FakeSession(gets=[FakeResponse([])])
        client = WordPressClient("my-site.wordpress.com", "secret-token", session)
        self.assertEqual(session.headers["Authorization"], "Bearer secret-token")
        self.assertIn("public-api.wordpress.com/wp/v2/sites/my-site.wordpress.com", client.api)
        self.assertIsNone(client.find_post("home-recipe-m01"))

    def test_publish_payload(self):
        session = FakeSession(
            gets=[FakeResponse([])],
            posts=[FakeResponse({"id": 12, "link": "https://my-site.wordpress.com/p/12"})],
        )
        client = WordPressClient("my-site.wordpress.com", "secret-token", session)
        result = client.publish(title="제목", content="본문", slug="home-recipe-m01")
        self.assertEqual(result["id"], 12)
        payload = session.calls[-1][2]["json"]
        self.assertEqual(payload["status"], "publish")
        self.assertEqual(payload["comment_status"], "closed")


if __name__ == "__main__":
    unittest.main()
