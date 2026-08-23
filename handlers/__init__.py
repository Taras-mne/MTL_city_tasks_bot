from aiogram import Router

from . import common, tags, tasks, users

router = Router()
# common первым: /start и отмена должны срабатывать даже посреди ввода текста
router.include_routers(common.router, tasks.router, tags.router, users.router)
