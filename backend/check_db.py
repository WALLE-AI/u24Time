import sqlite3

def run():
    conn = sqlite3.connect("data/memory_index.db")
    try:
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(files)")
        print(cur.fetchall())
    except Exception as e:
        print(e)
run()
