import asyncio
from crawler_engine.engine import CrawlerEngine
from db.session import get_async_session, init_db
import logging

# Set up logging to console
logging.basicConfig(level=logging.INFO)

async def manual_crawl():
    print("Initializing Engine...")
    engine = CrawlerEngine()
    
    print("Ensuring DB tables exist...")
    await init_db()
    
    print("Starting manual HotSearch crawl (Weibo)...")
    async with get_async_session() as session:
        items = await engine.run_hotsearch(source_ids=["global.social.weibo_newsnow"], db_session=session)
        print(f"Crawl finished. Items found: {len(items)}")
        for item in items[:3]:
            print(f"- {item.title} ({item.source_id})")

if __name__ == "__main__":
    asyncio.run(manual_crawl())
