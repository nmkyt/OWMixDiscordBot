"""
Общая настройка для тестов: делает импорт src.* полностью изолированным от
реального .env / реального Discord-токена / реальной БД миксов.

Тесты подставляют свои значения BOT_TOKEN/DATABASE_URL/ADMIN_IDS ДО первого
импорта src.config (которое require их наличия и на импорте models.py
выполняет Base.metadata.create_all(engine)) — поэтому база для тестов
это одноразовый SQLite-файл во временной директории, а не боевой Postgres.
"""
import atexit
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_tmp_db = tempfile.NamedTemporaryFile(prefix="owmix_test_", suffix=".db", delete=False)
_tmp_db.close()


def _cleanup_tmp_db():
    # На Windows файл SQLite может ещё удерживаться пулом соединений на момент
    # выхода из процесса — это не ошибка тестов, просто не мешаем интерпретатору закрыться.
    try:
        os.remove(_tmp_db.name)
    except OSError:
        pass


atexit.register(_cleanup_tmp_db)

os.environ["BOT_TOKEN"] = "test-token"
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp_db.name}"
os.environ["ADMIN_IDS"] = "111111111111111111,222222222222222222"

import pytest  # noqa: E402

from src.config import session  # noqa: E402
from src.models import Player, Queue  # noqa: E402


@pytest.fixture(autouse=True)
def clean_db():
    """Каждый тест стартует с пустых таблиц players/queue."""
    session.query(Queue).delete()
    session.query(Player).delete()
    session.commit()
    yield
    session.rollback()
    session.query(Queue).delete()
    session.query(Player).delete()
    session.commit()


@pytest.fixture
def make_player():
    """Фабрика игроков для тестов: create(discord_id=..., **overrides) -> Player (уже в БД)."""
    def create(discord_id: str, name: str = None, **overrides):
        defaults = dict(
            name=name or f"Player{discord_id}",
            priority_role=None,
            tank_rating=None,
            damage_rating=None,
            support_rating=None,
            check_in='no',
        )
        defaults.update(overrides)
        player = Player(discord_id=discord_id, **defaults)
        session.add(player)
        session.commit()
        return player
    return create
