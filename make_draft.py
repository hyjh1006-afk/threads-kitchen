# -*- coding: utf-8 -*-
"""오늘의 초안 생성 (게시는 하지 않음 — 승인형 워크플로 1단계).

사용: python make_draft.py [--menu m03]
결과: drafts/YYYY-MM-DD.json + 화면에 미리보기 출력
"""
import argparse
import json
from datetime import date
from pathlib import Path

import coupang_link
import image_gen
import image_host

BASE = Path(__file__).parent
CONFIG = json.loads((BASE / "config.json").read_text(encoding="utf-8"))
MENUS_PATH = BASE / "menus.json"


def pick_menu(menu_id: str | None = None, skip_ids: set[str] | None = None) -> dict | None:
    """다음 메뉴 선택. skip_ids = 사용자가 폰(클라우드 랩)에서 반려한 메뉴들."""
    data = json.loads(MENUS_PATH.read_text(encoding="utf-8"))
    for m in data["menus"]:
        if menu_id and m["id"] == menu_id:
            return m
        if not menu_id and not m.get("used") and m["id"] not in (skip_ids or set()):
            return m
    return None


def fetch_vetoes() -> set[str]:
    """클라우드 랩의 반려 목록 (폰 승인 게이트). 실패 시 빈 set — fail-open."""
    import requests
    try:
        r = requests.get("https://lab-cloud.pages.dev/api/vetoes", timeout=10)
        if r.ok:
            return set(r.json().get("menu_ids", []))
    except Exception:
        pass
    return set()


def with_ad_tag(body: str) -> str:
    """본문 [광고] 태그 — 사용자 결정(2026-07-27)으로 기본 OFF (config로 복귀 가능)."""
    if not CONFIG.get("ad_tag_in_body", False):
        return body
    tag = CONFIG.get("ad_tag", "[광고]")
    return body if body.startswith(tag) else f"{tag} {body}"


def build_reply(menu: dict, include_missing: bool = True) -> tuple[str, str | None, list[dict]]:
    """답글 2개 체인: (답글1=레시피 전문, 답글2=재료 링크+안내문구, links).

    레시피를 상세하게 쓰기 위해 스레드 500자 한도를 답글 2개로 나눈다
    (사용자 요청 2026-07-27). 답글2가 없으면(링크 전부 실패) None —
    광고가 없으니 안내문구도 불필요하다.

    include_missing=False(자동 모드): 링크 생성 실패한 재료 줄은 아예 뺀다
    (자리 표시 문구가 실제 게시되는 사고 방지).
    안내문구 위치는 config.disclosure_position: reply_top | reply_bottom(사용자 결정).
    """
    lines = ["재료는 이걸로 했어 👇", ""]
    links = []
    for ing in menu["ingredients"]:
        item = coupang_link.search_link(ing["search"], CONFIG.get("coupang_subid", "threads_kitchen"))
        if item:
            lines.append(f"🛒 {ing['label']}: {item['url']}")
            links.append({"label": ing["label"], **item})
        elif include_missing:
            lines.append(f"🛒 {ing['label']}: [링크 자리 — 파트너스 키 설정 후 자동 생성]")
            links.append({"label": ing["label"], "url": None, "note": "키 미설정 또는 검색 실패"})
    if not any(l.get("url") for l in links) and not include_missing:
        return menu["recipe"], None, links
    if CONFIG.get("disclosure_position", "reply_bottom") == "reply_top":
        lines.insert(0, CONFIG["disclosure"] + "\n")
    else:
        lines += ["", CONFIG["disclosure"]]
    return menu["recipe"], "\n".join(lines).rstrip(), links


def ensure_images(menu: dict) -> list[str]:
    """이미지 자동 파이프라인: 4컷 세트 생성(Pollinations) → git push → URL 검증.

    {id}_1..4.png 세트를 우선 쓰고, 구버전 단일 {id}.png는 폴백.
    어느 단계가 실패해도 성공한 만큼의 URL 리스트(없으면 빈 리스트)를 반환한다.
    """
    imgdir = BASE / "images"
    variants = sorted(imgdir.glob(f"{menu['id']}_*.png"))
    if not variants:
        legacy = imgdir / f"{menu['id']}.png"
        if legacy.exists():
            variants = [legacy]
    if not variants:
        print(f"  이미지 4컷 생성 중… ({menu['id']})")
        variants = image_gen.generate_set(menu["image_prompt"], imgdir, menu["id"])
    if not variants:
        return []
    image_base = CONFIG.get("image_base_url", "").strip().rstrip("/")
    if not image_base:
        print("  (이미지 로컬만 생성됨 — 호스팅하려면 config의 image_base_url 설정)")
        return []
    if not image_host.push_images():
        print("  (이미지 푸시 실패/원격 없음 — 텍스트로 진행)")
        return []
    urls = []
    for p in variants:
        url = f"{image_base}/{p.name}"
        if image_host.verify_url(url):
            urls.append(url)
        else:
            print(f"  (공개 URL 확인 실패: {url} — 이 컷 제외)")
    return urls


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--menu", default=None, help="특정 메뉴 id 지정 (예: m13)")
    args = ap.parse_args()

    menu = pick_menu(args.menu)
    if not menu:
        print("소재 은행이 비었습니다 — menus.json에 메뉴를 추가하세요.")
        return

    image_urls = ensure_images(menu)

    reply_text, links_text, links = build_reply(menu)
    draft = {
        "date": date.today().isoformat(),
        "menu_id": menu["id"],
        "menu_name": menu["name"],
        "body_text": with_ad_tag(menu["body"]),
        "image_urls": image_urls,
        "image_prompt": menu["image_prompt"],
        "reply_text": reply_text,
        "links_text": links_text,
        "links": links,
        "status": "PENDING_APPROVAL",
    }
    out = BASE / "drafts" / f"{draft['date']}.json"
    out.write_text(json.dumps(draft, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=" * 46)
    print(f"[초안] {menu['name']}  ({out.name})")
    print("=" * 46)
    print("\n--- 본문 ---\n" + draft["body_text"])
    print("\n--- 이미지 ---")
    print("\n".join(image_urls) if image_urls else "(텍스트-온리 게시 — 이미지 파이프라인 미완성 시 자동 폴백)")
    print("\n--- 답글1 (레시피) ---\n" + reply_text)
    print("\n--- 답글2 (재료 링크) ---\n" + (links_text or "(링크 없음 — 생략)"))
    print("\n검토 후 게시하려면:  python post_approved.py --yes")


if __name__ == "__main__":
    main()
