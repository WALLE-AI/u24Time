import asyncio
from db.session import get_async_session
from crawler_engine.engine import CrawlerEngine
from data_source.registry import registry
from crawler_engine.api_adapters.extended_adapters import HuggingFaceAdapter, PolymarketAdapter

async def test():
    engine = CrawlerEngine()
    async with get_async_session() as session:
        async def _do_hf():
            return await engine._pipeline.align_and_save("academic.huggingface.papers", await HuggingFaceAdapter().fetch(), db_session=session)
        
        items = await engine.run_custom_adapter("academic.huggingface.papers", _do_hf, db_session=session)
        print("HF Items saved:", len(items))

        async def _do_poly():
            return await engine._pipeline.align_and_save("academic.prediction.polymarket", await PolymarketAdapter().fetch_active(), db_session=session)
        
        items2 = await engine.run_custom_adapter("academic.prediction.polymarket", _do_poly, db_session=session)
        print("Poly Items saved:", len(items2))

if __name__ == "__main__":
    asyncio.run(test())
