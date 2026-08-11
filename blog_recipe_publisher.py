# -*- coding: utf-8 -*-
"""WordPress publisher with grounded, cached long-form recipe copy."""
from __future__ import annotations

import html

import blog_content
import bluesky_client
from recipe_publisher import affiliate_links, local_images, teaser_text
from wordpress_com_client import WordPressClient

SECTION_HEADING_STYLE = "font-size:24px;line-height:1.35;margin:2rem 0 .75rem;font-weight:700"


def _heading(text: str) -> str:
    """Render a compact blog subheading independent of the active theme\'s huge h2 style."""
    return f'<h2 style="{SECTION_HEADING_STYLE}">{html.escape(text)}</h2>'



def _paragraphs(items: list[str]) -> str:
    return "".join(f"<p>{html.escape(item)}</p>" for item in items if item.strip())


def _bullets(items: list[str]) -> str:
    return "<ul>" + "".join(f"<li>{html.escape(item)}</li>" for item in items if item.strip()) + "</ul>"


def _source_recipe(text: str) -> str:
    return "<br>\n".join(html.escape(line) for line in text.splitlines())


def build_article(menu: dict, media: list[dict], links: list[dict], disclosure: str,
                  expansion: dict | None) -> str:
    intro = expansion["opening"] if expansion else [line for line in menu["body"].split("\n\n") if line]
    why = expansion["why"] if expansion else []
    tips = expansion["tips"] if expansion else []
    uses = expansion["uses"] if expansion else []
    closing = str(expansion.get("closing", "")) if expansion else ""

    gallery = ""
    if media:
        figures = "".join(
            f'<figure class="wp-block-image"><img src="{html.escape(str(item.get("source_url") or ""), quote=True)}" '
            f'alt="{html.escape(menu["name"], quote=True)}"></figure>'
            for item in media if item.get("source_url")
        )
        gallery = '<div class="wp-block-gallery has-nested-images columns-2">' + figures + "</div>"

    sections = [_paragraphs(intro), gallery]
    if why:
        sections.extend([_heading("왜 이 방식이 편하냐면"), _bullets(why)])
    sections.extend([
        _heading("재료와 만드는 순서"),
        f'<div class="recipe-steps"><p>{_source_recipe(menu["recipe"])}</p></div>',
    ])
    if tips:
        sections.extend([_heading("실패를 줄이는 포인트"), _bullets(tips)])
    if uses:
        sections.extend([_heading("이렇게 활용해도 좋아"), _bullets(uses)])
    if closing:
        sections.extend([_heading("마무리"), f"<p>{html.escape(closing)}</p>"])
    if links:
        items = "".join(
            f'<li><a href="{html.escape(link["url"], quote=True)}" rel="sponsored nofollow">'
            f'{html.escape(link["label"])}</a></li>' for link in links
        )
        sections.extend([
            "<hr>" + _heading("사용한 재료·도구"),
            f'<p><strong>{html.escape(disclosure)}</strong></p>',
            f"<ul>{items}</ul>",
        ])
    return "".join(sections)


def publish(menu: dict, config: dict, *, generate_images: bool = True) -> dict:
    wordpress = WordPressClient.from_env()
    slug = f"home-recipe-{menu['id']}"
    existing = wordpress.find_post(slug)
    paths = local_images(menu, generate=generate_images)
    uploaded: list[dict] = []
    if not existing:
        for path in paths:
            try:
                uploaded.append(wordpress.upload_media(path, menu["name"]))
            except Exception as exc:
                print(f"[publisher] 이미지 제외({path.name}): {str(exc)[:160]}")
    links = affiliate_links(menu, config.get("coupang_subid", "recipe_blog"))
    expansion = blog_content.load_or_generate(menu)
    article = build_article(menu, uploaded, links, config["disclosure"], expansion)
    if existing:
        post = existing
    else:
        post = wordpress.publish(
            title=menu["name"], content=article, slug=slug,
            featured_media=(uploaded[0]["id"] if uploaded else None),
            excerpt=next((x for x in menu["body"].splitlines() if x.strip()), ""),
        )
    url = str(post.get("link") or "")
    result = {
        "wordpress_id": str(post.get("id") or ""), "url": url,
        "already_existed": bool(existing), "images": [p.name for p in paths],
        "links": [link["label"] for link in links], "long_form": bool(expansion),
        "bluesky_uri": None, "bluesky_error": None,
    }
    if config.get("bluesky", {}).get("enabled", True) and bluesky_client.is_configured():
        try:
            response = bluesky_client.BlueskyClient.from_env().post(
                teaser_text(menu, url), link=url, images=paths[:1],
                alt_text=f"{menu['name']} 완성 사진",
            )
            result["bluesky_uri"] = response.get("uri")
        except Exception as exc:
            result["bluesky_error"] = str(exc)[:300]
    return result
