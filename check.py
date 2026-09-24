import asyncio
from app.db.database import async_session_maker
from sqlalchemy import text
async def main():
    async with async_session_maker() as s:
        res = await s.execute(text('SELECT id, name FROM users_role'))
        print(res.fetchall())
asyncio.run(main())
