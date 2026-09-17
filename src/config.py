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

# Настройка Discord Bot
intents = discord.Intents.default()
intents.message_content = True
intents.messages = True
intents.reactions = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Токен бота
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не задан. Проверьте файл .env.")

# URL базы данных
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL не задан. Проверьте файл .env.")

# Настройка подключения к базе данных PostgreSQL
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
Base = sqlalchemy.orm.declarative_base()

# scoped_session выдаёт отдельную сессию каждому потоку. Все обращения к БД
# выполняются через run_db() в отдельном потоке (см. ниже), поэтому вместо
# одной общей Session на весь процесс (небезопасно при параллельных командах
# и блокирует event loop бота при каждом запросе) каждая такая операция
# получает свою изолированную сессию.
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
