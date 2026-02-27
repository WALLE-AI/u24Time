import asyncio
from db.session import get_async_session
from sqlalchemy import text

async def check_academic():
    async with get_async_session() as session:
        try:
            # Check canonical items
            result = await session.execute(text("SELECT source_id, domain, sub_domain, COUNT(*) FROM canonical_items WHERE source_id LIKE 'academic%' GROUP BY source_id"))
            source_counts = result.fetchall()
            print("Academic Canonical Items by source_id:")
            for sid, dom, sub, count in source_counts:
                print(f"  {sid} (domain={dom}, sub_domain={sub}): {count}")

            # Check raw items
            result = await session.execute(text("SELECT source_id, COUNT(*) FROM raw_items WHERE source_id LIKE 'academic%' GROUP BY source_id"))
            raw_counts = result.fetchall()
            print("\nAcademic Raw Items by source_id:")
            for sid, count in raw_counts:
                print(f"  {sid}: {count}")
                
            # Check for any items with academic domain but different source_id
            result = await session.execute(text("SELECT source_id, COUNT(*) FROM canonical_items WHERE domain='academic' AND source_id NOT LIKE 'academic%' GROUP BY source_id"))
            other_counts = result.fetchall()
            if other_counts:
                print("\nOther items in academic domain:")
                for sid, count in other_counts:
                    print(f"  {sid}: {count}")

        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(check_academic())
