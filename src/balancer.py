from src.config import session
from src.models import Player, Queue
import random, json, os, logging
from itertools import combinations

logger = logging.getLogger(__name__)

HISTORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "recent_pairs.json")
ALPHA_TEAMMATE = 50
ALPHA_OPPONENT = 10
WINDOW_GAMES = 6
GAME_INDEX = 0
RECENT_PAIRS = {}


def _pair_key(a, b):
    a, b = (str(a), str(b))
    return a+"-"+b if a < b else b+"-"+a


def init_history():
    global RECENT_PAIRS, GAME_INDEX
    if os.path.exists(HISTORY_FILE):
        try:
            data = json.load(open(HISTORY_FILE, "r", encoding="utf-8"))
            RECENT_PAIRS = data.get("pairs", {})
            GAME_INDEX = int(data.get("game_index", 0))
        except Exception as e:
            logger.warning(f'Failed to load history file, starting fresh: {e}')
            RECENT_PAIRS, GAME_INDEX = {}, 0
    else:
        RECENT_PAIRS, GAME_INDEX = {}, 0


def save_history():
    json.dump({"pairs": RECENT_PAIRS, "game_index": GAME_INDEX},
              open(HISTORY_FILE, "w", encoding="utf-8"),
              ensure_ascii=False)


def pair_penalty(p1, p2, as_mates=True):
    """
    Возвращает штраф за «недавнюю близость».
    Чем ближе к текущему GAME_INDEX была совместная игра, тем больше штраф.
    """
    key = _pair_key(p1.discord_id, p2.discord_id)
    rec = RECENT_PAIRS.get(key, {})
    seq = rec.get("last_as_mates", []) if as_mates else rec.get("last_as_foes", [])
    pen = 0
    # линейное затухание в пределах окна WINDOW_GAMES
    for idx in seq:
        age = GAME_INDEX - idx
        if 0 <= age < WINDOW_GAMES:
            pen += (WINDOW_GAMES - age)
    return pen


def update_history_with_lobby(lobby):
    """
    Обновляет историю для всех пар:
    - товарищи по команде -> last_as_mates
    - игроки из разных команд -> last_as_foes (меньший вес)
    """
    global GAME_INDEX
    GAME_INDEX += 1

    def ids_of_team(team):
        members = []
        if team["tank"]:
            members.append(team["tank"])
        members.extend(team["damage"])
        members.extend(team["support"])
        return [m.discord_id for m in members]

    t1_ids = ids_of_team(lobby["team1"])
    t2_ids = ids_of_team(lobby["team2"])

    for team_ids in (t1_ids, t2_ids):
        for a, b in combinations(team_ids, 2):
            key = _pair_key(a, b)
            rec = RECENT_PAIRS.setdefault(key, {"last_as_mates": [], "last_as_foes": []})
            rec["last_as_mates"].append(GAME_INDEX)
            if len(rec["last_as_mates"]) > WINDOW_GAMES:
                rec["last_as_mates"] = rec["last_as_mates"][-WINDOW_GAMES:]

    for a in t1_ids:
        for b in t2_ids:
            key = _pair_key(a, b)
            rec = RECENT_PAIRS.setdefault(key, {"last_as_mates": [], "last_as_foes": []})
            rec["last_as_foes"].append(GAME_INDEX)
            if len(rec["last_as_foes"]) > WINDOW_GAMES:
                rec["last_as_foes"] = rec["last_as_foes"][-WINDOW_GAMES:]

    save_history()


def get_players():
    free_players = session.query(Player).filter(Player.check_in == 'yes').all()
    random.shuffle(free_players)
    return free_players


def get_queue():
    queued_players = session.query(Queue).all()
    free_players = get_players()
    queue = []
    if queued_players:
        for player_queue in queued_players:
            for player_free in free_players:
                if player_queue.discord_id == player_free.discord_id:
                    queue.append(player_free)
                    free_players.remove(player_free)
                    break
    session.query(Queue).delete()
    session.commit()
    return queue, free_players


def find_closest_tanks(free_players, queued_players):
    """ Находит двух ближайших игроков на роли 'Танк', включая queued_players. """
    tanks = [p for p in free_players if p.priority_role in ("tank", "flex")]
    selected = []

    # queued первыми
    queued_tanks = [p for p in queued_players if p.priority_role in ("tank", "flex")]
    selected.extend(queued_tanks)

    if len(tanks) + len(selected) < 2:
        tanks = [p for p in free_players if p.tank_rating is not None]
    if len(tanks) + len(selected) < 2:
        raise ValueError("Недостаточно игроков на роли Танк")

    min_cost, best_pair = float('inf'), None
    cand = [p for p in tanks if p not in selected]
    for i in range(len(cand)):
        for j in range(i + 1, len(cand)):
            a, b = cand[i], cand[j]
            diff = abs(a.tank_rating - b.tank_rating)
            penalty_mates = pair_penalty(a, b, as_mates=True)
            penalty_foes = pair_penalty(a, b, as_mates=False)
            cost = diff + ALPHA_TEAMMATE * penalty_mates + ALPHA_OPPONENT * penalty_foes
            if cost < min_cost:
                min_cost, best_pair = cost, [a, b]

    if len(selected) == 1:
        best = None
        min_cost = float('inf')
        for p in cand:
            if p == selected[0]:
                continue
            diff = abs(p.tank_rating - selected[0].tank_rating)
            cost = diff + ALPHA_TEAMMATE * pair_penalty(p, selected[0], True) + ALPHA_OPPONENT * pair_penalty(p, selected[0], False)
            if cost < min_cost:
                min_cost, best = cost, p
        if best:
            selected.append(best)
    else:
        if best_pair is None:
            raise ValueError("Недостаточно игроков на роли Танк для формирования пары")
        selected.extend(best_pair[: 2 - len(selected)])

    for player in list(selected):
        if player in free_players:
            free_players.remove(player)
        if player in queued_players:
            queued_players.remove(player)
    return selected, free_players, queued_players


def _greedy_pick_with_penalties(role_players, selected, rating_attr):
    """
    Добирает следующего игрока, минимизируя:
        sum |rating(candidate) - rating(sel)| + ALPHA*(штрафы за недавние пары с каждым sel)
    """
    best_idx, best_cost = None, float('inf')
    for i, candidate in enumerate(role_players):
        diff_sum = 0
        pen_sum = 0
        for s in selected:
            r_c = getattr(candidate, rating_attr)
            r_s = getattr(s, rating_attr)
            diff_sum += abs(r_c - r_s)
            pen_sum += ALPHA_TEAMMATE * pair_penalty(candidate, s, True) + ALPHA_OPPONENT * pair_penalty(candidate, s, False)
        cost = diff_sum + pen_sum
        if cost < best_cost:
            best_cost, best_idx = cost, i
    return best_idx


def find_closest_damage(free_players, queued_players):
    """ Находит четырех ближайших игроков на роли 'Урон', включая queued_players, c анти-повторами. """
    damage = [p for p in free_players if p.priority_role in ("damage", "flex")]
    selected = []

    queued_damage = [p for p in queued_players if p.priority_role in ("damage", "flex")]
    selected.extend(queued_damage)

    if len(damage) + len(selected) < 4:
        damage = [p for p in free_players if p.damage_rating is not None]
    if len(damage) + len(selected) < 4:
        raise ValueError("Недостаточно игроков на роли Урон")

    remaining = [p for p in damage if p not in selected]
    while len(selected) < 4:
        idx = _greedy_pick_with_penalties(remaining, selected, "damage_rating")
        selected.append(remaining.pop(idx))

    for player in list(selected):
        if player in free_players:
            free_players.remove(player)
        if player in queued_players:
            queued_players.remove(player)
    return selected, free_players, queued_players


def find_closest_support(free_players, queued_players):
    """ Находит четырех ближайших игроков на роли 'Поддержка', включая queued_players, c анти-повторами. """
    support = [p for p in free_players if p.priority_role in ("support", "flex")]
    selected = []

    queued_support = [p for p in queued_players if p.priority_role in ("support", "flex")]
    selected.extend(queued_support)

    if len(support) + len(selected) < 4:
        support = [p for p in free_players if p.support_rating is not None]
    if len(support) + len(selected) < 4:
        raise ValueError("Недостаточно игроков на роли Поддержка")

    remaining = [p for p in support if p not in selected]
    while len(selected) < 4:
        idx = _greedy_pick_with_penalties(remaining, selected, "support_rating")
        selected.append(remaining.pop(idx))

    for player in list(selected):
        if player in free_players:
            free_players.remove(player)
        if player in queued_players:
            queued_players.remove(player)
    return selected, free_players, queued_players


def check_lobby_status(lobby):
    if lobby['team1']['tank'] is None: return False
    for p in lobby['team1']['damage']:
        if p is None: return False
    for p in lobby['team1']['support']:
        if p is None: return False
    if lobby['team2']['tank'] is None: return False
    for p in lobby['team2']['damage']:
        if p is None: return False
    for p in lobby['team2']['support']:
        if p is None: return False
    return True


def create_lobbies(lobby_count):
    # инициализируем/загружаем историю
    init_history()

    queued_players, free_players = get_queue()
    if (lobby_count * 10) > (len(queued_players) + len(free_players)):
        raise ValueError("Количество лобби превышает количество игроков")
    if len(queued_players) >= 10:
        raise ValueError("Количество игроков в очереди превышает 10.")

    lobbies = []
    for _ in range(lobby_count):
        lobby = {
            "team1": {"tank": None, "damage": [], "support": []},
            "team2": {"tank": None, "damage": [], "support": []}
        }

        tanks, free_players, queued_players = find_closest_tanks(free_players, queued_players)
        damage, free_players, queued_players = find_closest_damage(free_players, queued_players)
        support, free_players, queued_players = find_closest_support(free_players, queued_players)

        # распределение по командам

        lobby["team1"]["tank"], lobby["team2"]["tank"] = tanks[0], tanks[1]
        lobby["team1"]["damage"].append(damage[0]); lobby["team2"]["damage"].append(damage[1])
        lobby["team1"]["damage"].append(damage[2]); lobby["team2"]["damage"].append(damage[3])
        lobby["team1"]["support"].append(support[0]); lobby["team2"]["support"].append(support[1])
        lobby["team1"]["support"].append(support[2]); lobby["team2"]["support"].append(support[3])

        if check_lobby_status(lobby):
            lobbies.append(lobby)
            update_history_with_lobby(lobby)

    return lobbies, free_players