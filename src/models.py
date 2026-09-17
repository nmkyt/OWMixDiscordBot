from sqlalchemy import CheckConstraint, Column, Integer, String
from src.config import Base, engine

MIN_RATING = 1000
MAX_RATING = 5000
ROLES = ('tank', 'damage', 'support', 'flex')


class Player(Base):
    __tablename__ = 'players'
    __table_args__ = (
        CheckConstraint("check_in IN ('yes', 'no')", name='ck_players_check_in'),
        CheckConstraint(
            "priority_role IS NULL OR priority_role IN ('tank', 'damage', 'support', 'flex')",
            name='ck_players_priority_role',
        ),
        CheckConstraint(
            f"tank_rating IS NULL OR tank_rating BETWEEN {MIN_RATING} AND {MAX_RATING}",
            name='ck_players_tank_rating',
        ),
        CheckConstraint(
            f"damage_rating IS NULL OR damage_rating BETWEEN {MIN_RATING} AND {MAX_RATING}",
            name='ck_players_damage_rating',
        ),
        CheckConstraint(
            f"support_rating IS NULL OR support_rating BETWEEN {MIN_RATING} AND {MAX_RATING}",
            name='ck_players_support_rating',
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    priority_role = Column(String, nullable=True)
    tank_rating = Column(Integer, nullable=True)
    damage_rating = Column(Integer, nullable=True)
    support_rating = Column(Integer, nullable=True)
    discord_id = Column(String, nullable=False, unique=True)
    check_in = Column(String, nullable=False, default='no', server_default='no')


class Queue(Base):
    __tablename__ = 'queue'
    id = Column(Integer, primary_key=True, autoincrement=True)
    discord_id = Column(String, nullable=False, unique=True)


Base.metadata.create_all(engine)
