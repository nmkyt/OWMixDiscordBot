import asyncio
import logging
import os

import discord
import sqlalchemy
from discord.ext import commands
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.engine import URL
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

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")


def _resolve_database_url(raw: str | None) -> str | URL:
    """DATABASE_URL из .env как есть (PostgreSQL, SQLite — любой URL SQLAlchemy); если не задан —
    локальный SQLite-файл data/owmix.db, который создаётся автоматически."""
    if raw and raw.strip():
        return raw.strip()
    os.makedirs(DATA_DIR, exist_ok=True)
    return URL.create("sqlite", database=os.path.join(DATA_DIR, "owmix.db"))


DATABASE_URL = _resolve_database_url(os.getenv("DATABASE_URL"))


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

try:
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
except ModuleNotFoundError as e:
    raise RuntimeError(f"Не установлен драйвер базы данных ({e.name}). "
                       f"Для PostgreSQL: pip install -r requirements-postgres.txt") from e
logger.info(f'Database: {engine.dialect.name}')
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
