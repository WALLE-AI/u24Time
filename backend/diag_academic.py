from db.session import get_sync_session
from db.models import CanonicalItemModel
from sqlalchemy import select, func

with get_sync_session() as session:
    # 1. academic 域 source_id 分布
    stmt = (
        select(CanonicalItemModel.source_id, func.count().label("n"))
        .where(CanonicalItemModel.domain == "academic")
        .group_by(CanonicalItemModel.source_id)
        .order_by(func.count().desc())
    )
    print("=== academic 域 source_id 分布 ===")
    for r in session.execute(stmt).all():
        print(f"  {r.source_id}: {r.n} 条")

    # 2. 查看 academic 域里看起来像娱乐的条目（sub_domain 非学术）
    print("\n=== academic 域 sub_domain 分布 ===")
    stmt2 = (
        select(CanonicalItemModel.sub_domain, func.count().label("n"))
        .where(CanonicalItemModel.domain == "academic")
        .group_by(CanonicalItemModel.sub_domain)
        .order_by(func.count().desc())
    )
    for r in session.execute(stmt2).all():
        print(f"  sub_domain={repr(r.sub_domain)}: {r.n} 条")

    # 3. 查看 academic 域里 source_id 包含 social/hotsearch/weibo 的条目
    print("\n=== academic 域里可疑条目（前20）===")
    stmt3 = (
        select(CanonicalItemModel)
        .where(CanonicalItemModel.domain == "academic")
        .where(
            CanonicalItemModel.source_id.like("global.social.%") |
            CanonicalItemModel.source_id.like("hotsearch.%") |
            CanonicalItemModel.source_id.like("tech.oss.%")
        )
        .limit(10)
    )
    rows = session.scalars(stmt3).all()
    if rows:
        for r in rows:
            print(f"  source={r.source_id}, sub={r.sub_domain}, title={r.title[:60]}")
    else:
        print("  无可疑来源")

    # 4. 查看前端 academic tab 实际查询：/api/v1/items?domain=academic&limit=20
    # 即按 hotness_score desc 排序的前 20 条
    print("\n=== 前端学术热搜 Top-10（按 hotness 排序）===")
    stmt4 = (
        select(CanonicalItemModel)
        .where(CanonicalItemModel.domain == "academic")
        .order_by(CanonicalItemModel.hotness_score.desc(), CanonicalItemModel.crawled_at.desc())
        .limit(10)
    )
    for r in session.scalars(stmt4).all():
        print(f"  [{r.hotness_score:.1f}] source={r.source_id}, sub={r.sub_domain}, title={r.title[:60]}")
