import asyncio
from db.session import get_async_session
from crawler_engine.engine import CrawlerEngine
from loguru import logger

async def test():
    engine = CrawlerEngine()
    async with get_async_session() as session:
        items = await engine.run_rss(feed_ids=["academic.arxiv.cs_ai"], db_session=session)
        print(f'Items fetched: {len(items)}')
        for i in items[:2]:
            print(i.domain, i.title, i.source_id)

if __name__ == "__main__":
    asyncio.run(test())
