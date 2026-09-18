import logging
import random
from src.balancer import create_lobbies
from src.config import session
from src.models import Queue, Player, MIN_RATING, MAX_RATING

logger = logging.getLogger(__name__)

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
    return random.choice(maps)


def convert_rank_to_value(rank: str) -> int:
    if rank in rank_to_value:
        return rank_to_value.get(rank, "Invalid rank")
    else:
        raise ValueError("Invalid rank")


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
        raise ValueError('Неверный формат рейтинга')
    if not (MIN_RATING <= value <= MAX_RATING):
        raise ValueError(f'Рейтинг должен быть в диапазоне от {MIN_RATING} до {MAX_RATING} (или 0, если роль не играется)')
    return value


def parse_rating_update(rating: str, role: str, current_priority):
    """
    Как parse_rating_input, но дополнительно запрещает обнулить рейтинг той роли,
    которая сейчас выбрана приоритетной (или flex) — используется в !update,
    где игрок меняет рейтинг самостоятельно.
    """
    if rating.split(',')[0].strip() == '0' and current_priority in (role, 'flex'):
        raise ValueError('Вы не можете обнулить рейтинг на роли, которая выбрана приоритетной')
    return parse_rating_input(rating)


def check_queue():
    queue = []
    queued_players = session.query(Queue).all()
    players = session.query(Player).all()
    for player in players:
        for queued in queued_players:
            if queued.discord_id == player.discord_id:
                queue.append(player.name)
    return queue


def active_players():
    active = []
    players = session.query(Player).filter(Player.check_in == 'yes').all()
    for player in players:
        active.append(player.name)
    return active, len(active)


def end():
    players = session.query(Player).all()
    for player in players:
        player.check_in = 'no'
    session.commit()


def get_rating(lobby):
    team1_rating = (sum(player.tank_rating for player in [lobby["team1"]["tank"]] if player) +
                   sum(player.damage_rating for player in lobby["team1"]["damage"]) +
                   sum(player.support_rating for player in lobby["team1"]["support"]))
    team2_rating = (sum(player.tank_rating for player in [lobby["team2"]["tank"]] if player) +
                   sum(player.damage_rating for player in lobby["team2"]["damage"]) +
                   sum(player.support_rating for player in lobby["team2"]["support"]))
    match_rating = (team1_rating + team2_rating) / 10
    return abs(team1_rating - team2_rating) / 5, match_rating


def create_lobbies_caller(lobby_count):
    """
    create_lobbies может вернуть меньше лобби, чем запрошено (если для остальных не
    хватило игроков) — это не ошибка, а частичный успех, и его тоже нужно обработать:
    оставшихся игроков вернуть в очередь. Полностью неудачные случаи (ValueError из
    create_lobbies) не ловим — вызывающий код (!create_lobby) сам решает, что сказать
    пользователю.
    """
    lobbies, queued_players = create_lobbies(lobby_count)
    if len(lobbies) < lobby_count:
        logger.warning(f'Only formed {len(lobbies)}/{lobby_count} requested lobbies')
    for player in queued_players:
        user = Queue(discord_id=player.discord_id)
        session.add(user)
        session.commit()
    return lobbies, queued_players

