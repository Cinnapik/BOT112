# init_db.py
# Отдельный скрипт чтобы один раз создать/обновить таблицы в БД.
# Удобно запускать перед стартом бота.

import asyncio
from db import init_db

async def main():
    await init_db()
    print("DB initialized")

if __name__ == "__main__":
    asyncio.run(main())
