import importlib
import logging
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

log = logging.getLogger(__name__)

DB_PATH = Path(__file__).resolve().parent.parent / "tasks.db"

engine = create_async_engine(f"sqlite+aiosqlite:///{DB_PATH}")
Session = async_sessionmaker(engine, expire_on_commit=False)


async def init_db():
    from . import models

    async with engine.begin() as conn:
        await conn.run_sync(models.Base.metadata.create_all)
    await _run_local_seed()


async def _run_local_seed():
    """Стартовый сид из гитигнорного db/seed_local.py (если файл есть).
    Сам сид обязан быть идемпотентным — см. seed_local.example.py."""
    try:
        seed = importlib.import_module("db.seed_local")
    except ModuleNotFoundError:
        return
    async with Session() as session:
        added = await seed.run(session)
    if added:
        log.info("seed_local: залито записей — %s", added)
