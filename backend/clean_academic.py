from db.session import get_sync_session
from db.models import CanonicalItemModel
from sqlalchemy import delete

with get_sync_session() as session:
    # 彻底清理：只要是被打上 academic 标签，但数据并非学术信息来源，就一刀切咔掉。
    stmt = (
        delete(CanonicalItemModel)
        .where(CanonicalItemModel.domain == 'academic')
        .where(~CanonicalItemModel.source_id.startswith('academic.'))
    )
    result = session.execute(stmt)
    session.commit()
    print(f"成功删除了 {result.rowcount} 条混入学术域的垃圾/受污染数据。")
