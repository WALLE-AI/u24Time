import asyncio
from db.session import get_async_session
from crawler_engine.engine import CrawlerEngine
from scheduler import DataScheduler

async def main():
    engine = CrawlerEngine()
    scheduler = DataScheduler(engine=engine, db_session_factory=get_async_session)
    scheduler.start()
    
    print("Triggering global.disaster.usgs...")
    
    future = asyncio.run_coroutine_threadsafe(scheduler._crawl("global.disaster.usgs"), scheduler._loop)
    try:
        res = future.result(timeout=15)
        print("Crawl completed:", res)
    except Exception as e:
        print("Crawl failed:", e)
        import traceback
        traceback.print_exc()

    print("Tasks in engine:", engine.list_tasks())
    
    from time import sleep
    sleep(1)

if __name__ == "__main__":
    asyncio.run(main())
