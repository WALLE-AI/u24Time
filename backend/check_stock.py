from sqlalchemy import select, func, desc
from db.session import get_sync_session
from db.models import CanonicalItemModel

def check_stock_data():
    with get_sync_session() as session:
        # Check all unique sub_domains in economy domain
        stmt = select(CanonicalItemModel.sub_domain).where(CanonicalItemModel.domain == "economy").distinct()
        subs = session.scalars(stmt).all()
        print(f"Unique Economy Sub-domains: {subs}")

        for sub in subs:
            count = session.query(func.count(CanonicalItemModel.id)).filter(
                CanonicalItemModel.domain == "economy",
                CanonicalItemModel.sub_domain == sub
            ).scalar()
            print(f"- {sub}: {count}")
            
        # Check details for stock and futures
        for sub in ["stock", "futures"]:
            print(f"\nRecent {sub.upper()} Items:")
            stmt_items = select(CanonicalItemModel).where(
                CanonicalItemModel.domain == "economy",
                CanonicalItemModel.sub_domain == sub
            ).order_by(desc(CanonicalItemModel.id)).limit(5)
            items = session.scalars(stmt_items).all()
            for item in items:
                print(f"ID: {item.id} | Source: {item.source_id} | Title: {item.title[:60]}")

if __name__ == "__main__":
    check_stock_data()
