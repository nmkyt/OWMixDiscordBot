import re

import discord

from discord.ext import commands

from src.config import bot, BOT_TOKEN, ADMIN_IDS, session, run_db, logger
from src.models import Player, Queue
from src.balancer import reset_history
from src.sync_logic import (
    create_lobbies_caller,
    get_map,
    get_rating,
    check_queue,
    active_players,
    mix_status as get_mix_status,
    end,
    format_rating,
    parse_rating_input,
    parse_rating_update,
)

admins = ADMIN_IDS

# Пример battle_tag: Sacr1ficed#2456
BATTLE_TAG_PATTERN = re.compile(r"^[\w]+#\d+$")
# discord_id в админ-командах: числовой ID или упоминание <@123> / <@!123>
DISCORD_ID_PATTERN = re.compile(r"^(?:<@!?(\d+)>|(\d+))$")

# Пример правильного вызова для каждой команды с аргументами — подставляется
# в сообщения об ошибках ввода, чтобы пользователь сразу видел, как надо.
USAGE = {
    'register': '!register Sacr1ficed#2456 4000 d2 3700',
    'update': '!update 4000 d2 3700',
    'user_update': '!user_update <discord_id> 4000 d2 3700',
    'queue_add': '!queue_add <discord_id>',
    'queue_remove': '!queue_remove <discord_id>',
    'uncheck': '!uncheck <discord_id>',
    'create_lobby': '!create_lobby 2',
}

PARAM_LABELS = {
    'battle_tag': 'BattleTag',
    'tank_rating': 'рейтинг танка',
    'damage_rating': 'рейтинг DPS',
    'support_rating': 'рейтинг саппорта',
    'discord_id': 'discord_id',
    'user_id': 'discord_id',
    'lobby_count': 'количество лобби',
}

ROLE_INPUT_LABELS = {'tank': 'Танк', 'damage': 'DPS', 'support': 'Саппорт'}


def error_text(problem: str, usage: str = None) -> str:
    """Единый формат сообщения об ошибке ввода: что не так + (если есть) пример правильной команды."""
    text = f'❌ {problem}'
    if usage:
        text += f'\nПример: `{usage}`'
    return text


def system_error_text(action: str) -> str:
    """Единый формат сообщения о сбое на стороне бота (не по вине пользователя)."""
    return f'⚠️ Не удалось {action}. Попробуйте ещё раз чуть позже.'


NOT_REGISTERED = error_text('Вы не зарегистрированы. Сначала зарегистрируйтесь через !register.', USAGE['register'])


class InputError(commands.CommandError):
    """Ошибка ввода пользователя. Бросается из команды и показывается в чате
    в едином формате через on_command_error (с примером команды, если with_usage)."""

    def __init__(self, problem: str, with_usage: bool = True):
        super().__init__(problem)
        self.problem = problem
        self.with_usage = with_usage


class NotAdmin(commands.CheckFailure):
    pass


def admin_only():
    """Проверка прав до разбора аргументов: не-админ всегда получает понятный отказ,
    а не молчание бота или ошибку про аргументы."""
    async def predicate(ctx):
        if ctx.author.id not in admins:
            raise NotAdmin()
        return True
    return commands.check(predicate)


def parse_discord_id(raw: str) -> str:
    match = DISCORD_ID_PATTERN.match(raw.strip())
    if match is None:
        raise InputError(f'Некорректный discord_id «{raw}»: нужен числовой ID или упоминание @игрока.')
    return match.group(1) or match.group(2)


def parse_ratings(tank_rating: str, damage_rating: str, support_rating: str, priority=None, protect_priority=False):
    """Разбирает рейтинги трёх ролей. Ошибка в любой из них -> InputError с названием роли.
    protect_priority=True запрещает обнулить рейтинг приоритетной роли (см. parse_rating_update)."""
    values = {}
    for role, raw in (('tank', tank_rating), ('damage', damage_rating), ('support', support_rating)):
        try:
            if protect_priority:
                values[role] = parse_rating_update(raw, role, priority)
            else:
                values[role] = parse_rating_input(raw)
        except ValueError as e:
            raise InputError(f'{ROLE_INPUT_LABELS[role]}: {e}')
    if all(value is None for value in values.values()):
        raise InputError('Укажите рейтинг хотя бы на одной роли (0 — только для ролей, которые вы не играете).')
    return values['tank'], values['damage'], values['support']


def update_user_status(user_id, field, value):
    """Синхронная работа с БД; вызывается только через run_db в отдельном потоке."""
    user = session.query(Player).filter(Player.discord_id == str(user_id)).first()
    if user is None:
        return 'not_registered'

    if field == 'checked_in':
        if value == 'yes' and not user.priority_role:
            return 'no_role'
        user.check_in = value
        session.commit()
        return True

    if field == 'priority_role':
        if value == 'flex':
            if user.tank_rating is not None and user.damage_rating is not None and user.support_rating is not None:
                user.priority_role = value
                session.commit()
                return True
            return False
        rating_attr = {'tank': 'tank_rating', 'damage': 'damage_rating', 'support': 'support_rating'}.get(value)
        if rating_attr and getattr(user, rating_attr) is not None:
            user.priority_role = value
            session.commit()
            return True
        return False

    return False


class CheckinView(discord.ui.View):
    message: discord.Message = None

    async def on_timeout(self):
        """Без этого после таймаута кнопки выглядят живыми, а клик по ним даёт лишь
        безликое «Interaction failed» — вместо этого явно показываем, что чек-ин закрыт."""
        for item in self.children:
            item.disabled = True
        if self.message is None:
            return
        try:
            await self.message.edit(content=f'{self.message.content}\n\n🔒 Чек-ин закрыт. '
                                            f'Попросите администратора открыть новый через !check.', view=self)
        except Exception as e:
            logger.warning(f'Could not disable check-in buttons: {e}')

    async def on_error(self, interaction: discord.Interaction, error: Exception, item):
        """Предохранитель на уровне кнопок: ошибка в одном клике не должна ронять бота
        и не должна оставлять пользователя без ответа."""
        logger.error(f'Error in CheckinView item {item}: {error}', exc_info=error)
        try:
            message = system_error_text('обработать нажатие')
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
        except Exception:
            pass

    @discord.ui.button(label='✅Check-in', style=discord.ButtonStyle.success)
    async def check_in(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = interaction.user.id
        user_name = interaction.user.name
        await interaction.response.defer()
        try:
            result = await run_db(update_user_status, user_id, 'checked_in', 'yes')
        except Exception as e:
            logger.error(f'Error checking in {user_name}: {e}')
            await interaction.followup.send(system_error_text('пройти чек-ин'), ephemeral=True)
            return
        if result == 'not_registered':
            await interaction.followup.send(NOT_REGISTERED, ephemeral=True)
            return
        if result == 'no_role':
            await interaction.followup.send(error_text(
                'Сначала выберите приоритетную роль (🛡️ Tank / 🏹 DPS / 💉 Support / 🎲 Flex), '
                'затем нажмите ✅ Check-in.'), ephemeral=True)
            return
        logger.info(f'User {user_name} successfully checked in.')
        await interaction.followup.send(f"{user_name} успешно прошел чек-ин.", ephemeral=True)

    @discord.ui.button(label='❌Check-out', style=discord.ButtonStyle.danger)
    async def check_out(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = interaction.user.id
        user_name = interaction.user.name
        await interaction.response.defer()
        try:
            result = await run_db(update_user_status, user_id, 'checked_in', 'no')
        except Exception as e:
            logger.error(f'Error checking out {user_name}: {e}')
            await interaction.followup.send(system_error_text('пройти чек-аут'), ephemeral=True)
            return
        if result == 'not_registered':
            await interaction.followup.send(NOT_REGISTERED, ephemeral=True)
            return
        logger.info(f'User {user_name} successfully checked out.')
        await interaction.followup.send(f"{user_name} успешно прошел чек-аут", ephemeral=True)

    async def _set_priority_role(self, interaction: discord.Interaction, role: str,
                                  role_label: str, requirement_msg: str):
        user_id = interaction.user.id
        user_name = interaction.user.name
        await interaction.response.defer()
        try:
            result = await run_db(update_user_status, user_id, 'priority_role', role)
        except Exception as e:
            logger.error(f'Error setting priority role for {user_name}: {e}')
            await interaction.followup.send(system_error_text('выбрать роль'), ephemeral=True)
            return
        if result == 'not_registered':
            await interaction.followup.send(NOT_REGISTERED, ephemeral=True)
        elif result:
            logger.info(f'User {user_name} set priority role as {role}.')
            await interaction.followup.send(f"{user_name} успешно выбрал {role_label} приоритетной ролью", ephemeral=True)
        else:
            await interaction.followup.send(error_text(requirement_msg, USAGE['update']), ephemeral=True)

    @discord.ui.button(label='🛡️ Tank', style=discord.ButtonStyle.gray)
    async def tank(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._set_priority_role(
            interaction, 'tank', 'танка',
            'Чтобы выбрать танка приоритетной ролью, сначала укажите рейтинг на нём через !update.'
        )

    @discord.ui.button(label='🏹 DPS', style=discord.ButtonStyle.gray)
    async def dps(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._set_priority_role(
            interaction, 'damage', 'урон',
            'Чтобы выбрать урон приоритетной ролью, сначала укажите рейтинг на нём через !update.'
        )

    @discord.ui.button(label='💉 Support', style=discord.ButtonStyle.gray)
    async def support(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._set_priority_role(
            interaction, 'support', 'поддержку',
            'Чтобы выбрать поддержку приоритетной ролью, сначала укажите рейтинг на ней через !update.'
        )

    @discord.ui.button(label='🎲 Flex', style=discord.ButtonStyle.gray)
    async def flex(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._set_priority_role(
            interaction, 'flex', 'flex',
            'Чтобы выбрать flex, укажите рейтинг на всех трёх ролях через !update.'
        )


@bot.event
async def on_ready():
    logger.info(f'Logged in as {bot.user.name}')
    logger.info('Overwatch Mix Discord Bot v2.1')
    logger.info('Developed by nmkyt')
    logger.info('Command list available at !mix_help in Discord app')


def _usage(ctx):
    if ctx.command is None or ctx.command.name not in USAGE:
        return None
    # вызвали через алиас (!registration) — в примере показываем то же имя, что набрал пользователь
    return USAGE[ctx.command.name].replace(f'!{ctx.command.name}', f'!{ctx.invoked_with}', 1)


@bot.event
async def on_command_error(ctx, error):
    """Общий предохранитель: ни одна ошибка в команде не должна проходить незамеченной
    и не должна ронять бота — пользователь всегда получает ответ в едином формате,
    а непредвиденные ошибки дополнительно логируются."""
    if isinstance(error, commands.CommandNotFound):
        message = error_text(f'Неизвестная команда «!{ctx.invoked_with}». Список команд: !mix_help.')
    elif isinstance(error, NotAdmin):
        message = error_text('У вас недостаточно прав для выполнения этой команды.')
    elif isinstance(error, InputError):
        message = error_text(error.problem, _usage(ctx) if error.with_usage else None)
    elif isinstance(error, commands.MissingRequiredArgument):
        label = PARAM_LABELS.get(error.param.name, error.param.name)
        message = error_text(f'Не хватает аргумента «{label}».', _usage(ctx))
    elif isinstance(error, commands.TooManyArguments):
        message = error_text('Лишние аргументы в команде.', _usage(ctx))
    elif isinstance(error, (commands.BadArgument, commands.BadUnionArgument)):
        param = getattr(ctx, 'current_parameter', None)
        label = PARAM_LABELS.get(param.name, param.name) if param else 'аргумента'
        message = error_text(f'Некорректное значение «{label}».', _usage(ctx))
    elif isinstance(error, commands.UserInputError):
        # прочие ошибки разбора (незакрытые кавычки и т.п.)
        message = error_text('Не удалось разобрать команду — проверьте кавычки и пробелы.', _usage(ctx))
    elif isinstance(error, commands.CommandOnCooldown):
        message = error_text('Команда на перезарядке, попробуйте чуть позже.')
    elif isinstance(error, commands.CheckFailure):
        message = error_text('Эту команду сейчас нельзя выполнить.')
    else:
        original = getattr(error, 'original', error)
        logger.error(f'Unhandled error in command "{ctx.command}": {original}', exc_info=original)
        message = system_error_text('выполнить команду')

    try:
        await ctx.send(message)
    except Exception as e:
        logger.error(f'Could not report command error to chat: {e}')


@bot.command()
@admin_only()
async def check(ctx):
    view = CheckinView(timeout=20000)
    await ctx.send(
        'Чекин на миксы начался! Обратите внимание, что пройти check-in могут только зарегистрированные игроки.')
    view.message = await ctx.send(
        'Нажмите ✅ и выберите приоритетную роль. Пожалуйста, нажмите ❌, если покидаете миксы.', view=view)


@bot.command()
async def mix_help(ctx):
    await ctx.send(f"--------------------------------**Список команд**--------------------------------\n"
                   f"• Для регистрации в боте используйте **«!register BattleTag TankRating DPSRating "
                   f"SupportRating»** (или **«!registration ...»**)\n"
                   f"где Tank, DPS и Support Rating - цифра или дивизион вашего рейтинга в OW. пр.: m2, 2700, g4 итп.\n"
                   f"• Для обновления своего рейтинга используйте **«!update TankRating DPSRating SupportRating»**\n"
                   f"• Для того, чтобы узнать свой рейтинг в боте используйте **«!my_rank»**\n"
                   f"• Для проведения чек-ина используйте команду **«!check»**\n"
                   f"• Для просмотра статуса миксов (регистрации, чек-ин, роли, лобби) используйте **«!mix_status»**\n"
                   f"• Для просмотра очереди на след. игру используйте **«!queue»**\n"
                   f"• Для очистки очереди используйте **«!queue_clear»**\n"
                   f"• Для добавления игрока в очередь используйте **«!queue_add discord_id»**\n"
                   f"• Для удаления игрока из очереди используйте **«!queue_remove discord_id»**\n")


@bot.command()
@admin_only()
async def queue(ctx):
    try:
        queued_players = await run_db(check_queue)
    except Exception as e:
        logger.error(f'Error fetching queue: {e}')
        await ctx.send(system_error_text('получить очередь'))
        return
    await ctx.send(f'{queued_players}')


@bot.command(ignore_extra=False)
@admin_only()
async def queue_add(ctx, discord_id: str):
    discord_id = parse_discord_id(discord_id)

    def _add():
        user = session.query(Player).filter(Player.discord_id == discord_id).first()
        if user is None:
            return 'not_registered', None
        if session.query(Queue).filter(Queue.discord_id == discord_id).first() is not None:
            return 'already_queued', user.name
        session.add(Queue(discord_id=discord_id))
        session.commit()
        return user.check_in, user.name

    try:
        result, name = await run_db(_add)
    except Exception as e:
        logger.error(f'Error adding to queue: {e}')
        await ctx.send(system_error_text('добавить игрока в очередь'))
        return

    if result == 'not_registered':
        raise InputError(f'Игрок с discord_id {discord_id} не зарегистрирован.')
    if result == 'already_queued':
        raise InputError(f'{name} уже в очереди.', with_usage=False)
    message = f'{name} успешно добавлен в очередь'
    if result != 'yes':
        message += ' (внимание: игрок не прошёл чек-ин — пока он не отметится, очередь его не учтёт)'
    await ctx.send(message)


@bot.command(ignore_extra=False)
@admin_only()
async def queue_remove(ctx, discord_id: str):
    discord_id = parse_discord_id(discord_id)

    def _remove():
        user = session.query(Queue).filter(Queue.discord_id == discord_id).first()
        if user is None:
            return False
        session.delete(user)
        session.commit()
        return True

    try:
        found = await run_db(_remove)
    except Exception as e:
        logger.error(f'Error removing from queue: {e}')
        await ctx.send(system_error_text('убрать игрока из очереди'))
        return

    if not found:
        raise InputError(f'Игрока с discord_id {discord_id} нет в очереди.', with_usage=False)
    await ctx.send("Пользователь успешно убран из очереди")


@bot.command()
@admin_only()
async def queue_clear(ctx):
    def _clear():
        session.query(Queue).delete()
        session.commit()

    try:
        await run_db(_clear)
    except Exception as e:
        logger.error(f'Error clearing queue: {e}')
        await ctx.send(system_error_text('очистить очередь'))
        return
    await ctx.send("Очередь успешно очищена")


@bot.command()
@admin_only()
async def mix_status(ctx):
    try:
        status = await run_db(get_mix_status)
    except Exception as e:
        logger.error(f'Error fetching mix status: {e}')
        await ctx.send(system_error_text('получить статус миксов'))
        return

    roles = status['by_priority']
    can_play = status['can_play']
    lobbies_line = f'🎮 Игроков хватает на лобби: **{status["lobbies"]}**'
    if status['checked_in'] > 0:
        lobbies_line += f' (до следующего не хватает {status["to_next_lobby"]})'
    if status['short_roles']:
        role_labels = {'tank': '🛡️ танков', 'damage': '🏹 дпсов', 'support': '💉 саппортов'}
        lobbies_line += '\n⚠️ Не хватает игроков на роли: ' + ', '.join(role_labels[r] for r in status['short_roles'])
    await ctx.send(
        f'**📊 Статус миксов**\n'
        f'👥 Зарегистрировано: **{status["total"]}**\n'
        f'✅ Прошли чек-ин: **{status["checked_in"]}**\n'
        f'⭐ Приоритетные роли: 🛡️ {roles["tank"]} | 🏹 {roles["damage"]} | '
        f'💉 {roles["support"]} | 🎲 {roles["flex"]}\n'
        f'🎯 Могут играть: 🛡️ {can_play["tank"]} | 🏹 {can_play["damage"]} | 💉 {can_play["support"]}\n'
        f'⏳ В очереди на след. игру: **{status["queued"]}**\n'
        f'{lobbies_line}'
    )


@bot.command()
@admin_only()
async def players(ctx):
    try:
        result = await run_db(active_players)
    except Exception as e:
        logger.error(f'Error fetching active players: {e}')
        await ctx.send(system_error_text('получить список игроков'))
        return
    await ctx.send(f"{result}")


@bot.command()
@admin_only()
async def mix_stop(ctx):
    try:
        await run_db(end)
        await run_db(reset_history)
    except Exception as e:
        logger.error(f'Error stopping mix: {e}')
        await ctx.send(system_error_text('завершить миксы'))
        return
    await ctx.send("Все игроки переведены в неактивный статус, история анти-повтора очищена.")


@bot.command()
async def my_rank(ctx):
    discord_id = str(ctx.author.id)

    def _get():
        user = session.query(Player).filter(Player.discord_id == discord_id).first()
        if user is None:
            return None
        lines = [f'Имя пользователя: {user.name}']
        if user.tank_rating is not None:
            lines.append(f'Рейтинг на танке: {format_rating(user.tank_rating)}')
        if user.damage_rating is not None:
            lines.append(f'Рейтинг на дпсах: {format_rating(user.damage_rating)}')
        if user.support_rating is not None:
            lines.append(f'Рейтинг на саппортах: {format_rating(user.support_rating)}')
        return '\n'.join(lines)

    try:
        result = await run_db(_get)
    except Exception as e:
        logger.error(f'Error fetching rank for {ctx.author.name}: {e}')
        await ctx.send(system_error_text('получить данные о рейтинге'))
        return

    if result is None:
        await ctx.send(NOT_REGISTERED)
        return
    await ctx.send(result)


@bot.command(ignore_extra=False)
@admin_only()
async def user_update(ctx, user_id: str, tank_rating: str, damage_rating: str, support_rating: str):
    user_id = parse_discord_id(user_id)

    def _update():
        user = session.query(Player).filter(Player.discord_id == user_id).first()
        if user is None:
            return 'not_found'
        try:
            values = parse_ratings(tank_rating, damage_rating, support_rating,
                                   priority=user.priority_role, protect_priority=True)
        except InputError as e:
            return e
        user.tank_rating, user.damage_rating, user.support_rating = values
        session.commit()
        return user.name

    try:
        result = await run_db(_update)
    except Exception as e:
        logger.error(f'Error updating user rating: {e}')
        await ctx.send(system_error_text('обновить рейтинг пользователя'))
        return

    if result == 'not_found':
        raise InputError(f'Игрок с discord_id {user_id} не зарегистрирован.')
    if isinstance(result, InputError):
        raise result

    logger.info(f'Admin successfully updated rating of {result}.')
    await ctx.send(f'Администратор обновил рейтинг у {result}.')


@bot.command(ignore_extra=False)
async def update(ctx, tank_rating: str, damage_rating: str, support_rating: str):
    discord_id = str(ctx.author.id)
    username = ctx.author.name

    def _update():
        user = session.query(Player).filter(Player.discord_id == discord_id).first()
        if user is None:
            return 'not_registered'
        try:
            values = parse_ratings(tank_rating, damage_rating, support_rating,
                                   priority=user.priority_role, protect_priority=True)
        except InputError as e:
            return e
        user.tank_rating, user.damage_rating, user.support_rating = values
        session.commit()
        return True

    try:
        result = await run_db(_update)
    except Exception as e:
        logger.error(f'Error updating user rating: {e}')
        await ctx.send(system_error_text('обновить рейтинг'))
        return

    if result == 'not_registered':
        await ctx.send(NOT_REGISTERED)
        return
    if isinstance(result, InputError):
        raise result

    logger.info(f'User {username} successfully updated his rating.')
    await ctx.send('Вы успешно изменили свой рейтинг')


@bot.command(ignore_extra=False, aliases=['registration'])
async def register(ctx, battle_tag: str, tank_rating: str, damage_rating: str, support_rating: str):
    discord_id = str(ctx.author.id)

    if not BATTLE_TAG_PATTERN.match(battle_tag):
        raise InputError(f'Неверный формат BattleTag «{battle_tag}»: нужно имя и номер через #.')

    tank_value, damage_value, support_value = parse_ratings(tank_rating, damage_rating, support_rating)

    priority = None
    if tank_value is not None:
        priority = 'tank'
    elif damage_value is not None:
        priority = 'damage'
    elif support_value is not None:
        priority = 'support'

    username = battle_tag.split('#')[0]

    def _register():
        if session.query(Player).filter(Player.discord_id == discord_id).first() is not None:
            return 'already_registered'
        user_info = Player(
            name=username,
            tank_rating=tank_value,
            damage_rating=damage_value,
            support_rating=support_value,
            priority_role=priority,
            discord_id=discord_id,
            check_in='no',
        )
        session.add(user_info)
        session.commit()
        return True

    try:
        result = await run_db(_register)
    except Exception as e:
        logger.error(f'Error registering user: {e}')
        await ctx.send(system_error_text('зарегистрировать пользователя'))
        return

    if result == 'already_registered':
        await ctx.send(error_text('Вы уже зарегистрированы. Чтобы изменить рейтинг, используйте !update.',
                                  USAGE['update']))
        return

    logger.info(f'User {username} successfully registered.')
    await ctx.send('Вы успешно зарегистрировались на миксы')


@bot.command(ignore_extra=False)
@admin_only()
async def uncheck(ctx, discord_id: str):
    discord_id = parse_discord_id(discord_id)

    def _uncheck():
        user = session.query(Player).filter(Player.discord_id == discord_id).first()
        if user is None:
            return False
        user.check_in = 'no'
        session.commit()
        queued = session.query(Queue).filter(Queue.discord_id == discord_id).first()
        if queued:
            session.delete(queued)
            session.commit()
        return True

    try:
        found = await run_db(_uncheck)
    except Exception as e:
        logger.error(f'Error unchecking user: {e}')
        await ctx.send(system_error_text('снять чек-ин'))
        return

    if not found:
        raise InputError(f'Игрок с discord_id {discord_id} не зарегистрирован.')
    await ctx.send('Пользователь был успешно удален из очереди')


@bot.command(ignore_extra=False)
@admin_only()
async def create_lobby(ctx, lobby_count: int):
    if lobby_count < 1:
        raise InputError('Количество лобби должно быть не меньше 1.')

    try:
        lobbies, queued_players = await run_db(create_lobbies_caller, lobby_count)
    except ValueError as e:
        raise InputError(f'Не удалось создать лобби: {e}', with_usage=False)
    except Exception as e:
        logger.error(f'Error creating lobbies: {e}')
        await ctx.send(system_error_text('создать лобби'))
        return

    if not lobbies:
        await ctx.send(error_text('Не удалось собрать ни одного лобби — недостаточно игроков с нужными ролями. '
                                  'Посмотреть, каких ролей не хватает: !mix_status.'))
        return

    for i, lobby in enumerate(lobbies):
        team1 = lobby['team1']
        team2 = lobby['team2']
        await ctx.send(f'**🌞 Лобби {i + 1}**')
        await ctx.send("**💙 Синяя команда**")
        await ctx.send(f'🛡️ **{team1["tank"].name}** 🏹 **{team1["damage"][0].name} |'
                       f' {team1["damage"][1].name}**  💉 **{team1["support"][0].name} |'
                       f' {team1["support"][1].name}**')
        await ctx.send("**💖 Красная команда**")
        await ctx.send(
            f'🛡️ **{team2["tank"].name}** 🏹 **{team2["damage"][0].name} |'
            f' {team2["damage"][1].name}** 💉 **{team2["support"][0].name} |'
            f' {team2["support"][1].name}**')
        await ctx.send(f'**🎲 Карта: {get_map()}**')
        teams_abs, match_rating = get_rating(lobby)
        await ctx.send(f'*Средний рейтинг матча {round(match_rating)}, Разница между командами: {teams_abs}*')
        await ctx.send('------------------------------------------')

    if len(lobbies) < lobby_count:
        await ctx.send(f'⚠️ Удалось собрать только {len(lobbies)} из {lobby_count} лобби — '
                       f'не хватило игроков с нужными ролями для остальных.')

    if queued_players:
        message = ' '.join(player.name for player in queued_players)
        await ctx.send(f"**Ожидающие игроки**: {message}")


def main():
    bot.run(BOT_TOKEN)


if __name__ == "__main__":
    main()
