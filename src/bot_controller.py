import discord
from config import bot, BOT_TOKEN, session
from models import Player, Queue
from sync_logic import convert_rank_to_value, rank_to_value, create_lobbies_caller, get_map


class CheckinView(discord.ui.View):
    foo: bool = None
    role: str = ''

    @discord.ui.button(label='✅Check-in', style=discord.ButtonStyle.success)
    async def check_in(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.foo = True
        user_id = interaction.user.id
        user_name = interaction.user.name
        await interaction.response.defer()
        await update_user_status(user_id, 'checked_in', 'yes')
        print(f'User {user_name} successfully checked in')
        await interaction.followup.send(f"{user_name} успешно прошел чек-ин", ephemeral=True)

    @discord.ui.button(label='❌Check-out', style=discord.ButtonStyle.danger)
    async def check_out(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.foo = False
        user_id = interaction.user.id
        user_name = interaction.user.name
        await interaction.response.defer()
        await update_user_status(user_id, 'checked_in', 'no')
        print(f'User {user_name} successfully checked out')
        await interaction.followup.send(f"{user_name} успешно прошел чек-аут", ephemeral=True)

    @discord.ui.button(label='🛡️ Tank', style=discord.ButtonStyle.gray)
    async def tank(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.role = 'tank'
        user_id = interaction.user.id
        user_name = interaction.user.name
        await interaction.response.defer()
        await update_user_status(user_id, 'priority_role', 'tank')
        print(f'User {user_name} set priority role as Tank')
        await interaction.followup.send(f"{user_name} успешно выбрал танка приоритетной ролью", ephemeral=True)

    @discord.ui.button(label='🏹 DPS', style=discord.ButtonStyle.gray)
    async def dps(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.role = 'damage'
        user_id = interaction.user.id
        user_name = interaction.user.name
        await interaction.response.defer()
        await update_user_status(user_id, 'priority_role', 'damage')
        print(f'User {user_name} successfully set priority role as DPS')
        await interaction.followup.send(f"{user_name} успешно выбрал урон приоритетной ролью", ephemeral=True)

    @discord.ui.button(label='💉 Support', style=discord.ButtonStyle.gray)
    async def support(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.role = 'support'
        user_id = interaction.user.id
        user_name = interaction.user.name
        await interaction.response.defer()
        await update_user_status(user_id, 'priority_role', 'support')
        print(f'User {user_name} successfully set priority role as Support')
        await interaction.followup.send(f"{user_name} успешно выбрал поддержку приоритетной ролью", ephemeral=True)


@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name}')


@bot.command()
async def check(ctx):
    view = CheckinView(timeout=14400)
    await ctx.send(
        'Чекин на миксы начался! Обратите внимание, что пройти check-in могут только зарегистрированные игроки.')
    await ctx.send('Нажмите ✅ и выберите приоритетную роль. Пожалуйста, нажмите ❌, если покидаете миксы.', view=view)


async def update_user_status(user_id, field, value):
    try:
        user = session.query(Player).filter(Player.discord_id == str(user_id)).first()
        if field == 'checked_in':
            user.check_in = value
        if field == 'priority_role':
            user.priority_role = value
            session.commit()
        session.commit()
    except Exception as e:
        print(f'Error updating user status: {str(e)}')


@bot.command()
async def update(ctx, tank_rating: str, damage_rating: str, support_rating: str):
    discord_id = ctx.author.id
    username = ctx.author.name
    user = session.query(Player).filter(Player.discord_id == str(discord_id)).first()
    if tank_rating and damage_rating and support_rating:
        tank_rating = tank_rating.split(',')[0]
        if tank_rating != '0':
            if tank_rating in rank_to_value:
                try:
                    user.tank_rating = convert_rank_to_value(tank_rating)
                except ValueError as e:
                    await ctx.send(f'Введите корректную команду. Пример: !edit 4000, d2, 3700 | {e}')
            else:
                try:
                    user.tank_rating = int(tank_rating)
                except ValueError as e:
                    await ctx.send(f'Введите корректную команду. Пример: !edit 4000, d2, 3700 | {e}')
        damage_rating = damage_rating.split(',')[0]
        if damage_rating != '0':
            if damage_rating in rank_to_value:
                try:
                    user.damage_rating = convert_rank_to_value(damage_rating)
                except ValueError as e:
                    await ctx.send(f'Введите корректную команду. Пример: !edit 4000, d2, 3700 | {e}')
            else:
                try:
                    user.damage_rating = int(damage_rating)
                except ValueError as e:
                    await ctx.send(f'Введите корректную команду. Пример: !edit 4000, d2, 3700 | {e}')
        support_rating = support_rating.split(',')[0]
        if support_rating != '0':
            if support_rating in rank_to_value:
                try:
                    user.support_rating = convert_rank_to_value(support_rating)
                except ValueError as e:
                    await ctx.send(f'Введите корректную команду. Пример: !edit 4000, d2, 3700 | {e}')
            else:
                try:
                    user.support_rating = int(support_rating)
                except ValueError as e:
                    await ctx.send(f'Введите корректную команду. Пример: !edit 4000, d2, 3700 | {e}')
        session.commit()
        await ctx.send('Вы успешно изменили свой рейтинг')
        print(f'User {username} successfully edited his rating')


@bot.command()
async def register(ctx, battle_tag: str, tank_rating: str, damage_rating: str, support_rating: str):
    discord_id = ctx.author.id
    if session.query(Player).filter(Player.discord_id == str(discord_id)).first() is None:
        if battle_tag and tank_rating and damage_rating and support_rating:
            username = battle_tag.split('#')[0]
            tank_rating = tank_rating.split(',')[0]
            if tank_rating != '0':
                if tank_rating in rank_to_value:
                    try:
                        tank_rating = convert_rank_to_value(tank_rating)
                    except ValueError as e:
                        await ctx.send(f'Введите корректную команду. Пример: !register Sacr1ficed#2456, 4000, d2, '
                                       f'3700 | {e}')
                else:
                    try:
                        tank_rating = int(tank_rating)
                    except ValueError as e:
                        await ctx.send(f'Введите корректную команду. Пример: !register Sacr1ficed#2456, 4000, d2, '
                                       f'3700 | {e}')
            damage_rating = damage_rating.split(',')[0]
            if damage_rating != '0':
                if damage_rating in rank_to_value:
                    try:
                        damage_rating = convert_rank_to_value(damage_rating)
                    except ValueError as e:
                        await ctx.send(f'Введите корректную команду. Пример: !register Sacr1ficed#2456, 4000, d2, '
                                       f'3700 | {e}')
                else:
                    try:
                        damage_rating = int(damage_rating)
                    except ValueError as e:
                        await ctx.send(f'Введите корректную команду. Пример: !register Sacr1ficed#2456, 4000, d2, '
                                       f'3700 | {e}')
            support_rating = support_rating.split(',')[0]
            if support_rating != '0':
                if support_rating in rank_to_value:
                    try:
                        support_rating = convert_rank_to_value(support_rating)
                    except ValueError as e:
                        await ctx.send(f'Введите корректную команду. Пример: !register Sacr1ficed#2456, 4000, d2, '
                                       f'3700 | {e}')
                else:
                    try:
                        support_rating = int(support_rating)
                    except ValueError as e:
                        await ctx.send(f'Введите корректную команду. Пример: !register Sacr1ficed#2456, 4000, d2, '
                                       f'3700 | {e}')
            user_info = Player(name=username,
                               tank_rating=tank_rating,
                               damage_rating=damage_rating,
                               support_rating=support_rating,
                               discord_id=str(discord_id))
            session.add(user_info)
            session.commit()
            print(f'User {username} successfully registered.')
            await ctx.send('Вы успешно зарегистрировались на миксы')
        else:
            await ctx.send('Введите корректную команду. Пример: !register Sacr1ficed#2456, 4000, d2, 3700')
    else:
        await ctx.send('Вы уже зарегистрированы, для изменения пользователя используйте команду !update')


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
        await ctx.send('------------------------------------------')
    message = ''
    if queued_players:
        for player in queued_players:
            message = message + f'{player.name} '
        await ctx.send(f"**Ожидающие игроки**: {message}")


bot.run(BOT_TOKEN)
