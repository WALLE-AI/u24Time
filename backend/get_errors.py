import sqlite3, json
import codecs

conn = sqlite3.connect('u24time.db')
conn.row_factory = sqlite3.Row
errors = [dict(r) for r in conn.execute('SELECT task_id, source_id, error_message FROM crawl_tasks WHERE status="failed" ORDER BY started_at DESC LIMIT 20').fetchall()]

with codecs.open('errors_utf8.json', 'w', encoding='utf-8') as f:
    json.dump(errors, f, indent=2)
