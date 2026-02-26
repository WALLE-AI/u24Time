import asyncio
from db.session import get_async_session
from db.models import CrawlTaskModel
from datetime import datetime, timezone

async def test():
    print("Starting DB test...")
    try:
        async with get_async_session() as session:
            task = CrawlTaskModel(
                task_id="test-task-1",
                source_id="test",
                task_type="test",
                params={},
                status="done",
                items_fetched=1,
                items_aligned=1,
                started_at=datetime.now(timezone.utc),
                finished_at=datetime.now(timezone.utc)
            )
            session.add(task)
            await session.commit()
            print("Successfully saved test task.")
    except Exception as e:
        print(f"Error during DB test: {e}")

if __name__ == "__main__":
    asyncio.run(test())
