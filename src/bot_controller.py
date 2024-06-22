from config import bot, BOT_TOKEN, session
from models import Player
from sync_logic import convert_rank_to_value, rank_to_value


@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name}')


@bot.command()
async def check(ctx):
    message = await ctx.send('Чекин на миксы начался! Нажмите ✅ и выберите приоритетную роль.')
    reactions = ['✅', '🛡', '🏹', '💉']
    for reaction in reactions:
        await message.add_reaction(reaction)


@bot.command()
async def register(ctx, battle_tag: str, tank_rating: str, damage_rating: str, support_rating: str):
    discord_id = ctx.author.id
    if session.query(Player).filter(Player.discord_id == str(discord_id)).first():
        if battle_tag and tank_rating and damage_rating and support_rating:
            username = battle_tag.split('#')[0]
            tank_rating = tank_rating.split(',')[0]
            if tank_rating != '0':
                if tank_rating in rank_to_value:
                    try:
                        tank_rating = convert_rank_to_value(tank_rating)
                    except ValueError as e:
                        await ctx.send(f'Введите корректную команду. Пример: Sacr1ficed#2456, 4000, d2, 3700 | {e}')
                else:
                    try:
                        tank_rating = int(tank_rating)
                    except ValueError as e:
                        await ctx.send(f'Введите корректную команду. Пример: Sacr1ficed#2456, 4000, d2, 3700 | {e}')
            damage_rating = damage_rating.split(',')[0]
            if damage_rating != '0':
                if damage_rating in rank_to_value:
                    try:
                        damage_rating = convert_rank_to_value(damage_rating)
                    except ValueError as e:
                        await ctx.send(f'Введите корректную команду. Пример: Sacr1ficed#2456, 4000, d2, 3700 | {e}')
                else:
                    try:
                        damage_rating = int(damage_rating)
                    except ValueError as e:
                        await ctx.send(f'Введите корректную команду. Пример: Sacr1ficed#2456, 4000, d2, 3700 | {e}')
            support_rating = support_rating.split(',')[0]
            if support_rating != '0':
                if support_rating in rank_to_value:
                    try:
                        support_rating = convert_rank_to_value(support_rating)
                    except ValueError as e:
                        await ctx.send(f'Введите корректную команду. Пример: Sacr1ficed#2456, 4000, d2, 3700 | {e}')
                else:
                    try:
                        support_rating = int(support_rating)
                    except ValueError as e:
                        await ctx.send(f'Введите корректную команду. Пример: Sacr1ficed#2456, 4000, d2, 3700 | {e}')
            user_info = Player(name=username,
                               tank_rating=tank_rating,
                               damage_rating=damage_rating,
                               support_rating=support_rating,
                               discord_id=str(discord_id))
            session.add(user_info)
            session.commit()
            await ctx.send('Вы успешно зарегистрировались на миксы')
        else:
            await ctx.send('Введите корректную команду. Пример: Sacr1ficed#2456, 4000, d2, 3700')
    else:
        await ctx.send('Вы уже зарегистрированы, для изменения пользователя используйте команду !edit')


async def on_reaction_add(reaction, user):
    if user.bot:
        return
    user_id = user.id
    user_name = user.name
    emoji = str(reaction.emoji)

    try:
        user = session.query(Player).filter(Player.discord_id == str(user_id)).first()
        if emoji == '✅':
            print(f'User {user_name} successfully checked in')
            user.checked_in = 'yes'
        if emoji == '🛡':
            print(f'User {user_name} successfully set priority role as Tank')
            user.priority_role = 'tank'
        if emoji == '🏹':
            print(f'User {user_name} successfully set priority role as DPS')
            user.priority_role = 'damage'
        if emoji == '💉':
            print(f'User {user_name} successfully set priority role as Support')
            user.priority_role = 'support'
        session.commit()
    except Exception as e:
        print(f'Error on reaction add: {str(e)}')

bot.run(BOT_TOKEN)
