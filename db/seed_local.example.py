"""Шаблон стартового сида. Скопируй в db/seed_local.py (он в гитигноре) —
init_db() подхватит его при запуске. Сид обязан быть идемпотентным:
здесь он заливает задачи только в пустую таблицу."""

from sqlalchemy import func, select

from .models import Task

# (название, описание | None, выполнена)
TASKS = [
    ("Пример задачи", None, False),
    ("Пример выполненной задачи", "с описанием", True),
]


async def run(session) -> int:
    if await session.scalar(select(func.count()).select_from(Task)):
        return 0
    session.add_all(Task(name=n, description=d, is_done=done) for n, d, done in TASKS)
    await session.commit()
    return len(TASKS)
