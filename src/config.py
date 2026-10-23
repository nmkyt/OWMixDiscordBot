import asyncio
import logging
import os

import discord
import sqlalchemy
from discord.ext import commands
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("owmix")

intents = discord.Intents.default()
intents.message_content = True
intents.messages = True
intents.reactions = True

bot = commands.Bot(command_prefix="!", intents=intents)

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не задан. Проверьте файл .env.")

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL не задан. Проверьте файл .env.")


def _parse_admin_ids(raw: str) -> set[int]:
    """Разбирает ADMIN_IDS ('1, 2 3') в множество ID, пропуская некорректные элементы."""
    ids = set()
    for part in raw.replace(",", " ").split():
        try:
            ids.add(int(part))
        except ValueError:
            logger.warning(f'Ignoring invalid ADMIN_IDS entry: {part!r}')
    return ids


ADMIN_IDS = _parse_admin_ids(os.getenv("ADMIN_IDS", ""))
if not ADMIN_IDS:
    logger.warning('ADMIN_IDS is empty or not set in .env: admin commands will be unavailable to everyone')

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
Base = sqlalchemy.orm.declarative_base()

# своя сессия на поток: вся работа с БД идёт через run_db() в отдельных потоках
session = scoped_session(sessionmaker(bind=engine, expire_on_commit=False))


async def run_db(func, *args, **kwargs):
    """Выполняет блокирующую функцию, работающую с БД, в отдельном потоке —
    не блокируя основной event loop бота — и освобождает сессию этого потока
    по завершении (как при успехе, так и при ошибке)."""

    def _call():
        try:
            return func(*args, **kwargs)
        finally:
            session.remove()

    return await asyncio.to_thread(_call)
