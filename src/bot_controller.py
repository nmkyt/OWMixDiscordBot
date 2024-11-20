import discord
from src.config import bot, BOT_TOKEN, session
from src.models import Player, Queue
import re
from src.sync_logic import convert_rank_to_value, rank_to_value, create_lobbies_caller, get_map, get_rating


class CheckinView(discord.ui.View):
    foo: bool = None
    role: str = ''

    @discord.ui.button(label='✅Check-in', style=discord.ButtonStyle.success)
    async def check_in(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.foo = True
        user_id = interaction.user.id
        user_name = interaction.user.name
        await interaction.response.defer()
        await update_user_status(user_id, 'checked_in', 'yes', interaction)
        print(f'User {user_name} successfully checked in.')
        await interaction.followup.send(f"{user_name} успешно прошел чек-ин.", ephemeral=True)

    @discord.ui.button(label='❌Check-out', style=discord.ButtonStyle.danger)
    async def check_out(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.foo = False
        user_id = interaction.user.id
        user_name = interaction.user.name
        await interaction.response.defer()
        await update_user_status(user_id, 'checked_in', 'no', interaction)
        print(f'User {user_name} successfully checked out.')
        await interaction.followup.send(f"{user_name} успешно прошел чек-аут", ephemeral=True)

    @discord.ui.button(label='🛡️ Tank', style=discord.ButtonStyle.gray)
    async def tank(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.role = 'tank'
        user_id = interaction.user.id
        user_name = interaction.user.name
        await interaction.response.defer()
        if await update_user_status(user_id, 'priority_role', 'tank', interaction):
            print(f'User {user_name} set priority role as Tank.')
            await interaction.followup.send(f"{user_name} успешно выбрал танка приоритетной ролью", ephemeral=True)
        else:
            await interaction.followup.send('Чтобы выбрать роль приоритетной, необходимо указать ее рейтинг.')
            raise Exception("Error updating user status.")

    @discord.ui.button(label='🏹 DPS', style=discord.ButtonStyle.gray)
    async def dps(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.role = 'damage'
        user_id = interaction.user.id
        user_name = interaction.user.name
        await interaction.response.defer()
        if await update_user_status(user_id, 'priority_role', 'damage', interaction):
            print(f'User {user_name} successfully set priority role as DPS.')
            await interaction.followup.send(f"{user_name} успешно выбрал урон приоритетной ролью", ephemeral=True)
        else:
            await interaction.followup.send('Чтобы выбрать роль приоритетной, необходимо указать ее рейтинг.')
            raise Exception("Error updating user status.")

    @discord.ui.button(label='💉 Support', style=discord.ButtonStyle.gray)
    async def support(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.role = 'support'
        user_id = interaction.user.id
        user_name = interaction.user.name
        await interaction.response.defer()
        if await update_user_status(user_id, 'priority_role', 'support', interaction):
            print(f'User {user_name} successfully set priority role as Support.')
            await interaction.followup.send(f"{user_name} успешно выбрал поддержку приоритетной ролью", ephemeral=True)
        else:
            await interaction.followup.send('Чтобы выбрать роль приоритетной, необходимо указать ее рейтинг.')
            raise Exception("Error updating user status.")

    @discord.ui.button(label='🎲 Flex', style=discord.ButtonStyle.gray)
    async def flex(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.role = 'flex'
        user_id = interaction.user.id
        user_name = interaction.user.name
        await interaction.response.defer()
        if await update_user_status(user_id, 'priority_role', 'flex', interaction):
            print(f'User {user_name} successfully set priority role as Flex.')
            await interaction.followup.send(f"{user_name} успешно выбрал flex приоритетной ролью", ephemeral=True)
        else:
            await interaction.followup.send('Чтобы выбрать роль приоритетной, необходимо указать ее рейтинг.')
            raise Exception("Error updating user status.")


@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name}')


@bot.command()
async def check(ctx):
    view = CheckinView(timeout=20000)
    await ctx.send(
        'Чекин на миксы начался! Обратите внимание, что пройти check-in могут только зарегистрированные игроки.')
    await ctx.send('Нажмите ✅ и выберите приоритетную роль. Пожалуйста, нажмите ❌, если покидаете миксы.', view=view)


async def update_user_status(user_id, field, value, interaction):
    try:
        user = session.query(Player).filter(Player.discord_id == str(user_id)).first()
        if field == 'checked_in':
            user.check_in = value
        if field == 'priority_role':
            if value == 'tank':
                if user.tank_rating is not None:
                    user.priority_role = value
                    session.commit()
                    return True
                else:
                    return False
            if value == 'damage':
                if user.damage_rating is not None:
                    user.priority_role = value
                    session.commit()
                    return True
                else:
                    return False
            if value == 'support':
                if user.support_rating is not None:
                    user.priority_role = value
                    session.commit()
                    return True
                else:
                    return False
            if value == 'flex':
                if (user.tank_rating and user.damage_rating and user.support_rating) is not None:
                    user.priority_role = value
                    session.commit()
                    return True
                else:
                    return False
        session.commit()
    except Exception as e:
        print(f'Error updating user status: {str(e)}')


@bot.command()
async def my_rank(ctx):
    discord_id = ctx.author.id
    user_rating = ''
    try:
        user = session.query(Player).filter(Player.discord_id == str(discord_id)).first()
        user_rating = user_rating + f'Имя пользователя: {user.name}\n'
        if user.tank_rating is not None:
            user_rating = user_rating + f'Рейтинг на танке: {user.tank_rating}\n'
        if user.damage_rating is not None:
            user_rating = user_rating + f'Рейтинг на дпсах: {user.damage_rating}\n'
        if user.support_rating is not None:
            user_rating = user_rating + f'Рейтинг на саппотрах: {user.support_rating}'
        await ctx.send(user_rating)
    except Exception as e:
        print(f'Error updating user status: {str(e)}')


@bot.command()
async def user_update(ctx, user_id: str, tank_rating, damage_rating, support_rating):
    if ctx.author.id == 279987350786801665:
        user = session.query(Player).filter(Player.discord_id == user_id).first()
        username = user.name
        if user is not None:
            if tank_rating and damage_rating and support_rating:
                tank_rating = tank_rating.split(',')[0]
                if tank_rating != '0':
                    if tank_rating in rank_to_value:
                        try:
                            user.tank_rating = convert_rank_to_value(tank_rating)
                        except ValueError as e:
                            await ctx.send(f'Введите корректную команду. Пример: !update 4000, d2, 3700 | {e}')
                    else:
                        try:
                            user.tank_rating = int(tank_rating)
                        except ValueError as e:
                            await ctx.send(f'Введите корректную команду. Пример: !update 4000, d2, 3700 | {e}')
                else:
                    user.tank_rating = None
                damage_rating = damage_rating.split(',')[0]
                if damage_rating != '0':
                    if damage_rating in rank_to_value:
                        try:
                            user.damage_rating = convert_rank_to_value(damage_rating)
                        except ValueError as e:
                            await ctx.send(f'Введите корректную команду. Пример: !update 4000, d2, 3700 | {e}')
                    else:
                        try:
                            user.damage_rating = int(damage_rating)
                        except ValueError as e:
                            await ctx.send(f'Введите корректную команду. Пример: !update 4000, d2, 3700 | {e}')
                else:
                    user.damage_rating = None
                support_rating = support_rating.split(',')[0]
                if support_rating != '0':
                    if support_rating in rank_to_value:
                        try:
                            user.support_rating = convert_rank_to_value(support_rating)
                        except ValueError as e:
                            await ctx.send(f'Введите корректную команду. Пример: !update 4000, d2, 3700 | {e}')
                    else:
                        try:
                            user.support_rating = int(support_rating)
                        except ValueError as e:
                            await ctx.send(f'Введите корректную команду. Пример: !update 4000, d2, 3700 | {e}')
                else:
                    user.support_rating = None
                session.commit()
                await ctx.send(f'nmkyt обновил рейтинг у {username}.')
                print(f'nmkyt successfully update rating of {username}.')


@bot.command()
async def update(ctx, tank_rating: str, damage_rating: str, support_rating: str):
    discord_id = ctx.author.id
    username = ctx.author.name
    user = session.query(Player).filter(Player.discord_id == str(discord_id)).first()
    if user is not None:
        if tank_rating and damage_rating and support_rating:
            tank_rating = tank_rating.split(',')[0]
            if tank_rating != '0':
                if tank_rating in rank_to_value:
                    try:
                        user.tank_rating = convert_rank_to_value(tank_rating)
                    except ValueError as e:
                        await ctx.send(f'Введите корректную команду. Пример: !update 4000, d2, 3700 | {e}')
                else:
                    try:
                        user.tank_rating = int(tank_rating)
                    except ValueError as e:
                        await ctx.send(f'Введите корректную команду. Пример: !update 4000, d2, 3700 | {e}')
            else:
                if user.priority_role != 'tank':
                    user.tank_rating = None
                else:
                    await ctx.send("Вы не можете обнулить рейтинг на роли, которая выбрана приоритетной")
                    raise Exception("Update Error")
            damage_rating = damage_rating.split(',')[0]
            if damage_rating != '0':
                if damage_rating in rank_to_value:
                    try:
                        user.damage_rating = convert_rank_to_value(damage_rating)
                    except ValueError as e:
                        await ctx.send(f'Введите корректную команду. Пример: !update 4000, d2, 3700 | {e}')
                else:
                    try:
                        user.damage_rating = int(damage_rating)
                    except ValueError as e:
                        await ctx.send(f'Введите корректную команду. Пример: !update 4000, d2, 3700 | {e}')
            else:
                if user.priority_role != 'damage':
                    user.damage_rating = None
                else:
                    await ctx.send("Вы не можете обнулить рейтинг на роли, которая выбрана приоритетной")
                    raise Exception("Update Error")
            support_rating = support_rating.split(',')[0]
            if support_rating != '0':
                if support_rating in rank_to_value:
                    try:
                        user.support_rating = convert_rank_to_value(support_rating)
                    except ValueError as e:
                        await ctx.send(f'Введите корректную команду. Пример: !update 4000, d2, 3700 | {e}')
                else:
                    try:
                        user.support_rating = int(support_rating)
                    except ValueError as e:
                        await ctx.send(f'Введите корректную команду. Пример: !update 4000, d2, 3700 | {e}')
            else:
                if user.priority_role != 'support':
                    user.support_rating = None
                else:
                    await ctx.send("Вы не можете обнулить рейтинг на роли, которая выбрана приоритетной")
                    raise Exception("Update Error")
            session.commit()
            await ctx.send('Вы успешно изменили свой рейтинг')
            print(f'User {username} successfully updated his rating.')
    else:
        await ctx.send('Вы не зарегистрированы в системе. Используйте !register для регистрации.')


# Регулярное выражение для проверки battle_tag (пример: Sacr1ficed#2456)
BATTLE_TAG_PATTERN = re.compile(r"^[a-zA-Z0-9]+#\d+$")


@bot.command()
async def register(ctx, battle_tag: str, tank_rating: str, damage_rating: str, support_rating: str):
    discord_id = ctx.author.id

    # Проверяем, зарегистрирован ли уже пользователь
    if session.query(Player).filter(Player.discord_id == str(discord_id)).first() is not None:
        await ctx.send('Вы уже зарегистрированы, для изменения пользователя используйте команду !update')
        return

    # Проверяем, что все поля не пустые
    if not (battle_tag and tank_rating and damage_rating and support_rating):
        await ctx.send('Введите корректную команду. Пример: !register Sacr1ficed#2456, 4000, d2, 3700')
        return

    # Проверка battle_tag
    if not BATTLE_TAG_PATTERN.match(battle_tag):
        await ctx.send('Неверный формат battle_tag. Пример: Sacr1ficed#2456')
        return

    # Функция для проверки и преобразования рейтингов
    def process_rating(rating):
        if rating in rank_to_value:  # Проверка на значение из словаря рангов
            return convert_rank_to_value(rating)
        try:
            return int(rating)  # Пробуем преобразовать в число
        except ValueError:
            raise ValueError('Неверный формат рейтинга')

    try:
        # Обрабатываем рейтинги
        tank_rating = process_rating(tank_rating.split(',')[0])
        damage_rating = process_rating(damage_rating.split(',')[0])
        support_rating = process_rating(support_rating.split(',')[0])
    except ValueError as e:
        await ctx.send(f'Введите корректную команду. Пример: !register Sacr1ficed#2456, 4000, d2, 3700 | {e}')
        return

    # Регистрируем пользователя
    username = battle_tag.split('#')[0]
    user_info = Player(
        name=username,
        tank_rating=tank_rating,
        damage_rating=damage_rating,
        support_rating=support_rating,
        priority_role='tank',
        discord_id=str(discord_id)
    )
    session.add(user_info)
    session.commit()

    print(f'User {username} successfully registered.')
    await ctx.send('Вы успешно зарегистрировались на миксы')


@bot.command()
async def uncheck(ctx, discord_id: str):
    user = session.query(Player).filter(Player.discord_id == str(discord_id)).first()
    if user:
        user.check_in = 'no'
        session.commit()
        user = session.query(Queue).filter(Queue.discord_id == str(discord_id)).first()
        if user:
            session.delete(user)
            session.commit()
        await ctx.send('Пользователь был успешно удален из очереди')
    else:
        await ctx.send('Пользователь не найден')


@bot.command()
async def create_lobby(ctx, lobby_count: int):
    lobbies, queued_players = create_lobbies_caller(lobby_count)
    for i, lobby in enumerate(lobbies):
        await ctx.send(f'**🌞 Лобби {i + 1}**')
        await ctx.send("**💙 Синяя команда**")
        await ctx.send(f'🛡️ **{lobby['team1']['tank'].name}** 🏹 **{lobby['team1']['damage'][0].name} |'
                       f' {lobby['team1']['damage'][1].name}**  💉 **{lobby['team1']['support'][0].name} |'
                       f' {lobby['team1']['support'][1].name}**')
        await ctx.send("**💖 Красная команда**")
        await ctx.send(
            f'🛡️ **{lobby['team2']['tank'].name}** 🏹 **{lobby['team2']['damage'][0].name} |'
            f' {lobby['team2']['damage'][1].name}** 💉 **{lobby['team2']['support'][0].name} |'
            f' {lobby['team2']['support'][1].name}**')
        await ctx.send(f'**🎲 Карта: {get_map()}**')
        teams_abs, match_rating = get_rating(lobby)
        await ctx.send(f'*Средний рейтинг матча {round(match_rating)}, Разница между командами: {teams_abs}*')
        await ctx.send('------------------------------------------')
    message = ''
    if queued_players:
        for player in queued_players:
            message = message + f'{player.name} '
        await ctx.send(f"**Ожидающие игроки**: {message}")


bot.run(BOT_TOKEN)
