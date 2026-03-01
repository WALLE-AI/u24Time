import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "backend", "u24time.db")

TECH_NEWS_SOURCES = [
    "tech.oss.hackernews",
    "tech.oss.tech_events",
    "tech.oss.techcrunch",
    "tech.oss.coolapk",
    "tech.oss.toutiao_tech"
]

def update_db():
    print(f"Connecting to {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    placeholders = ",".join(["?"] * len(TECH_NEWS_SOURCES))
    query = f"UPDATE canonical_items SET sub_domain = 'tech_news' WHERE source_id IN ({placeholders}) AND sub_domain = 'oss'"
    
    cursor.execute(query, TECH_NEWS_SOURCES)
    rows_affected = cursor.rowcount
    conn.commit()
    conn.close()
    
    print(f"Updated {rows_affected} items to 'tech_news' sub_domain.")

if __name__ == "__main__":
    update_db()
