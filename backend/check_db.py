
import asyncio
import sys
import os
from datetime import datetime, timezone

# Add backend to path
sys.path.insert(0, os.path.abspath("."))

from db.session import get_async_session
from db.models import CanonicalItemModel
from sqlalchemy import select, func

async def check():
    print(f"Checking DB at {datetime.now(timezone.utc)}")
    async with get_async_session() as s:
        # Total count
        count = (await s.execute(select(func.count(CanonicalItemModel.id)))).scalar()
        print(f"Total items in DB: {count}")
        
        # Newest item
        stmt = select(CanonicalItemModel).order_by(CanonicalItemModel.crawled_at.desc()).limit(1)
        item = (await s.execute(stmt)).scalar()
        if item:
            print(f"Newest item: {item.title}")
            print(f"Crawled at: {item.crawled_at}")
            print(f"Source: {item.source_id}")
        else:
            print("No items found.")

if __name__ == "__main__":
    asyncio.run(check())
