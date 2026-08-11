# -*- coding: utf-8 -*-
"""Rebuild an existing WordPress recipe from its current images and cached long copy."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import blog_content
import blog_recipe_publisher as publisher
from wordpress_com_client import WordPressClient

BASE = Path(__file__).parent


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--menu", required=True)
    args = parser.parse_args()

    menus = json.loads((BASE / "menus.json").read_text(encoding="utf-8"))["menus"]
    menu = next((item for item in menus if item["id"] == args.menu), None)
    if not menu:
        raise SystemExit(f"Unknown menu: {args.menu}")
    config = json.loads((BASE / "publisher_config.json").read_text(encoding="utf-8"))
    client = WordPressClient.from_env()
    post = client.find_post(f"home-recipe-{menu['id']}")
    if not post:
        raise SystemExit("Post does not exist yet")

    image_urls = list(dict.fromkeys(re.findall(r'<img src="([^"]+)', post["content"]["raw"])))
    media = [{"source_url": url} for url in image_urls]
    links = publisher.affiliate_links(menu, config.get("coupang_subid", "recipe_blog"))
    expansion = blog_content.load_or_generate(menu)
    if not expansion:
        raise SystemExit("Long-form expansion is unavailable")
    article = publisher.build_article(menu, media, links, config["disclosure"], expansion)
    response = client.http.post(
        client.api + f"/posts/{post['id']}", json={"content": article}, timeout=60
    )
    if not response.ok:
        raise client._error(response, "긴 글 갱신")
    visible_chars = len(re.sub(r"<[^>]+>", "", article))
    print(f"Updated {menu['id']} with {visible_chars} visible characters")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
