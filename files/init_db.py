import asyncio
from db import init_db

async def main():
    await init_db()
    print("DB initialized")

if __name__ == "__main__":
    asyncio.run(main())
