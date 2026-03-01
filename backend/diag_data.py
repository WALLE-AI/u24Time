import asyncio
from db.session import get_async_session
from db.models import CanonicalItemModel, CrawlTaskModel
from sqlalchemy import select, func

async def check_db_status():
    print("Checking Database Status...")
    async with get_async_session() as session:
        # Check Canonical Items
        item_count_stmt = select(func.count()).select_from(CanonicalItemModel)
        item_count = (await session.execute(item_count_stmt)).scalar()
        print(f"Total Canonical Items: {item_count}")
        
        # Check Tasks
        task_count_stmt = select(func.count()).select_from(CrawlTaskModel)
        task_count = (await session.execute(task_count_stmt)).scalar()
        print(f"Total Crawl Tasks: {task_count}")
        
        # Check Recent Tasks
        recent_tasks_stmt = select(CrawlTaskModel).order_by(CrawlTaskModel.started_at.desc()).limit(10)
        recent_tasks = (await session.execute(recent_tasks_stmt)).scalars().all()
        print("\nRecent Tasks:")
        for t in recent_tasks:
            print(f"- [{t.task_type}] {t.source_id}: {t.status} (Fetched: {t.items_fetched}, Aligned: {t.items_aligned}) at {t.started_at}")

        # Check domain distribution
        domain_stmt = select(CanonicalItemModel.domain, func.count()).group_by(CanonicalItemModel.domain)
        domains = (await session.execute(domain_stmt)).all()
        print("\nDomain Distribution:")
        for d, count in domains:
            print(f"- {d}: {count}")

if __name__ == "__main__":
    asyncio.run(check_db_status())
