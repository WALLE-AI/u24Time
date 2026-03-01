from db.models import CrawlTaskModel
def inspect_tasks():
    with get_sync_session() as session:
        stmt = select(CrawlTaskModel).order_by(desc(CrawlTaskModel.id)).limit(10)
        tasks = session.scalars(stmt).all()
        print(f"{'ID':<5} | {'Source ID':<35} | {'Status':<10} | {'Aligned':<8} | {'Finished At'}")
        print("-" * 100)
        for t in tasks:
            print(f"{t.id:<5} | {t.source_id:<35} | {t.status:<10} | {t.items_aligned:<8} | {t.finished_at}")

if __name__ == "__main__":
    inspect_tasks()
