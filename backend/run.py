import os
import sys
import uvicorn
from loguru import logger

def main():
    # 确保 backend 目录在 sys.path 中
    backend_dir = os.path.dirname(os.path.abspath(__file__))
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)

    logger.info("Starting U24Time API Server via run.py...")
    
    # 启动 uvicorn 服务
    uvicorn.run(
        "server:app",
        host="0.0.0.0",
        port=5001,
        reload=True,
        log_level="info",
        reload_dirs=[backend_dir]
    )

if __name__ == "__main__":
    main()
