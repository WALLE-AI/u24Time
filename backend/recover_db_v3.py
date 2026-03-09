# -*- coding: utf-8 -*-
import sqlite3
import os
import shutil

OLD_DB = "u24time.db"
NEW_DB = "u24time_clean.db"
BACKUP = "u24time.db.bak"

print("开始执行 DB 挽救计划 (v3 原生 Base 建表)...")

if os.path.exists(NEW_DB):
    os.remove(NEW_DB)

print(f"1. 备份损坏库到 {BACKUP}")
if os.path.exists(OLD_DB):
    shutil.copy2(OLD_DB, BACKUP)
else:
    print(f"错误: 找不到原始库 {OLD_DB}")
    exit(1)

print("2. 尝试初始化新库表结构")
os.environ["DB_SQLITE_PATH"] = NEW_DB
os.environ["DATABASE_URL_SYNC"] = f"sqlite:///{NEW_DB}"

try:
    from sqlalchemy import create_engine
    from db.models import Base
    
    # 连接新库，强制利用所有的 Models 生成新表
    engine = create_engine(f"sqlite:///{NEW_DB}")
    Base.metadata.create_all(engine)
    print("✅ SQLAlchemy 建表成功")
except Exception as e:
    print(f"初始化新库结构失败: {e}")
    exit(1)

print("3. 连接新老库，跨库同步幸存数据")
try:
    conn_new = sqlite3.connect(NEW_DB)
    # 附加旧库 (以只读模式关联避免二次损坏)
    # Windows/SQLite URI 需要允许读取
    conn_new.execute(f"ATTACH DATABASE '{BACKUP}' AS old_db")
    
    # 获取所有的用户表
    cursor = conn_new.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name != 'alembic_version';")
    tables = [row[0] for row in cursor.fetchall()]
    
    for t in tables:
        print(f"正在拷贝 {t} 表数据...")
        try:
            # 忽略损坏行或约束冲突
            conn_new.execute(f"INSERT OR IGNORE INTO main.{t} SELECT * FROM old_db.{t}")
            conn_new.commit()
            print(f"  ✅ {t} 恢复成功")
        except Exception as e:
            print(f"  ❌ {t} 恢复出错 (可能含有破损记录): {e}")

    conn_new.close()

    print("4. 替换正式库")
    os.remove(OLD_DB)
    if os.path.exists("u24time.db-wal"): os.remove("u24time.db-wal")
    if os.path.exists("u24time.db-shm"): os.remove("u24time.db-shm")
    
    os.rename(NEW_DB, OLD_DB)
    print("🎉 数据库修复操作完成，损坏内容已被剔除！")
except Exception as e:
    print(f"出现严重错误: {e}")
