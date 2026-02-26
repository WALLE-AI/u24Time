import asyncio
from db.session import init_db
from loguru import logger

async def main():
    logger.info("Initializing database...")
    try:
        await init_db()
        logger.info("Database initialized successfully.")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")

if __name__ == "__main__":
    asyncio.run(main())
