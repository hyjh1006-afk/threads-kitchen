# 무료 레시피 발행기 연결

기존 Threads 자동화는 서버에서 비활성화한 채 백업으로 보존한다. 새 실행 진입점은
`publish_daily.py`, 새 예약 작업은 `daily-recipe-publisher`다.

## 비용

- WordPress.com의 무료 사이트 주소(`*.wordpress.com`) 사용: 0원
- Bluesky 계정 및 게시 API: 0원
- GitHub Actions 공개 저장소 기본 사용: 0원 범위
- 쿠팡 링크는 기존 파트너스 키를 재사용한다.

유료 도메인, 유료 테마, WordPress 업그레이드는 선택하지 않는다.

## 비밀값

로컬 `.env` 및 GitHub Actions Secrets에만 다음 값을 둔다.

```text
WORDPRESS_SITE=https://사이트이름.wordpress.com
WORDPRESS_USERNAME=
WORDPRESS_APP_PASSWORD=
BLUESKY_HANDLE=
BLUESKY_APP_PASSWORD=
COUPANG_ACCESS_KEY=
COUPANG_SECRET_KEY=
GEMINI_API_KEY=
```

Bluesky 두 값은 없어도 된다. 이 경우 WordPress만 정상 발행한다.

## 동작

1. `m01`~`m15`를 날짜순으로 하루 1개씩 WordPress에 재발행한다.
2. 재발행 완료 후 아직 쓰지 않은 새 메뉴로 이어간다.
3. 사진은 WordPress 미디어에 직접 업로드한다. 사진 실패 여부와 별개로 글은 발행한다.
4. 메뉴마다 `home-recipe-mXX` 고정 슬러그로 중복을 방지한다.
5. 쿠팡 링크가 만들어진 날만 고지문과 제휴 링크 섹션을 넣는다.
6. WordPress 성공 후 Bluesky에 사진 1장과 글 링크를 홍보한다.

로컬 연결 확인은 `python publish_daily.py --menu m01 --no-generate`로 한다.
첫 실제 글을 확인한 다음 GitHub Actions의 `daily-recipe-publisher`를 켠다.
