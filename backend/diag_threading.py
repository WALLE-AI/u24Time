import asyncio
import threading
from db.session import get_async_session
from db.models import CrawlTaskModel
from crawler_engine.engine import CrawlerEngine
from datetime import datetime, timezone

_engine = CrawlerEngine()

def _run_async(coro):
    def _thread():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(coro)
        finally:
            loop.close()

    t = threading.Thread(target=_thread)
    t.start()
    return t

async def _test_crawl():
    print("Starting crawl test in thread...")
    async with get_async_session() as session:
        # Just use run_hotsearch with a dummy source or small batch
        # hotsearch.weibo is usually available
        items = await _engine.run_hotsearch(source_ids=["hotsearch.weibo"], db_session=session)
        print(f"Crawl finished. Items: {len(items)}")

if __name__ == "__main__":
    thread = _run_async(_test_crawl())
    thread.join()
    print("Thread finished.")
