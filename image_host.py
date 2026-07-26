# -*- coding: utf-8 -*-
"""이미지 자동 호스팅: images/를 git commit·push → GitHub raw URL 확보.

전제(1회 설정): 이 폴더가 GitHub 저장소로 연결돼 있어야 한다 (README 참고).
remote가 없으면 조용히 건너뛰고 로컬 경로만 알려준다 (게시를 막지 않음).
"""
from __future__ import annotations

import subprocess
import time
from pathlib import Path

BASE_DIR = Path(__file__).parent


def _git(*args) -> tuple[int, str]:
    p = subprocess.run(["git", *args], cwd=BASE_DIR, capture_output=True, text=True)
    return p.returncode, (p.stdout + p.stderr).strip()


def has_remote() -> bool:
    code, out = _git("remote")
    return code == 0 and bool(out.strip())


def push_images() -> bool:
    """images/ 변경분만 커밋·푸시. 변경 없으면 True."""
    if not has_remote():
        return False
    _git("add", "images")
    code, out = _git("diff", "--cached", "--quiet")
    if code == 0:  # 스테이징된 변경 없음
        return True
    code, out = _git("commit", "-m", "이미지 자동 업로드 (threads-kitchen)")
    if code != 0:
        print("  (커밋 실패:", out[:120], ")")
        return False
    code, out = _git("push")
    if code != 0:
        print("  (푸시 실패:", out[:120], ")")
        return False
    return True


def verify_url(url: str, tries: int = 4, wait: int = 5) -> bool:
    """게시 전 raw URL 접근 확인 (반영 지연 대비 재시도)."""
    import requests
    for _ in range(tries):
        try:
            if requests.head(url, timeout=10, allow_redirects=True).status_code == 200:
                return True
        except requests.RequestException:
            pass
        time.sleep(wait)
    return False
