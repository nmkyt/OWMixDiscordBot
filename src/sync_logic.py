import random
import re
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


_map_bag = []
_last_map = None


def get_map():
    """Случайная карта для лобби без повторов, пока не сыграны все остальные.

    Карты выдаются из «мешка»: он перемешивается целиком, карты достаются по одной, и только
    когда мешок опустел, перемешивается заново. Так карта не повторится раньше, чем пройдут
    все остальные, — в том числе между лобби одного !create_lobby. На стыке двух мешков
    следующей картой не бывает та, что вышла последней. Состояние хранится в памяти:
    после перезапуска бота цикл начинается заново.
    """
    global _last_map
    if not _map_bag:
        _map_bag.extend(maps)
        random.shuffle(_map_bag)
        if len(_map_bag) > 1 and _map_bag[-1] == _last_map:
            _map_bag[0], _map_bag[-1] = _map_bag[-1], _map_bag[0]
    _last_map = _map_bag.pop()
    return _last_map


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


BATTLE_TAG_PATTERN = re.compile(r"^[\w]+#\d+$")
ROLE_INPUT_LABELS = {'tank': 'Танк', 'damage': 'DPS', 'support': 'Саппорт'}


def parse_battle_tag(battle_tag: str) -> str:
    """BattleTag (Sacr1ficed#2456) -> имя игрока (Sacr1ficed); ValueError при неверном формате."""
    if not BATTLE_TAG_PATTERN.match(battle_tag):
        raise ValueError(f'Неверный формат BattleTag «{battle_tag}»: нужно имя и номер через #.')
    return battle_tag.split('#')[0]


def parse_ratings(tank_rating: str, damage_rating: str, support_rating: str):
    """Разбирает рейтинги трёх ролей -> (tank, damage, support). ValueError с названием роли
    при неверном вводе или если все роли нулевые."""
    values = {}
    for role, raw in (('tank', tank_rating), ('damage', damage_rating), ('support', support_rating)):
        try:
            values[role] = parse_rating_input(raw)
        except ValueError as e:
            raise ValueError(f'{ROLE_INPUT_LABELS[role]}: {e}') from e
    if all(value is None for value in values.values()):
        raise ValueError('Укажите рейтинг хотя бы на одной роли (0 — только для ролей, которые вы не играете).')
    return values['tank'], values['damage'], values['support']


def get_player(discord_id):
    """Игрок по Discord ID или None."""
    return session.query(Player).filter(Player.discord_id == str(discord_id)).first()


def pick_priority_role(current, tank_rating, damage_rating, support_rating):
    """Приоритетная роль, совместимая с рейтингами: текущая, если на ней остался рейтинг
    (для flex — на всех трёх ролях), иначе первая роль с рейтингом (танк, урон, саппорт)."""
    ratings = {'tank': tank_rating, 'damage': damage_rating, 'support': support_rating}
    if current == 'flex' and all(value is not None for value in ratings.values()):
        return current
    if ratings.get(current) is not None:
        return current
    return next((role for role, value in ratings.items() if value is not None), None)


def register_player(discord_id, name: str, tank_rating, damage_rating, support_rating) -> bool:
    """Регистрирует игрока с уже разобранными рейтингами. Приоритетная роль — первая роль
    с рейтингом (танк, урон, саппорт). Возвращает False, если игрок уже зарегистрирован."""
    if get_player(discord_id) is not None:
        return False
    session.add(Player(
        name=name,
        tank_rating=tank_rating,
        damage_rating=damage_rating,
        support_rating=support_rating,
        priority_role=pick_priority_role(None, tank_rating, damage_rating, support_rating),
        discord_id=str(discord_id),
        check_in='no',
    ))
    session.commit()
    return True


def update_player_ratings(discord_id, tank_rating: str, damage_rating: str, support_rating: str):
    """Разбирает и сохраняет рейтинги игрока. Если на приоритетной роли рейтинга больше нет,
    роль меняется по pick_priority_role.

    Возвращает (имя, прежняя приоритетная роль, новая приоритетная роль) или None,
    если игрок не зарегистрирован; ValueError при неверном вводе.
    """
    user = get_player(discord_id)
    if user is None:
        return None
    ratings = parse_ratings(tank_rating, damage_rating, support_rating)
    old_priority = user.priority_role
    user.tank_rating, user.damage_rating, user.support_rating = ratings
    user.priority_role = pick_priority_role(old_priority, *ratings)
    session.commit()
    return user.name, old_priority, user.priority_role


def update_user_status(user_id, field, value):
    """Меняет чек-ин (field='checked_in', value 'yes'/'no') или приоритетную роль (field='priority_role').

    Возвращает True при успехе, 'not_registered', 'no_role' (чек-ин без выбранной роли)
    или False (на выбранной роли нет рейтинга).
    """
    user = get_player(user_id)
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


def uncheck_player(discord_id) -> bool:
    """Снимает чек-ин с игрока и убирает его из очереди; False, если игрок не зарегистрирован."""
    user = get_player(discord_id)
    if user is None:
        return False
    user.check_in = 'no'
    session.query(Queue).filter(Queue.discord_id == str(discord_id)).delete()
    session.commit()
    return True


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


def add_to_queue(discord_id):
    """Ставит игрока в конец очереди. Возвращает (статус, игрок), где статус —
    'added', 'already_queued' или 'not_registered' (тогда игрок None)."""
    user = get_player(discord_id)
    if user is None:
        return 'not_registered', None
    if session.query(Queue).filter(Queue.discord_id == str(discord_id)).first() is not None:
        return 'already_queued', user
    session.add(Queue(discord_id=str(discord_id)))
    session.commit()
    return 'added', user


def remove_from_queue(discord_id) -> bool:
    """Убирает игрока из очереди; False, если его там не было."""
    removed = session.query(Queue).filter(Queue.discord_id == str(discord_id)).delete()
    session.commit()
    return removed > 0


def clear_queue():
    """Очищает очередь."""
    session.query(Queue).delete()
    session.commit()


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


def team_ratings(lobby):
    """Возвращает (суммарный рейтинг команды 1, суммарный рейтинг команды 2)."""
    team1_rating = (sum(player.tank_rating for player in [lobby["team1"]["tank"]] if player) +
                   sum(player.damage_rating for player in lobby["team1"]["damage"]) +
                   sum(player.support_rating for player in lobby["team1"]["support"]))
    team2_rating = (sum(player.tank_rating for player in [lobby["team2"]["tank"]] if player) +
                   sum(player.damage_rating for player in lobby["team2"]["damage"]) +
                   sum(player.support_rating for player in lobby["team2"]["support"]))
    return team1_rating, team2_rating


def get_rating(lobby):
    """Возвращает (разница рейтинга команд в пересчёте на игрока, средний рейтинг игрока в матче)."""
    team1_rating, team2_rating = team_ratings(lobby)
    match_rating = (team1_rating + team2_rating) / 10
    return abs(team1_rating - team2_rating) / 5, match_rating


# (верхняя граница разницы в SR на игрока, значок, оценка). Границы выбраны по симуляции
# сотен лобби: до 25 SR укладывается около 55% лобби, до 50 — около 77%, свыше 100 — 7-8%.
BALANCE_LEVELS = (
    (10, '🟢', 'Идеальный баланс'),
    (25, '🟢', 'Ровные команды'),
    (50, '🟡', 'Небольшой перевес'),
    (100, '🟠', 'Заметный перевес'),
    (float('inf'), '🔴', 'Сильный перевес'),
)
TEAM_NAMES = ('💙 Синие', '💖 Красные')


def describe_balance(lobby):
    """Две строки о балансе лобби для !create_lobby: оценка словами (при заметном перевесе — с
    указанием, какая команда сильнее и на сколько SR на игрока) и средний рейтинг игрока
    в каждой команде."""
    team1_rating, team2_rating = team_ratings(lobby)
    diff = round(abs(team1_rating - team2_rating) / 5)
    match_rating = round((team1_rating + team2_rating) / 10)
    icon, verdict = next((icon, verdict) for limit, icon, verdict in BALANCE_LEVELS if diff < limit)

    if diff < BALANCE_LEVELS[0][0]:
        summary = f'{icon} {verdict}'
    else:
        stronger = TEAM_NAMES[0 if team1_rating > team2_rating else 1]
        summary = f'{stronger} — {icon} {verdict}: +{diff} SR на игрока'
    return (f'Средний рейтинг матча {match_rating} SR\n'
            f'{summary} (💙 {round(team1_rating / 5)} · 💖 {round(team2_rating / 5)})')


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
