import asyncio
import sys
from pathlib import Path

# Ensure backend root is on sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from crawler_engine.api_adapters.github_adapter import GithubAdapter
from crawler_engine.engine import CrawlerEngine
import json

async def run():
    print("Testing GithubAdapter directly")
    adapter = GithubAdapter()
    dummy_repos = [
        {"url": "https://github.com/vuejs/core", "title": "Vue"},
        {"url": "https://github.com/facebook/react", "title": "React"},
        {"url": "https://github.com/fakeuser123/fakerepo456", "title": "Fake"},
    ]
    enriched = await adapter.enrichen_trending_repos(dummy_repos)
    print("Enriched repos:")
    print(json.dumps(enriched, indent=2, ensure_ascii=False))


    print("\n\nTesting via CrawlerEngine run_hotsearch (tech.oss.github_trending only)")
    engine = CrawlerEngine()
    items = await engine.run_hotsearch(source_ids=["tech.oss.github_trending"])
    print(f"Engine fetched {len(items)} CanonicalItems.")
    if items:
        print("\nFirst 3 Items:")
        for item in items[:3]:
            score = item.raw_engagement.get("score", 0)
            commits = item.raw_engagement.get("commits_30d", 0)
            stars_today = item.raw_engagement.get("stars_today", 0)
            
            # Print with safely encoded title to avoid cp1252/GBK errors on windows
            safe_title = item.title.encode(sys.stdout.encoding, "replace").decode(sys.stdout.encoding)
            print(f"Title: {safe_title}")
            print(f"Severity: {item.severity_level}, Score: {score}")
            print(f"Stars Today: {stars_today}, Commits (30d): {commits}")
            print("-" * 50)


if __name__ == "__main__":
    asyncio.run(run())
