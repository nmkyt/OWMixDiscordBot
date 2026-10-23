"""
Тесты сообщений об ошибках: на любую ошибку пользователя бот обязан ответить в чат
в едином формате («❌ что не так» + пример команды, если он уместен).

Команды прогоняются через настоящий разбор аргументов и проверки discord.py
(Command.invoke) — без сети: подменяется только отправка сообщения.
"""
import asyncio
from types import SimpleNamespace

import pytest
from discord.ext import commands
from discord.ext.commands.view import StringView

import src.bot_controller as bc
from src.config import bot, session
from src.models import Player, Queue

ADMIN_ID = 111111111111111111
PLAYER_ID = 333333333333333333


class FakeContext(commands.Context):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.sent = []

    async def send(self, content=None, **kwargs):
        self.sent.append(content)


def run_command(content, author_id=PLAYER_ID):
    """Выполняет команду как бот: разбор, проверки, вызов, on_command_error. Возвращает отправленные сообщения."""
    async def _run():
        view = StringView(content)
        view.skip_string(bot.command_prefix)
        invoked = view.get_word()
        message = SimpleNamespace(content=content, author=SimpleNamespace(id=author_id, name='tester'),
                                  _state=None, attachments=[])
        ctx = FakeContext(message=message, bot=bot, view=view, prefix=bot.command_prefix,
                          invoked_with=invoked, command=bot.get_command(invoked))
        try:
            if ctx.command is None:
                raise commands.CommandNotFound(f'Command "{invoked}" is not found')
            await ctx.command.invoke(ctx)
        except commands.CommandError as e:
            await bc.on_command_error(ctx, e)
        return ctx.sent

    return asyncio.run(_run())


def last(content, author_id=PLAYER_ID):
    sent = run_command(content, author_id)
    assert sent, f'бот ничего не ответил на {content!r}'
    return sent[-1]


@pytest.mark.parametrize('content, author_id', [
    ('!unknown_cmd', PLAYER_ID),
    ('!register', PLAYER_ID),
    ('!register Tag#1 3000', PLAYER_ID),
    ('!register Tag#1 3000 3000 3000 extra', PLAYER_ID),
    ('!register badtag 3000 3000 3000', PLAYER_ID),
    ('!register Tag#1 abc 3000 3000', PLAYER_ID),
    ('!register Tag#1 100 3000 3000', PLAYER_ID),
    ('!register Tag#1 0 0 0', PLAYER_ID),
    ('!register "Tag#1 3000 3000 3000', PLAYER_ID),
    ('!update 3000 3000 3000', PLAYER_ID),
    ('!update 3000', PLAYER_ID),
    ('!my_rank', PLAYER_ID),
    ('!check', PLAYER_ID),
    ('!create_lobby 1', PLAYER_ID),
    ('!queue_add', PLAYER_ID),
    ('!mix_stop', PLAYER_ID),
    ('!mix_status', PLAYER_ID),
    ('!create_lobby', ADMIN_ID),
    ('!create_lobby abc', ADMIN_ID),
    ('!create_lobby 0', ADMIN_ID),
    ('!create_lobby 5', ADMIN_ID),
    ('!queue_add abc', ADMIN_ID),
    ('!queue_add 123', ADMIN_ID),
    ('!queue_remove 123', ADMIN_ID),
    ('!uncheck 123', ADMIN_ID),
    ('!user_update 123 3000 3000 3000', ADMIN_ID),
])
def test_every_user_error_is_reported_in_unified_format(content, author_id):
    assert last(content, author_id).startswith('❌ ')


class TestMessages:
    def test_unknown_command_points_to_help(self):
        assert '!mix_help' in last('!regster Tag#1 3000 3000 3000')

    def test_missing_argument_is_named_and_has_example(self):
        msg = last('!register Tag#1 3000 3000')
        assert 'рейтинг саппорта' in msg
        assert 'Пример: `!register' in msg

    def test_too_many_arguments(self):
        assert 'Лишние аргументы' in last('!update 3000 3000 3000 4000')

    def test_bad_int_argument_is_named(self):
        assert 'количество лобби' in last('!create_lobby abc', ADMIN_ID)

    def test_rating_error_names_role_and_value(self):
        msg = last('!register Tag#1 3000 xyz 3000')
        assert msg.startswith('❌ DPS: неверный рейтинг «xyz»')

    def test_non_admin_gets_permission_error_before_argument_errors(self):
        """Регрессия: раньше не-админ на админ-команду не получал вообще никакого ответа."""
        assert 'недостаточно прав' in last('!queue_add')
        assert 'недостаточно прав' in last('!create_lobby 2')

    def test_db_failure_is_reported_as_system_error(self, monkeypatch):
        async def broken_db(*args, **kwargs):
            raise RuntimeError('db down')
        monkeypatch.setattr(bc, 'run_db', broken_db)
        assert last('!mix_status', ADMIN_ID).startswith('⚠️ ')

    def test_unhandled_exception_is_still_reported(self, monkeypatch):
        """Даже ошибка, которую команда не предусмотрела, должна дойти до чата."""
        # битое лобби от балансера -> TypeError при выводе составов, вне всех try в команде
        monkeypatch.setattr(bc, 'create_lobbies_caller', lambda n: ([{'team1': None, 'team2': None}], []))
        assert last('!create_lobby 1', ADMIN_ID).startswith('⚠️ ')


class TestRegisterAndUpdate:
    def test_all_roles_zero_rejected(self):
        assert 'хотя бы на одной роли' in last('!register Tag#1 0 0 0')
        assert session.query(Player).count() == 0

    def test_valid_registration_still_works(self):
        assert last('!register Tag#1 3000 d2 0') == 'Вы успешно зарегистрировались на миксы'

    def test_registration_alias_works_like_register(self):
        assert last('!registration Tag#1 3000 d2 0') == 'Вы успешно зарегистрировались на миксы'
        assert session.query(Player).filter(Player.discord_id == str(PLAYER_ID)).count() == 1

    def test_registration_alias_error_shows_alias_in_example(self):
        msg = last('!registration Tag#1 3000')
        assert msg.startswith('❌ Не хватает аргумента')
        assert 'Пример: `!registration Sacr1ficed#2456' in msg

    def test_already_registered(self, make_player):
        make_player(str(PLAYER_ID))
        assert 'уже зарегистрированы' in last('!register Tag#1 3000 3000 3000')

    def test_update_cannot_zero_priority_role(self, make_player):
        make_player(str(PLAYER_ID), priority_role='tank', tank_rating=3000)
        assert 'нельзя обнулить' in last('!update 0 3000 3000')

    def test_update_not_registered(self):
        assert last('!update 3000 3000 3000') == bc.NOT_REGISTERED


class TestAdminCommands:
    def test_queue_add_accepts_mention_and_rejects_duplicate(self, make_player):
        make_player('42', name='Alice', check_in='yes')
        assert last('!queue_add <@42>', ADMIN_ID) == 'Alice успешно добавлен в очередь'
        assert last('!queue_add 42', ADMIN_ID) == '❌ Alice уже в очереди.'

    def test_queue_add_warns_if_not_checked_in(self, make_player):
        make_player('42', name='Alice', check_in='no')
        assert 'не прошёл чек-ин' in last('!queue_add 42', ADMIN_ID)

    def test_create_lobby_error_keeps_queue(self, make_player):
        """Регрессия: при отказе (лобби больше, чем игроков) очередь раньше молча стиралась."""
        make_player('1', check_in='yes', priority_role='tank', tank_rating=3000)
        session.add(Queue(discord_id='1'))
        session.commit()

        msg = last('!create_lobby 3', ADMIN_ID)

        assert 'нужно 30 отметившихся игроков, сейчас 1' in msg
        assert session.query(Queue).count() == 1

    def test_user_update_unknown_user(self):
        assert 'не зарегистрирован' in last('!user_update 999 3000 3000 3000', ADMIN_ID)
