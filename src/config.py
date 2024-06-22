import os
from dotenv import load_dotenv
import discord
from discord.ext import commands
import sqlalchemy
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Настройка Discord Bot
intents = discord.Intents.default()
intents.message_content = True
intents.messages = True
intents.reactions = True

bot = commands.Bot(command_prefix="!", intents=intents)

load_dotenv()

# Токен бота
BOT_TOKEN = (os.getenv("BOT_TOKEN"))


# URL Базы данных
DATABASE_URL = (os.getenv("DATABASE_URL"))

# Настройка подключения к базе данных PostgreSQL
engine = create_engine(DATABASE_URL)
Session = sessionmaker(bind=engine)
session = Session()
Base = sqlalchemy.orm.declarative_base()
