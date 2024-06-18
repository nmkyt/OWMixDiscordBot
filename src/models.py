from sqlalchemy import Column, Integer, String
from config import Base, engine


class Player(Base):
    __tablename__ = 'players'
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    tank_rating = Column(Integer, nullable=True)
    damage_rating = Column(Integer, nullable=True)
    support_rating = Column(Integer, nullable=True)


Base.metadata.create_all(engine)
