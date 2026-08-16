# 🍚 threads-kitchen — English Korean home-cooking threads

Every day this project publishes one Korean home recipe to **Bluesky** as an English three-post thread. WordPress publishing ended after the site was suspended on 2026-08-13.

## Live channel

- Bluesky: https://bsky.app/profile/pparkzze.bsky.social
- Schedule: daily at 11:20 KST (`schedule.json`; editable from Pipeline HQ)
- Workflow: `.github/workflows/daily-recipe-publisher.yml`

The previous Threads account was deleted on 2026-08-11. WordPress and Threads are no longer publishing targets.

## Publishing flow

```text
Choose next recipe → create and validate English copy → prepare food images
→ generate one relevant Coupang affiliate link → publish photo root post
→ publish recipe reply → publish method/tip reply with disclosure and affiliate link
→ save verified publishing state and public channel metrics
```

- The root post is an appetizing hook with up to four images.
- Reply 1 contains ingredients and ratios.
- Reply 2 contains the cooking method, key practical tip, affiliate disclosure, and one relevant Coupang link.
- A missing/long affiliate link or missing disclosure blocks the whole publish attempt instead of silently posting an unmonetized thread.
- Every post is checked against Bluesky's 300-character limit.
- Generated copy is rejected if it introduces a number not present in the Korean source.
- `m01`–`m15` are replayed first, one recipe per day, followed by unused recipes.
- If a reply fails, posts created during that attempt are rolled back to avoid leaving a broken thread.

## Gemini quota and the copy cache

The free Gemini tier allows **20 requests per day per model per project**, so English copy is
never generated on the publishing path when it can be avoided:

- `prefetch-threads.yml` runs daily at 17:10 KST — just after the quota resets at Pacific
  midnight — and caches up to 6 upcoming recipes into `bluesky_threads/`.
- A cached recipe publishes with **zero** Gemini calls. Cache builds at 6/day against a
  consumption of 1/day, so it stays ahead.
- `publish_daily.py` stops after `posting.max_attempts_per_day` failures (default 3) and
  records them in `state/publish_attempts.json`.

This replaces the 2026-08-14 failure mode, where a 15-minute retry loop regenerated copy on
every run, burned the daily quota within an hour, and blocked publishing for three days while
committing "published" messages that hid the outage.

```powershell
python prefetch_threads.py --dry-run     # what still needs copy, no API calls
python prefetch_threads.py --max-calls 6
```

## Required GitHub Actions Secrets

```text
BLUESKY_HANDLE
BLUESKY_APP_PASSWORD
COUPANG_ACCESS_KEY
COUPANG_SECRET_KEY
GEMINI_API_KEY
```

On this PC, the Bluesky app password is also stored under `.local-secrets/` using Windows DPAPI. It is ignored by Git. Use `run_local_with_secrets.ps1` for local authenticated runs.

## Verified metrics

`collect_channel_metrics.py` records only platform-reported values in `state/channel_metrics.json`:

- posts, followers, and follows;
- likes, reposts, replies, and quotes across up to 100 recent root posts.

Bluesky does not expose ordinary post view counts, so the project does not estimate them. The retired WordPress field is stored as `null` for downstream compatibility.

## Main files

- `publish_daily.py` — daily publishing entry point
- `prefetch_threads.py` — build the English copy cache ahead of publishing
- `bluesky_thread_content.py` — grounded English thread generation and cache
- `bluesky_thread_publisher.py` — photo root + two replies
- `bluesky_client.py` — AT Protocol publishing client
- `collect_channel_metrics.py` — verified channel metrics
- `publisher_config.json` — limits and replay order
- `schedule.json` — KST publishing time
- `state/bluesky_published.json` — publishing history
- `state/channel_metrics.json` — shared metrics

Legacy WordPress modules remain only as historical reference and are not imported by the live workflow.

## Local checks

```powershell
python -m unittest discover -s tests -v
python collect_channel_metrics.py
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run_local_with_secrets.ps1
```

`publish_daily.py` will not exceed the configured daily limit unless `--force` is supplied.
