import os
import subprocess
import time
import shutil

DB_FILE = "u24time.db"
RECOVER_FILE = "u24time_recovered.db"
BACKUP_FILE = f"u24time_broken_{int(time.time())}.db"

print(f"=== 开始尝试修复损坏的数据库 {DB_FILE} ===")

if not os.path.exists(DB_FILE):
    print(f"❌ 找不到数据库文件: {DB_FILE}")
    exit(1)

# 1. 备份原文件
print(f"📌 备份原数据库到: {BACKUP_FILE}")
shutil.copy2(DB_FILE, BACKUP_FILE)
if os.path.exists("u24time.db-wal"):
    shutil.copy2("u24time.db-wal", f"{BACKUP_FILE}-wal")
if os.path.exists("u24time.db-shm"):
    shutil.copy2("u24time.db-shm", f"{BACKUP_FILE}-shm")

# 2. 导出为 SQL 转储并导入到新数据库
print(f"📌 尝试通过 sqlite3 dump 恢复数据到新文件: {RECOVER_FILE}")

if os.path.exists(RECOVER_FILE):
    os.remove(RECOVER_FILE)

# Windows 下通常自带 sqlite3，尝试调用来导出不损坏的表内容
# sqlite3 u24time.db ".dump" | sqlite3 u24time_recovered.db
try:
    ps_cmd = f"sqlite3 {DB_FILE} '.dump' | sqlite3 {RECOVER_FILE}"
    process = subprocess.run(
        ["powershell", "-Command", ps_cmd],
        capture_output=True,
        text=True
    )
    
    if os.path.exists(RECOVER_FILE) and os.path.getsize(RECOVER_FILE) > 0:
        print("✅ dump 恢复成功。")
    else:
        print("❌ dump 恢复失败或新文件为空。请检查输出:")
        print("STDOUT:", process.stdout)
        print("STDERR:", process.stderr)
        
        print("\n\n!!如果上述管道命令在当前机器不工作，尝试使用纯 python 暴力提取数据。!!")
        exit(1)

except Exception as e:
    print(f"❌ 修复执行异常: {e}")
    exit(1)

# 3. 替换原文件
print(f"📌 用恢复后的文件覆盖原文件")
os.remove(DB_FILE)
if os.path.exists("u24time.db-wal"): os.remove("u24time.db-wal")
if os.path.exists("u24time.db-shm"): os.remove("u24time.db-shm")

os.rename(RECOVER_FILE, DB_FILE)

print("🎉 修复流程结束。请重启相关服务尝试重新读取数据库！")
