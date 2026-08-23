import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage

import config
from db.base import init_db
from handlers import router
from middlewares.access import AccessMiddleware
from notifier import notifier


async def main():
    logging.basicConfig(level=logging.INFO)
    await init_db()
    bot = Bot(config.BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher(storage=MemoryStorage())
    dp.update.outer_middleware(AccessMiddleware())
    dp.include_router(router)
    await bot.delete_webhook(drop_pending_updates=True)
    digest_task = asyncio.create_task(notifier(bot))
    try:
        await dp.start_polling(bot)
    finally:
        digest_task.cancel()


if __name__ == "__main__":
    asyncio.run(main())
