from sqlalchemy import Column, Integer, String
from src.config import Base, engine


class Player(Base):
    __tablename__ = 'players'
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    priority_role = Column(String, nullable=True)
    tank_rating = Column(Integer, nullable=True)
    damage_rating = Column(Integer, nullable=True)
    support_rating = Column(Integer, nullable=True)
    discord_id = Column(String, nullable=True)
    check_in = Column(String, nullable=True)


class Queue(Base):
    __tablename__ = 'queue'
    id = Column(Integer, primary_key=True, autoincrement=True)
    discord_id = Column(String, nullable=True)


class OldQueue(Base):
    __tablename__ = 'old_queue'
    id = Column(Integer, primary_key=True, autoincrement=True)
    discord_id = Column(String, nullable=True)


Base.metadata.create_all(engine)
