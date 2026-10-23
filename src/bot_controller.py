import re

import discord

from discord.ext import commands

from src.config import bot, BOT_TOKEN, ADMIN_IDS, run_db, logger
from src.balancer import reset_history
from src.sync_logic import (
    add_to_queue,
    active_players,
    check_queue,
    clear_queue,
    create_lobbies_caller,
    end,
    format_rating,
    get_map,
    get_player,
    get_rating,
    mix_status as get_mix_status,
    parse_battle_tag,
    parse_ratings,
    register_player,
    remove_from_queue,
    uncheck_player,
    update_player_ratings,
    update_user_status,
)

admins = ADMIN_IDS

DISCORD_ID_PATTERN = re.compile(r"^(?:<@!?(\d+)>|(\d+))$")

# пример вызова, который показывается в сообщениях об ошибках ввода
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

HELP_COLOR = discord.Color(0xF99E1A)  # оранжевый Overwatch

PRIORITY_LABELS = {'tank': '🛡️ Tank', 'damage': '🏹 DPS', 'support': '💉 Support', 'flex': '🎲 Flex', None: 'не выбрана'}


def priority_change_note(old_priority, new_priority) -> str:
    """Пояснение для ответа на !update / !user_update, если приоритетная роль сменилась после изменения рейтинга."""
    if old_priority is None:
        reason = 'раньше она не была выбрана'
    elif old_priority == 'flex':
        reason = 'для Flex нужен рейтинг на всех трёх ролях'
    else:
        reason = 'на прежней роли больше нет рейтинга'
    return (f'Приоритетная роль изменена: {PRIORITY_LABELS[old_priority]} → {PRIORITY_LABELS[new_priority]} '
            f'({reason}). Выбрать другую можно кнопками на чек-ине.')


class InputError(commands.CommandError):
    """Ошибка ввода пользователя. Бросается из команды и показывается в чате
    в едином формате через on_command_error (с примером команды, если with_usage)."""

    def __init__(self, problem: str, with_usage: bool = True):
        super().__init__(problem)
        self.problem = problem
        self.with_usage = with_usage


class NotAdmin(commands.CheckFailure):
    """Команду вызвал не администратор."""


def admin_only():
    """Проверка прав до разбора аргументов: не-админ всегда получает понятный отказ,
    а не молчание бота или ошибку про аргументы."""
    async def predicate(ctx):
        if ctx.author.id not in admins:
            raise NotAdmin()
        return True
    return commands.check(predicate)


def parse_discord_id(raw: str) -> str:
    """Числовой ID или упоминание (<@123>, <@!123>) -> ID строкой; иначе InputError."""
    match = DISCORD_ID_PATTERN.match(raw.strip())
    if match is None:
        raise InputError(f'Некорректный discord_id «{raw}»: нужен числовой ID или упоминание @игрока.')
    return match.group(1) or match.group(2)


class CheckinView(discord.ui.View):
    """Кнопки чек-ина: выбор приоритетной роли, check-in и check-out. Ответы видит только нажавший."""
    message: discord.Message = None

    async def on_timeout(self):
        """Отключает кнопки и помечает чек-ин закрытым, чтобы клик по устаревшей кнопке
        не заканчивался безликим «Interaction failed»."""
        logger.info('Check-in closed by timeout')
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
        """Отмечает игрока на миксы; требует выбранную приоритетную роль."""
        user_id = interaction.user.id
        user_name = interaction.user.name
        await interaction.response.defer()
        try:
            result = await run_db(update_user_status, user_id, 'checked_in', 'yes')
        except Exception:
            logger.exception(f'Error checking in {user_name}')
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
        """Снимает чек-ин игрока."""
        user_id = interaction.user.id
        user_name = interaction.user.name
        await interaction.response.defer()
        try:
            result = await run_db(update_user_status, user_id, 'checked_in', 'no')
        except Exception:
            logger.exception(f'Error checking out {user_name}')
            await interaction.followup.send(system_error_text('пройти чек-аут'), ephemeral=True)
            return
        if result == 'not_registered':
            await interaction.followup.send(NOT_REGISTERED, ephemeral=True)
            return
        logger.info(f'User {user_name} successfully checked out.')
        await interaction.followup.send(f"{user_name} успешно прошел чек-аут", ephemeral=True)

    async def _set_priority_role(self, interaction: discord.Interaction, role: str,
                                  role_label: str, requirement_msg: str):
        """Общий обработчик кнопок выбора приоритетной роли.
        requirement_msg — ответ, если на этой роли у игрока нет рейтинга."""
        user_id = interaction.user.id
        user_name = interaction.user.name
        await interaction.response.defer()
        try:
            result = await run_db(update_user_status, user_id, 'priority_role', role)
        except Exception:
            logger.exception(f'Error setting priority role for {user_name}')
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


def _who(ctx):
    """Автор команды для логов: имя и Discord ID."""
    return f'{ctx.author.name} ({ctx.author.id})'


def _usage(ctx):
    """Пример вызова команды для сообщения об ошибке — под тем именем, которое набрал
    пользователь (для !registration покажет !registration, а не !register)."""
    if ctx.command is None or ctx.command.name not in USAGE:
        return None
    return USAGE[ctx.command.name].replace(f'!{ctx.command.name}', f'!{ctx.invoked_with}', 1)


@bot.event
async def on_command_error(ctx, error):
    """Общий предохранитель: ни одна ошибка в команде не должна проходить незамеченной
    и не должна ронять бота — пользователь всегда получает ответ в едином формате,
    а непредвиденные ошибки дополнительно логируются."""
    if isinstance(error, commands.CommandNotFound):
        message = error_text(f'Неизвестная команда «!{ctx.invoked_with}». Список команд: !mix_help.')
    elif isinstance(error, NotAdmin):
        logger.warning(f'Non-admin {_who(ctx)} tried !{ctx.invoked_with}')
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
        message = error_text('Не удалось разобрать команду — проверьте кавычки и пробелы.', _usage(ctx))
    elif isinstance(error, commands.CommandOnCooldown):
        message = error_text('Команда на перезарядке, попробуйте чуть позже.')
    elif isinstance(error, commands.CheckFailure):
        logger.warning(f'Check failed for !{ctx.invoked_with} by {_who(ctx)}: {error}')
        message = error_text('Эту команду сейчас нельзя выполнить.')
    else:
        original = getattr(error, 'original', error)
        logger.error(f'Unhandled error in command "{ctx.command}": {original}', exc_info=original)
        message = system_error_text('выполнить команду')

    if isinstance(error, (InputError, commands.UserInputError)):
        logger.info(f'Input error in !{ctx.invoked_with} by {_who(ctx)}: {error}')

    try:
        await ctx.send(message)
    except Exception:
        logger.exception('Could not report command error to chat')


@bot.command()
@admin_only()
async def check(ctx):
    """Открыть чек-ин на миксы (админ)."""
    view = CheckinView(timeout=20000)
    await ctx.send(
        'Чекин на миксы начался! Обратите внимание, что пройти check-in могут только зарегистрированные игроки.')
    view.message = await ctx.send(
        'Нажмите ✅ и выберите приоритетную роль. Пожалуйста, нажмите ❌, если покидаете миксы.', view=view)
    logger.info(f'Check-in opened by {_who(ctx)}')


@bot.command()
async def mix_help(ctx):
    """Список команд бота."""
    embed = discord.Embed(
        title='📖 Команды бота миксов',
        description=('Рейтинг роли — число от 500 до 5000 или дивизион Overwatch: `b5` … `chm1` '
                     '(например, `g4`, `d2`, `gm3`). `0` — роль не играете.'),
        color=HELP_COLOR,
    )
    embed.add_field(name='👤 Для игроков', inline=False, value=(
        '`!register BattleTag Танк DPS Саппорт` — регистрация (или `!registration`)\n'
        '`!update Танк DPS Саппорт` — обновить свой рейтинг\n'
        '`!my_rank` — показать свой рейтинг\n'
        '`!mix_help` — этот список\n'
        'Пример: `!register Sacr1ficed#2456 4000 d2 0`'
    ))
    embed.add_field(name='✅ Чек-ин', inline=False, value=(
        'Когда админ откроет чек-ин, выберите приоритетную роль кнопкой '
        '🛡️ Tank / 🏹 DPS / 💉 Support / 🎲 Flex и нажмите ✅ Check-in. '
        'Уходите с миксов — нажмите ❌ Check-out.'
    ))
    embed.add_field(name='🛠️ Админам: вечер миксов', inline=False, value=(
        '`!check` — открыть чек-ин\n'
        '`!mix_status` — сколько игроков, роли, на сколько лобби хватает\n'
        '`!players` — список отметившихся\n'
        '`!create_lobby N` — собрать N лобби\n'
        '`!mix_stop` — завершить вечер и снять чек-ин со всех'
    ))
    embed.add_field(name='🛠️ Админам: очередь и игроки', inline=False, value=(
        '`!queue` — очередь на следующую игру\n'
        '`!queue_add @игрок` / `!queue_remove @игрок` — добавить / убрать из очереди\n'
        '`!queue_clear` — очистить очередь\n'
        '`!uncheck @игрок` — снять чек-ин и убрать из очереди\n'
        '`!user_update @игрок Танк DPS Саппорт` — изменить рейтинг игрока'
    ))
    embed.set_footer(text='Вместо @игрок можно указать Discord ID числом.')
    await ctx.send(embed=embed)


@bot.command()
@admin_only()
async def queue(ctx):
    """Показать очередь на следующую игру (админ)."""
    try:
        queued_players = await run_db(check_queue)
    except Exception:
        logger.exception('Error fetching queue')
        await ctx.send(system_error_text('получить очередь'))
        return
    await ctx.send(f'{queued_players}')


@bot.command(ignore_extra=False)
@admin_only()
async def queue_add(ctx, discord_id: str):
    """Добавить игрока в очередь (админ)."""
    discord_id = parse_discord_id(discord_id)

    try:
        status, player = await run_db(add_to_queue, discord_id)
    except Exception:
        logger.exception('Error adding to queue')
        await ctx.send(system_error_text('добавить игрока в очередь'))
        return

    if status == 'not_registered':
        raise InputError(f'Игрок с discord_id {discord_id} не зарегистрирован.')
    if status == 'already_queued':
        raise InputError(f'{player.name} уже в очереди.', with_usage=False)
    logger.info(f'{_who(ctx)} added {player.name} ({discord_id}) to the queue')
    message = f'{player.name} успешно добавлен в очередь'
    if player.check_in != 'yes':
        message += ' (внимание: игрок не прошёл чек-ин — пока он не отметится, очередь его не учтёт)'
    await ctx.send(message)


@bot.command(ignore_extra=False)
@admin_only()
async def queue_remove(ctx, discord_id: str):
    """Убрать игрока из очереди (админ)."""
    discord_id = parse_discord_id(discord_id)

    try:
        found = await run_db(remove_from_queue, discord_id)
    except Exception:
        logger.exception('Error removing from queue')
        await ctx.send(system_error_text('убрать игрока из очереди'))
        return

    if not found:
        raise InputError(f'Игрока с discord_id {discord_id} нет в очереди.', with_usage=False)
    logger.info(f'{_who(ctx)} removed {discord_id} from the queue')
    await ctx.send("Пользователь успешно убран из очереди")


@bot.command()
@admin_only()
async def queue_clear(ctx):
    """Очистить очередь (админ)."""
    try:
        await run_db(clear_queue)
    except Exception:
        logger.exception('Error clearing queue')
        await ctx.send(system_error_text('очистить очередь'))
        return
    logger.info(f'Queue cleared by {_who(ctx)}')
    await ctx.send("Очередь успешно очищена")


@bot.command()
@admin_only()
async def mix_status(ctx):
    """Статус миксов: регистрации, чек-ин, роли, очередь, сколько лобби можно собрать (админ)."""
    try:
        status = await run_db(get_mix_status)
    except Exception:
        logger.exception('Error fetching mix status')
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
    """Список отметившихся игроков (админ)."""
    try:
        result = await run_db(active_players)
    except Exception:
        logger.exception('Error fetching active players')
        await ctx.send(system_error_text('получить список игроков'))
        return
    await ctx.send(f"{result}")


@bot.command()
@admin_only()
async def mix_stop(ctx):
    """Завершить вечер: снять чек-ин со всех и очистить историю анти-повтора (админ)."""
    try:
        await run_db(end)
        await run_db(reset_history)
    except Exception:
        logger.exception('Error stopping mix')
        await ctx.send(system_error_text('завершить миксы'))
        return
    logger.info(f'Mix stopped by {_who(ctx)}: all players checked out, anti-repeat history reset')
    await ctx.send("Все игроки переведены в неактивный статус, история анти-повтора очищена.")


@bot.command()
async def my_rank(ctx):
    """Показать свой рейтинг по ролям."""
    try:
        user = await run_db(get_player, ctx.author.id)
    except Exception:
        logger.exception(f'Error fetching rank for {ctx.author.name}')
        await ctx.send(system_error_text('получить данные о рейтинге'))
        return

    if user is None:
        await ctx.send(NOT_REGISTERED)
        return
    lines = [f'Имя пользователя: {user.name}']
    if user.tank_rating is not None:
        lines.append(f'Рейтинг на танке: {format_rating(user.tank_rating)}')
    if user.damage_rating is not None:
        lines.append(f'Рейтинг на дпсах: {format_rating(user.damage_rating)}')
    if user.support_rating is not None:
        lines.append(f'Рейтинг на саппортах: {format_rating(user.support_rating)}')
    await ctx.send('\n'.join(lines))


@bot.command(ignore_extra=False)
@admin_only()
async def user_update(ctx, user_id: str, tank_rating: str, damage_rating: str, support_rating: str):
    """Изменить рейтинг любого игрока (админ)."""
    user_id = parse_discord_id(user_id)

    try:
        result = await run_db(update_player_ratings, user_id, tank_rating, damage_rating, support_rating)
    except ValueError as e:
        raise InputError(str(e))
    except Exception:
        logger.exception('Error updating user rating')
        await ctx.send(system_error_text('обновить рейтинг пользователя'))
        return

    if result is None:
        raise InputError(f'Игрок с discord_id {user_id} не зарегистрирован.')

    name, old_priority, new_priority = result
    logger.info(f'{_who(ctx)} updated rating of {name} ({user_id}): '
                f'tank={tank_rating}, damage={damage_rating}, support={support_rating}, '
                f'priority {old_priority} -> {new_priority}')
    message = f'Администратор обновил рейтинг у {name}.'
    if new_priority != old_priority:
        message += '\n' + priority_change_note(old_priority, new_priority)
    await ctx.send(message)


@bot.command(ignore_extra=False)
async def update(ctx, tank_rating: str, damage_rating: str, support_rating: str):
    """Обновить свой рейтинг по ролям."""
    try:
        result = await run_db(update_player_ratings, ctx.author.id, tank_rating, damage_rating, support_rating)
    except ValueError as e:
        raise InputError(str(e))
    except Exception:
        logger.exception('Error updating user rating')
        await ctx.send(system_error_text('обновить рейтинг'))
        return

    if result is None:
        await ctx.send(NOT_REGISTERED)
        return

    name, old_priority, new_priority = result
    logger.info(f'User {name} ({ctx.author.id}) updated their rating: '
                f'tank={tank_rating}, damage={damage_rating}, support={support_rating}, '
                f'priority {old_priority} -> {new_priority}')
    message = 'Вы успешно изменили свой рейтинг'
    if new_priority != old_priority:
        message += '\n' + priority_change_note(old_priority, new_priority)
    await ctx.send(message)


@bot.command(ignore_extra=False, aliases=['registration'])
async def register(ctx, battle_tag: str, tank_rating: str, damage_rating: str, support_rating: str):
    """Зарегистрироваться на миксы (то же — !registration)."""
    try:
        username = parse_battle_tag(battle_tag)
        ratings = parse_ratings(tank_rating, damage_rating, support_rating)
    except ValueError as e:
        raise InputError(str(e))

    try:
        registered = await run_db(register_player, ctx.author.id, username, *ratings)
    except Exception:
        logger.exception('Error registering user')
        await ctx.send(system_error_text('зарегистрировать пользователя'))
        return

    if not registered:
        await ctx.send(error_text('Вы уже зарегистрированы. Чтобы изменить рейтинг, используйте !update.',
                                  USAGE['update']))
        return

    logger.info(f'User {username} ({ctx.author.id}) registered')
    await ctx.send('Вы успешно зарегистрировались на миксы')


@bot.command(ignore_extra=False)
@admin_only()
async def uncheck(ctx, discord_id: str):
    """Снять чек-ин с игрока и убрать его из очереди (админ)."""
    discord_id = parse_discord_id(discord_id)

    try:
        found = await run_db(uncheck_player, discord_id)
    except Exception:
        logger.exception('Error unchecking user')
        await ctx.send(system_error_text('снять чек-ин'))
        return

    if not found:
        raise InputError(f'Игрок с discord_id {discord_id} не зарегистрирован.')
    logger.info(f'{_who(ctx)} unchecked {discord_id}')
    await ctx.send('Пользователь был успешно удален из очереди')


@bot.command(ignore_extra=False)
@admin_only()
async def create_lobby(ctx, lobby_count: int):
    """Собрать N сбалансированных лобби из отметившихся игроков (админ)."""
    if lobby_count < 1:
        raise InputError('Количество лобби должно быть не меньше 1.')

    try:
        lobbies, queued_players = await run_db(create_lobbies_caller, lobby_count)
    except ValueError as e:
        raise InputError(f'Не удалось создать лобби: {e}', with_usage=False)
    except Exception:
        logger.exception('Error creating lobbies')
        await ctx.send(system_error_text('создать лобби'))
        return

    logger.info(f'{_who(ctx)} requested {lobby_count} lobbies: formed {len(lobbies)}, '
                f'{len(queued_players)} players left waiting')
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
        logger.info(f'Lobby {i + 1}: avg rating {round(match_rating)}, team diff {teams_abs}')
        await ctx.send(f'*Средний рейтинг матча {round(match_rating)}, Разница между командами: {teams_abs}*')
        await ctx.send('------------------------------------------')

    if len(lobbies) < lobby_count:
        await ctx.send(f'⚠️ Удалось собрать только {len(lobbies)} из {lobby_count} лобби — '
                       f'не хватило игроков с нужными ролями для остальных.')

    if queued_players:
        message = ' '.join(player.name for player in queued_players)
        await ctx.send(f"**Ожидающие игроки**: {message}")


def main():
    bot.run(BOT_TOKEN, log_handler=None)


if __name__ == "__main__":
    main()
