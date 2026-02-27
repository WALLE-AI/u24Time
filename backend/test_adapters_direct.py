import asyncio
from crawler_engine.api_adapters.extended_adapters import HuggingFaceAdapter, SemanticScholarAdapter
from data_alignment.pipeline import AlignmentPipeline
from db.session import get_async_session
from loguru import logger
import sys

# Ensure loguru prints to stdout
logger.remove()
logger.add(sys.stdout, level="DEBUG")

async def test_pipeline():
    pipeline = AlignmentPipeline()
    
    async with get_async_session() as db_session:
        # Test HuggingFace
        print("\n--- Testing HuggingFace Pipeline ---")
        hf = HuggingFaceAdapter()
        try:
            hf_rows = await hf.fetch()
            print(f"HuggingFace returned {len(hf_rows)} rows")
            items = await pipeline.align_and_save("academic.huggingface.papers", hf_rows, db_session=db_session)
            print(f"HuggingFace aligned {len(items)} items")
            await db_session.commit()
            print("HuggingFace committed")
        except Exception as e:
            print(f"HuggingFace pipeline error: {e}")
            await db_session.rollback()

        # Test Semantic Scholar
        print("\n--- Testing Semantic Scholar Pipeline ---")
        ss = SemanticScholarAdapter()
        try:
            ss_rows = await ss.fetch_trending(query="AI")
            print(f"Semantic Scholar returned {len(ss_rows)} rows")
            items = await pipeline.align_and_save("academic.semantic_scholar.trending", ss_rows, db_session=db_session)
            print(f"Semantic Scholar aligned {len(items)} items")
            await db_session.commit()
            print("Semantic Scholar committed")
        except Exception as e:
            print(f"Semantic Scholar pipeline error: {e}")
            await db_session.rollback()

if __name__ == "__main__":
    asyncio.run(test_pipeline())
