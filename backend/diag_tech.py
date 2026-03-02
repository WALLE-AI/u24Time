import asyncio
from db.session import get_async_session, get_sync_session
from db.models import CanonicalItemModel
from sqlalchemy import select, func
from crawler_engine.engine import CrawlerEngine

async def test():
    engine = CrawlerEngine()
    async with get_async_session() as session:
        items = await engine.run_hotsearch(
            source_ids=["tech.oss.toutiao_tech", "tech.oss.coolapk"],
            db_session=session
        )
        print(f"采集到 {len(items)} 条")
        for ci in items[:3]:
            print(f"  source={ci.source_id}, domain={ci.domain}, sub={ci.sub_domain}, title={ci.title[:50]}")
        await session.commit()

asyncio.run(test())

with get_sync_session() as session:
    stmt = select(CanonicalItemModel.domain, func.count().label("n")).group_by(CanonicalItemModel.domain).order_by(func.count().desc())
    print("\n=== 数据库 domain 分布 ===")
    for r in session.execute(stmt).all():
        print(f"  {repr(r.domain):20s}: {r.n} 条")
