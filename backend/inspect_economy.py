from sqlalchemy import select, desc
from db.session import get_sync_session
from db.models import CanonicalItemModel

def inspect_economy_subdomains():
    with get_sync_session() as session:
        stmt = select(CanonicalItemModel).where(CanonicalItemModel.domain == "economy").order_by(desc(CanonicalItemModel.id)).limit(100)
        items = session.scalars(stmt).all()
        print(f"{'ID':<5} | {'Source ID':<35} | {'Sub-Domain':<12} | {'Title'}")
        print("-" * 120)
        for item in items:
            print(f"{item.id:<5} | {item.source_id:<35} | {item.sub_domain:<12} | {item.title[:60]}")

if __name__ == "__main__":
    inspect_economy_subdomains()
