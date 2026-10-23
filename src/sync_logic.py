import random
from src.balancer import create_lobbies, ROLE_NEEDS
from src.config import session
from src.models import Queue, Player, MIN_RATING, MAX_RATING

rank_to_value = {
    'b5': 500, 'b4': 600, 'b3': 700, 'b2': 800, 'b1': 900,
    's5': 1000, 's4': 1100, 's3': 1200, 's2': 1300, 's1': 1400,
    'g5': 1500, 'g4': 1600, 'g3': 1700, 'g2': 1800, 'g1': 1900,
    'p5': 2000, 'p4': 2100, 'p3': 2200, 'p2': 2300, 'p1': 2400,
    'e5': 2500, 'e4': 2600, 'e3': 2700, 'e2': 2800, 'e1': 2900,
    'd5': 3000, 'd4': 3100, 'd3': 3200, 'd2': 3300, 'd1': 3400,
    'm5': 3500, 'm4': 3600, 'm3': 3700, 'm2': 3800, 'm1': 3900,
    'gm5': 4000, 'gm4': 4100, 'gm3': 4200, 'gm2': 4300, 'gm1': 4400,
    'chm5': 4500, 'chm4': 4600, 'chm3': 4700, 'chm2': 4800, 'chm1': 5000
}


maps = [
    'Lijiang Tower', 'Antarctic Peninsula', 'Ilios', 'Nepal', 'Samoa',
    'Circuit Royal', 'Dorado', 'Havana', 'Junkertown', 'Rialto', 'Route 66',
    'Watchpoint: Gibraltar', 'Blizzard World', 'Eichenwalde', 'Hollywood',
    'Midtown', 'Paraiso', 'Colosseo', 'Runasapi', 'Oasis', 'Neon Junction'
]


def get_map():
    """Случайная карта для лобби."""
    return random.choice(maps)


def convert_rank_to_value(rank: str) -> int:
    """Дивизион (например, 'd2') -> числовой рейтинг; ValueError для неизвестного дивизиона."""
    if rank in rank_to_value:
        return rank_to_value.get(rank, "Invalid rank")
    else:
        raise ValueError("Invalid rank")


rank_tiers = [
    (4500, 'Champion'), (4000, 'Grandmaster'), (3500, 'Master'),
    (3000, 'Diamond'), (2500, 'Emerald'), (2000, 'Platinum'),
    (1500, 'Gold'), (1000, 'Silver'), (500, 'Bronze'),
]


def format_rating(value: int) -> str:
    """Числовой рейтинг -> вид как в Overwatch 2, например 3500 -> 'Master 5 (3500)'."""
    for base, tier in rank_tiers:
        if value >= base:
            division = max(1, 5 - (value - base) // 100)
            return f'{tier} {division} ({value})'
    return str(value)


def parse_rating_input(rating: str):
    """
    Разбирает пользовательский ввод рейтинга для одной роли:
    - '0' -> None (роль не играется);
    - дивизион (b5..cmp1, регистр не важен) -> число из rank_to_value;
    - иначе -> int, если он в диапазоне [MIN_RATING, MAX_RATING].
    Бросает ValueError с понятным сообщением при некорректном вводе.
    """
    rating = rating.split(',')[0].strip()
    if rating == '0':
        return None
    if rating.lower() in rank_to_value:
        return convert_rank_to_value(rating.lower())
    try:
        value = int(rating)
    except ValueError:
        raise ValueError(f'неверный рейтинг «{rating}» — укажите число от {MIN_RATING} до {MAX_RATING}, '
                         f'дивизион (например, d2 или gm3) или 0, если роль не играется.')
    if not (MIN_RATING <= value <= MAX_RATING):
        raise ValueError(f'рейтинг {value} вне диапазона — допустимо от {MIN_RATING} до {MAX_RATING} '
                         f'(или 0, если роль не играется).')
    return value


def parse_rating_update(rating: str, role: str, current_priority):
    """
    Как parse_rating_input, но дополнительно запрещает обнулить рейтинг той роли,
    которая сейчас выбрана приоритетной (или flex) — используется в !update,
    где игрок меняет рейтинг самостоятельно.
    """
    if rating.split(',')[0].strip() == '0' and current_priority in (role, 'flex'):
        raise ValueError('нельзя обнулить рейтинг на приоритетной роли (или при выбранном flex) — '
                         'сначала выберите другую приоритетную роль на чек-ине.')
    return parse_rating_input(rating)


def check_queue():
    """Имена игроков, стоящих в очереди."""
    queue = []
    queued_players = session.query(Queue).all()
    players = session.query(Player).all()
    for player in players:
        for queued in queued_players:
            if queued.discord_id == player.discord_id:
                queue.append(player.name)
    return queue


def active_players():
    """Возвращает (имена отметившихся игроков, их количество)."""
    active = []
    players = session.query(Player).filter(Player.check_in == 'yes').all()
    for player in players:
        active.append(player.name)
    return active, len(active)


PLAYERS_PER_LOBBY = 10


def mix_status():
    """Сводка для !mix_status: регистрации, чек-ин, приоритетные роли, очередь и сколько лобби можно собрать."""
    total = session.query(Player).count()
    checked_in = session.query(Player).filter(Player.check_in == 'yes').all()
    checked_ids = {player.discord_id for player in checked_in}

    by_priority = {role: 0 for role in ('tank', 'damage', 'support', 'flex')}
    for player in checked_in:
        if player.priority_role in by_priority:
            by_priority[player.priority_role] += 1

    # рейтинг на роли указан — значит, игрок может её закрыть
    can_play = {
        'tank': sum(1 for p in checked_in if p.tank_rating is not None),
        'damage': sum(1 for p in checked_in if p.damage_rating is not None),
        'support': sum(1 for p in checked_in if p.support_rating is not None),
    }

    queued = sum(1 for q in session.query(Queue).all() if q.discord_id in checked_ids)

    lobbies = len(checked_in) // PLAYERS_PER_LOBBY
    # max(lobbies, 1): подсказываем нехватку ролей, даже когда людей нет и на одно лобби
    short_roles = [role for role, need in ROLE_NEEDS.items() if can_play[role] < need * max(lobbies, 1)]
    return {
        'total': total,
        'checked_in': len(checked_in),
        'by_priority': by_priority,
        'can_play': can_play,
        'queued': queued,
        'lobbies': lobbies,
        'to_next_lobby': PLAYERS_PER_LOBBY - len(checked_in) % PLAYERS_PER_LOBBY,
        'short_roles': short_roles,
    }


def end():
    """Снимает чек-ин со всех игроков (конец вечера миксов)."""
    players = session.query(Player).all()
    for player in players:
        player.check_in = 'no'
    session.commit()


def get_rating(lobby):
    """Возвращает (разница рейтинга команд в пересчёте на игрока, средний рейтинг игрока в матче)."""
    team1_rating = (sum(player.tank_rating for player in [lobby["team1"]["tank"]] if player) +
                   sum(player.damage_rating for player in lobby["team1"]["damage"]) +
                   sum(player.support_rating for player in lobby["team1"]["support"]))
    team2_rating = (sum(player.tank_rating for player in [lobby["team2"]["tank"]] if player) +
                   sum(player.damage_rating for player in lobby["team2"]["damage"]) +
                   sum(player.support_rating for player in lobby["team2"]["support"]))
    match_rating = (team1_rating + team2_rating) / 10
    return abs(team1_rating - team2_rating) / 5, match_rating


def create_lobbies_caller(lobby_count):
    """Собирает лобби через create_lobbies и записывает не попавших в лобби в очередь.

    Частичный успех (собрано меньше лобби, чем запрошено) — не ошибка. Очередь
    перезаписывается, только если собрано хотя бы одно лобби, иначе остаётся прежней.
    ValueError из create_lobbies пробрасывается: что ответить пользователю, решает !create_lobby.
    """
    lobbies, queued_players = create_lobbies(lobby_count)
    if lobbies:
        try:
            session.query(Queue).delete()
            session.add_all([Queue(discord_id=player.discord_id) for player in queued_players])
            session.commit()
        except Exception:
            session.rollback()
            raise
    return lobbies, queued_players
