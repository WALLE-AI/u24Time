"""
Quick test: fetch GitHub Trending from NewsNow API and print results.
Run: uv run python tests/test_github_trending.py
"""
import sys
from pathlib import Path
# Ensure backend root is on sys.path so data_alignment imports work
sys.path.insert(0, str(Path(__file__).parent.parent))

import asyncio
import httpx


async def test_newsnow_github():
    url = "https://newsnow.busiyi.world/api/s?id=github-trending-today&latest"
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Referer": "https://newsnow.busiyi.world",
        "Connection": "keep-alive",
    }

    print("=" * 60)
    print("Testing NewsNow API — GitHub Trending Today")
    print("=" * 60)

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        resp = await client.get(url, headers=headers)

    print(f"Status Code : {resp.status_code}")
    print(f"Content-Type: {resp.headers.get('content-type', '?')}")

    if resp.status_code != 200:
        print(f"ERROR: Got {resp.status_code}")
        print(resp.text[:500])
        return

    data = resp.json()
    items = data.get("items", [])
    updated = data.get("updatedTime", "?")

    print(f"Updated At  : {updated}")
    print(f"Items Count : {len(items)}")
    print("-" * 60)

    for i, item in enumerate(items[:20], 1):
        title = item.get("title", "(no title)")
        url_link = item.get("url", "")
        extra = item.get("extra") or {}
        stars = extra.get("hover", "")
        print(f"{i:2d}. {title}")
        if stars:
            print(f"    ⭐ {stars}")
        if url_link:
            print(f"    🔗 {url_link}")

    print("-" * 60)
    print(f"Total: {len(items)} repos")


async def test_via_normalizer():
    """Also test HotSearchNormalizer on the data"""
    print("\n" + "=" * 60)
    print("Testing HotSearchNormalizer on GitHub Trending data")
    print("=" * 60)

    from data_alignment.normalizers.hotsearch_normalizer import HotSearchNormalizer

    url = "https://newsnow.busiyi.world/api/s?id=github-trending-today&latest"
    headers = {
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0 Safari/537.36",
        "Referer": "https://newsnow.busiyi.world",
    }

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        resp = await client.get(url, headers=headers)

    if resp.status_code != 200:
        print(f"NewsNow returned {resp.status_code}, skipping normalizer test.")
        return

    raw = resp.json()
    normalizer = HotSearchNormalizer()
    items = normalizer.normalize_batch(raw, "hotsearch.github")

    print(f"Normalized {len(items)} CanonicalItems")
    print("-" * 60)
    for item in items[:10]:
        print(f"[{item.hotness_score:5.1f}] {item.title}")
        print(f"       severity={item.severity_level}  url={item.url or '(none)'}")
    print("-" * 60)


if __name__ == "__main__":
    asyncio.run(test_newsnow_github())
    asyncio.run(test_via_normalizer())
