"""
Тесты на реальные ограничения БД (CHECK/UNIQUE/NOT NULL), объявленные в src/models.py.
Гоняются против одноразового SQLite (см. conftest.py) — проверяют, что схема
действительно отклоняет "глупости", а не просто что Python-код их не пишет.
"""
import pytest
from sqlalchemy.exc import IntegrityError

from src.config import session
from src.models import Player, Queue


def _make(discord_id='1', **overrides):
    defaults = dict(name='P', priority_role=None, tank_rating=None,
                     damage_rating=None, support_rating=None, check_in='no')
    defaults.update(overrides)
    return Player(discord_id=discord_id, **defaults)


class TestCheckInConstraint:
    def test_valid_values_accepted(self):
        session.add(_make('1', check_in='yes'))
        session.commit()  # не должно бросить

    def test_invalid_value_rejected(self):
        session.add(_make('1', check_in='maybe'))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

    def test_defaults_to_no_when_omitted(self):
        p = Player(discord_id='1', name='P')
        session.add(p)
        session.commit()
        assert p.check_in == 'no'


class TestPriorityRoleConstraint:
    def test_valid_roles_accepted(self):
        for i, role in enumerate(('tank', 'damage', 'support', 'flex', None)):
            session.add(_make(str(i), priority_role=role))
        session.commit()

    def test_invalid_role_rejected(self):
        session.add(_make('1', priority_role='healer'))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


class TestRatingConstraints:
    def test_within_range_accepted(self):
        session.add(_make('1', tank_rating=1000))
        session.add(_make('2', tank_rating=5000))
        session.commit()

    def test_below_min_rejected(self):
        session.add(_make('1', tank_rating=999))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

    def test_above_max_rejected(self):
        session.add(_make('1', damage_rating=5001))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

    def test_null_rating_accepted(self):
        session.add(_make('1', support_rating=None))
        session.commit()


class TestDiscordIdConstraints:
    def test_not_null(self):
        p = Player(discord_id=None, name='P', check_in='no')
        session.add(p)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

    def test_unique(self):
        session.add(_make('1'))
        session.commit()
        session.add(_make('1'))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


class TestQueueConstraints:
    def test_discord_id_not_null(self):
        session.add(Queue(discord_id=None))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

    def test_discord_id_unique(self):
        session.add(Queue(discord_id='1'))
        session.commit()
        session.add(Queue(discord_id='1'))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
