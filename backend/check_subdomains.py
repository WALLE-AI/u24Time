import asyncio
from db.session import get_sync_session
from db.models import CanonicalItemModel
from sqlalchemy import select, func

def check_subdomains():
    with get_sync_session() as session:
        stmt = select(CanonicalItemModel.domain, CanonicalItemModel.sub_domain, func.count().label("count")).group_by(CanonicalItemModel.domain, CanonicalItemModel.sub_domain)
        rows = session.execute(stmt).all()
        print("Database Sub-domain Distribution:")
        for row in rows:
            print(f"- Domain: {row.domain}, Sub-domain: {row.sub_domain}, Count: {row.count}")

if __name__ == "__main__":
    check_subdomains()
