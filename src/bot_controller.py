import re

import discord

from discord.ext import commands

from src.config import bot, BOT_TOKEN, ADMIN_IDS, session, run_db, logger
from src.models import Player, Queue, MIN_RATING, MAX_RATING
from src.sync_logic import (
    convert_rank_to_value,
    rank_to_value,
    create_lobbies_caller,
    get_map,
    get_rating,
    check_queue,
    active_players,
    end,
)

admins = ADMIN_IDS

# Пример battle_tag: Sacr1ficed#2456
BATTLE_TAG_PATTERN = re.compile(r"^[\w]+#\d+$")


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
    async def on_error(self, interaction: discord.Interaction, error: Exception, item):
        """Предохранитель на уровне кнопок: ошибка в одном клике не должна ронять бота
        и не должна оставлять пользователя без ответа."""
        logger.error(f'Error in CheckinView item {item}: {error}', exc_info=error)
        try:
            message = 'Произошла непредвиденная ошибка, попробуйте ещё раз.'
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
            await interaction.followup.send("Произошла ошибка при чек-ине.", ephemeral=True)
            return
        if result == 'not_registered':
            await interaction.followup.send("Вы не зарегистрированы. Используйте !register.", ephemeral=True)
            return
        if result == 'no_role':
            await interaction.followup.send(
                "Сначала выберите приоритетную роль (🛡️ Tank / 🏹 DPS / 💉 Support / 🎲 Flex), "
                "затем нажмите ✅ Check-in.", ephemeral=True)
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
            await interaction.followup.send("Произошла ошибка при чек-ауте.", ephemeral=True)
            return
        if result == 'not_registered':
            await interaction.followup.send("Вы не зарегистрированы. Используйте !register.", ephemeral=True)
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
            await interaction.followup.send("Произошла ошибка.", ephemeral=True)
            return
        if result == 'not_registered':
            await interaction.followup.send("Вы не зарегистрированы. Используйте !register.", ephemeral=True)
        elif result:
            logger.info(f'User {user_name} set priority role as {role}.')
            await interaction.followup.send(f"{user_name} успешно выбрал {role_label} приоритетной ролью", ephemeral=True)
        else:
            await interaction.followup.send(requirement_msg, ephemeral=True)

    @discord.ui.button(label='🛡️ Tank', style=discord.ButtonStyle.gray)
    async def tank(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._set_priority_role(
            interaction, 'tank', 'танка',
            'Чтобы выбрать роль приоритетной, необходимо указать ее рейтинг.'
        )

    @discord.ui.button(label='🏹 DPS', style=discord.ButtonStyle.gray)
    async def dps(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._set_priority_role(
            interaction, 'damage', 'урон',
            'Чтобы выбрать роль приоритетной, необходимо указать ее рейтинг.'
        )

    @discord.ui.button(label='💉 Support', style=discord.ButtonStyle.gray)
    async def support(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._set_priority_role(
            interaction, 'support', 'поддержку',
            'Чтобы выбрать роль приоритетной, необходимо указать ее рейтинг.'
        )

    @discord.ui.button(label='🎲 Flex', style=discord.ButtonStyle.gray)
    async def flex(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._set_priority_role(
            interaction, 'flex', 'flex',
            'Чтобы выбрать флекс, необходимо указать рейтинг на всех ролях.'
        )


@bot.event
async def on_ready():
    logger.info(f'Logged in as {bot.user.name}')
    logger.info('OW2 Mix Bot v1.0')
    logger.info('Developed by nmkyt')
    logger.info('Command list available at !mix_help in Discord app')


@bot.event
async def on_command_error(ctx, error):
    """Общий предохранитель: ни одна ошибка в команде не должна проходить незамеченной
    и не должна ронять бота — только логироваться и сообщаться пользователю."""
    if isinstance(error, commands.CommandNotFound):
        return
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f'Не хватает аргумента «{error.param.name}». Смотрите !mix_help для примера.')
        return
    if isinstance(error, (commands.BadArgument, commands.BadUnionArgument)):
        await ctx.send('Некорректный аргумент команды. Смотрите !mix_help для примера.')
        return
    if isinstance(error, commands.CommandOnCooldown):
        await ctx.send('Команда на перезарядке, попробуйте чуть позже.')
        return

    original = getattr(error, 'original', error)
    logger.error(f'Unhandled error in command "{ctx.command}": {original}', exc_info=original)
    try:
        await ctx.send('Произошла непредвиденная ошибка при выполнении команды. Бот продолжает работать, попробуйте ещё раз.')
    except Exception:
        pass


@bot.command()
async def check(ctx):
    if ctx.author.id in admins:
        view = CheckinView(timeout=20000)
        await ctx.send(
            'Чекин на миксы начался! Обратите внимание, что пройти check-in могут только зарегистрированные игроки.')
        await ctx.send('Нажмите ✅ и выберите приоритетную роль. Пожалуйста, нажмите ❌, если покидаете миксы.', view=view)


@bot.command()
async def mix_help(ctx):
    await ctx.send(f"--------------------------------**Список команд**--------------------------------\n"
                   f"• Для регистрации в боте используйте **«!register BattleTag TankRating DPSRating "
                   f"SupportRating»**\n"
                   f"где Tank, DPS и Support Rating - цифра или дивизион вашего рейтинга в OW2. пр.: m2, 2700, g4 итп.\n"
                   f"• Для обновления своего рейтинга используйте **«!update TankRating DPSRating SupportRating»**\n"
                   f"• Для того, чтобы узнать свой рейтинг в боте используйте **«!my_rank»**\n"
                   f"• Для проведения чек-ина используйте команду **«!check»**\n"
                   f"• Для просмотра очереди на след. игру используйте **«!queue»**\n"
                   f"• Для очистки очереди используйте **«!queue_clear»**\n"
                   f"• Для добавления игрока в очередь используйте **«!queue_add discord_id»**\n"
                   f"• Для удаления игрока из очереди используйте **«!queue_remove discord_id»**\n")


@bot.command()
async def queue(ctx):
    if ctx.author.id in admins:
        try:
            queued_players = await run_db(check_queue)
        except Exception as e:
            logger.error(f'Error fetching queue: {e}')
            await ctx.send("Не удалось получить очередь.")
            return
        await ctx.send(f'{queued_players}')


@bot.command()
async def queue_add(ctx, discord_id: str):
    if ctx.author.id in admins:
        def _add():
            user = Queue(discord_id=discord_id)
            session.add(user)
            session.commit()

        try:
            await run_db(_add)
            await ctx.send("Пользователь успешно добавлен в очередь")
        except Exception as e:
            logger.error(f'Error adding to queue: {e}')
            await ctx.send("Не удалось добавить пользователя в очередь")


@bot.command()
async def queue_remove(ctx, discord_id: str):
    if ctx.author.id in admins:
        def _remove():
            user = session.query(Queue).filter(Queue.discord_id == discord_id).first()
            if user is None:
                raise ValueError("Пользователь не найден в очереди")
            session.delete(user)
            session.commit()

        try:
            await run_db(_remove)
            await ctx.send("Пользователь успешно убран из очереди")
        except ValueError as e:
            await ctx.send(str(e))
        except Exception as e:
            logger.error(f'Error removing from queue: {e}')
            await ctx.send("Не удалось убрать пользователя из очереди")


@bot.command()
async def queue_clear(ctx):
    if ctx.author.id in admins:
        def _clear():
            session.query(Queue).delete()
            session.commit()

        try:
            await run_db(_clear)
            await ctx.send("Очередь успешно очищена")
        except Exception as e:
            logger.error(f'Error clearing queue: {e}')
            await ctx.send("Не удалось очистить очередь")


@bot.command()
async def players(ctx):
    if ctx.author.id in admins:
        try:
            result = await run_db(active_players)
        except Exception as e:
            logger.error(f'Error fetching active players: {e}')
            await ctx.send("Не удалось получить список игроков.")
            return
        await ctx.send(f"{result}")


@bot.command()
async def mix_stop(ctx):
    if ctx.author.id in admins:
        try:
            await run_db(end)
        except Exception as e:
            logger.error(f'Error stopping mix: {e}')
            await ctx.send("Не удалось завершить миксы.")
            return
        await ctx.send("Все игроки переведены в неактивный статус.")
    else:
        await ctx.send("У вас недостаточно прав для выполнения этой команды.")


@bot.command()
async def my_rank(ctx):
    discord_id = str(ctx.author.id)

    def _get():
        user = session.query(Player).filter(Player.discord_id == discord_id).first()
        if user is None:
            return None
        lines = [f'Имя пользователя: {user.name}']
        if user.tank_rating is not None:
            lines.append(f'Рейтинг на танке: {user.tank_rating}')
        if user.damage_rating is not None:
            lines.append(f'Рейтинг на дпсах: {user.damage_rating}')
        if user.support_rating is not None:
            lines.append(f'Рейтинг на саппортах: {user.support_rating}')
        return '\n'.join(lines)

    try:
        result = await run_db(_get)
    except Exception as e:
        logger.error(f'Error fetching rank for {ctx.author.name}: {e}')
        await ctx.send("Не удалось получить данные о рейтинге.")
        return

    if result is None:
        await ctx.send('Вы не зарегистрированы в системе. Используйте !register для регистрации.')
        return
    await ctx.send(result)


@bot.command()
async def user_update(ctx, user_id: str, tank_rating: str, damage_rating: str, support_rating: str):
    if ctx.author.id not in admins:
        return

    def parse(rating: str):
        rating = rating.split(',')[0]
        if rating == '0':
            return None
        if rating.lower() in rank_to_value:
            return convert_rank_to_value(rating.lower())
        try:
            value = int(rating)
        except ValueError:
            raise ValueError('Неверный формат рейтинга')
        if not (MIN_RATING <= value <= MAX_RATING):
            raise ValueError(f'Рейтинг должен быть в диапазоне от {MIN_RATING} до {MAX_RATING} (или 0, чтобы снять роль)')
        return value

    try:
        tank_value = parse(tank_rating)
        damage_value = parse(damage_rating)
        support_value = parse(support_rating)
    except ValueError as e:
        await ctx.send(f'Введите корректную команду. Пример: !user_update <id> 4000 d2 3700 | {e}')
        return

    def _update():
        user = session.query(Player).filter(Player.discord_id == user_id).first()
        if user is None:
            return None
        user.tank_rating = tank_value
        user.damage_rating = damage_value
        user.support_rating = support_value
        session.commit()
        return user.name

    try:
        username = await run_db(_update)
    except Exception as e:
        logger.error(f'Error updating user status: {e}')
        await ctx.send('Не удалось обновить рейтинг пользователя.')
        return

    if username is None:
        await ctx.send('Пользователь не найден.')
        return

    logger.info(f'nmkyt successfully updated rating of {username}.')
    await ctx.send(f'nmkyt обновил рейтинг у {username}.')


@bot.command()
async def update(ctx, tank_rating: str, damage_rating: str, support_rating: str):
    discord_id = str(ctx.author.id)
    username = ctx.author.name

    def _update():
        user = session.query(Player).filter(Player.discord_id == discord_id).first()
        if user is None:
            return 'not_registered'

        priority = user.priority_role

        def parse(rating: str, role: str):
            rating = rating.split(',')[0]
            if rating == '0':
                if priority in (role, 'flex'):
                    raise ValueError('Вы не можете обнулить рейтинг на роли, которая выбрана приоритетной')
                return None
            if rating.lower() in rank_to_value:
                return convert_rank_to_value(rating.lower())
            try:
                value = int(rating)
            except ValueError:
                raise ValueError('Введите корректную команду. Пример: !update 4000 d2 3700')
            if not (MIN_RATING <= value <= MAX_RATING):
                raise ValueError(f'Введите корректное значение рейтинга ({MIN_RATING}-{MAX_RATING}, или 0 чтобы снять роль)')
            return value

        try:
            tank_value = parse(tank_rating, 'tank')
            damage_value = parse(damage_rating, 'damage')
            support_value = parse(support_rating, 'support')
        except ValueError as e:
            return str(e)

        user.tank_rating = tank_value
        user.damage_rating = damage_value
        user.support_rating = support_value
        session.commit()
        return True

    try:
        result = await run_db(_update)
    except Exception as e:
        logger.error(f'Error updating user status: {e}')
        await ctx.send('Введите корректную команду')
        return

    if result == 'not_registered':
        await ctx.send('Вы не зарегистрированы в системе. Используйте !register для регистрации.')
    elif result is True:
        logger.info(f'User {username} successfully updated his rating.')
        await ctx.send('Вы успешно изменили свой рейтинг')
    else:
        await ctx.send(result)


@bot.command()
async def register(ctx, battle_tag: str, tank_rating: str, damage_rating: str, support_rating: str):
    discord_id = str(ctx.author.id)

    if not (battle_tag and tank_rating and damage_rating and support_rating):
        await ctx.send('Введите корректную команду. Пример: !register Sacr1ficed#2456 4000 d2 3700')
        return

    if not BATTLE_TAG_PATTERN.match(battle_tag):
        await ctx.send('Неверный формат battle_tag. Пример: Sacr1ficed#2456')
        return

    def process_rating(rating: str):
        rating = rating.split(',')[0]
        if rating == '0':
            return None
        if rating.lower() in rank_to_value:
            return convert_rank_to_value(rating.lower())
        try:
            value = int(rating)
        except ValueError:
            raise ValueError('Неверный формат рейтинга')
        if not (MIN_RATING <= value <= MAX_RATING):
            raise ValueError(f'Рейтинг должен быть в диапазоне от {MIN_RATING} до {MAX_RATING} (или 0, если роль не играется)')
        return value

    try:
        tank_value = process_rating(tank_rating)
        damage_value = process_rating(damage_rating)
        support_value = process_rating(support_rating)
    except ValueError as e:
        await ctx.send(f'Введите корректную команду. Пример: !register Sacr1ficed#2456 4000 d2 3700 | {e}')
        return

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
        await ctx.send('Ошибка регистрации пользователя')
        return

    if result == 'already_registered':
        await ctx.send('Вы уже зарегистрированы, для изменения пользователя используйте команду !update')
        return

    logger.info(f'User {username} successfully registered.')
    await ctx.send('Вы успешно зарегистрировались на миксы')


@bot.command()
async def uncheck(ctx, discord_id: str):
    if ctx.author.id in admins:
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
            await ctx.send('Не удалось выполнить операцию.')
            return

        if found:
            await ctx.send('Пользователь был успешно удален из очереди')
        else:
            await ctx.send('Пользователь не найден')


@bot.command()
async def create_lobby(ctx, lobby_count: int):
    if ctx.author.id in admins:
        try:
            lobbies, queued_players = await run_db(create_lobbies_caller, lobby_count)
        except ValueError as e:
            await ctx.send(f'Не удалось создать лобби: {e}')
            return
        except Exception as e:
            logger.error(f'Error creating lobbies: {e}')
            await ctx.send('Не удалось создать лобби.')
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

        if queued_players:
            message = ' '.join(player.name for player in queued_players)
            await ctx.send(f"**Ожидающие игроки**: {message}")


def main():
    bot.run(BOT_TOKEN)


if __name__ == "__main__":
    main()
