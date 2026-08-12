# -*- coding: utf-8 -*-
import json
import unittest
from pathlib import Path

import bluesky_client
import bluesky_thread_content


class RecordingClient(bluesky_client.BlueskyClient):
    def __init__(self):
        super().__init__("test.bsky.social", "secret")
        self.calls = []
        self.deleted = []

    def post(self, text, **kwargs):
        self.calls.append((text, kwargs))
        number = len(self.calls)
        return {"uri": f"at://did/app.bsky.feed.post/{number}", "cid": f"cid-{number}"}

    def delete_post(self, uri):
        self.deleted.append(uri)


class FailingClient(RecordingClient):
    def post(self, text, **kwargs):
        if len(self.calls) == 1:
            raise RuntimeError("reply failed")
        return super().post(text, **kwargs)


class BlueskyThreadTests(unittest.TestCase):
    def test_cached_replay_threads_are_grounded_english_and_within_limit(self):
        base = Path(__file__).resolve().parents[1]
        menus = json.loads((base / "menus.json").read_text(encoding="utf-8"))["menus"]
        for menu_id in ("m01", "m02"):
            menu = next(item for item in menus if item["id"] == menu_id)
            data = json.loads(
                (base / "bluesky_threads" / f"{menu_id}.json").read_text(encoding="utf-8")
            )
            self.assertTrue(
                bluesky_thread_content._valid(data, menu["body"] + "\n" + menu["recipe"]),
                menu_id,
            )

    def test_three_posts_form_one_reply_chain(self):
        client = RecordingClient()
        result = client.post_thread(["root", "reply one", "reply two"])
        self.assertEqual(result["root"]["cid"], "cid-1")
        self.assertEqual(client.calls[1][1]["reply_root"]["cid"], "cid-1")
        self.assertEqual(client.calls[1][1]["reply_parent"]["cid"], "cid-1")
        self.assertEqual(client.calls[2][1]["reply_root"]["cid"], "cid-1")
        self.assertEqual(client.calls[2][1]["reply_parent"]["cid"], "cid-2")

    def test_partial_thread_is_rolled_back(self):
        client = FailingClient()
        with self.assertRaises(RuntimeError):
            client.post_thread(["root", "reply one", "reply two"])
        self.assertEqual(client.deleted, ["at://did/app.bsky.feed.post/1"])

    def test_public_url_uses_record_key(self):
        uri = "at://did:plc:test/app.bsky.feed.post/abc123"
        self.assertEqual(
            bluesky_client.public_url(uri, "cook.bsky.social"),
            "https://bsky.app/profile/cook.bsky.social/post/abc123",
        )

    def test_empty_link_does_not_create_invalid_facet(self):
        self.assertEqual(bluesky_client._link_facet("plain post", ""), [])


if __name__ == "__main__":
    unittest.main()
