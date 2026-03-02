from db.session import get_sync_session
from db.models import CanonicalItemModel
from sqlalchemy import update

with get_sync_session() as session:
    # 修正 tech.oss.* 源但被归入了 academic 的错误数据
    stmt = (
        update(CanonicalItemModel)
        .where(CanonicalItemModel.domain == 'academic')
        .where(CanonicalItemModel.source_id.in_([
            'tech.oss.github_trending',
            'tech.oss.coolapk',
            'tech.oss.toutiao_tech'
        ]))
        .values(domain='technology', classification_source='fixed')
    )
    result = session.execute(stmt)
    session.commit()
    print(f"成功将 {result.rowcount} 条 tech.oss.* 错误条目从 academic 归位至 technology。")
    
    # 顺便修正可能错误归入了 academic 的 economy.stock.* 条目（如果有）
    stmt2 = (
        update(CanonicalItemModel)
        .where(CanonicalItemModel.domain == 'academic')
        .where(CanonicalItemModel.source_id.in_([
            'economy.stock.wallstreetcn',
            'economy.stock.cls_hot',
            'economy.stock.xueqiu'
        ]))
        .values(domain='economy', classification_source='fixed')
    )
    result2 = session.execute(stmt2)
    session.commit()
    print(f"成功将 {result2.rowcount} 条 economy.stock.* 错误条目从 academic 归位至 economy。")
