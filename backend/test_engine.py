import asyncio
from crawler_engine.engine import CrawlerEngine
from db.session import get_async_session
from data_source.registry import DataSourceRegistry
from data_alignment.pipeline import AlignmentPipeline

async def test_crawl():
    registry = DataSourceRegistry()
    pipeline = AlignmentPipeline()
    engine = CrawlerEngine()
    
    source_id = "economy.quant.fear_greed_index"
    async with get_async_session() as session:
        print(f"Starting crawl for {source_id}...")
        items = await engine.run_api(source_id, db_session=session)
        print(f"Fetched and aligned {len(items)} items.")
        for it in items[:2]:
            print(f"Item: {it.title} | ID: {it.item_id} | Domain: {it.domain} | Sub: {it.sub_domain}")
        # Explicit commit is handled by get_async_session context manager usually,
        # but let's be sure. Actually get_async_session in session.py COMMITS on yield.
    
    print("Done.")

if __name__ == "__main__":
    asyncio.run(test_crawl())
