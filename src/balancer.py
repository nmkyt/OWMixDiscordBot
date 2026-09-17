from src.config import session
from src.models import Player, Queue
import random, json, os, logging
from itertools import combinations

logger = logging.getLogger(__name__)

# data/, а не src/ — это рантайм-состояние (история миксов), а не исходный код.
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
HISTORY_FILE = os.path.join(DATA_DIR, "recent_pairs.json")
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
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            RECENT_PAIRS = data.get("pairs", {})
            GAME_INDEX = int(data.get("game_index", 0))
        except Exception as e:
            logger.warning(f'Failed to load history file, starting fresh: {e}')
            RECENT_PAIRS, GAME_INDEX = {}, 0
    else:
        RECENT_PAIRS, GAME_INDEX = {}, 0


def save_history():
    """Анти-повтор — вспомогательная функция; сбой записи файла истории (диск, права
    доступа, антивирус и т.п.) не должен мешать созданию лобби, поэтому не пробрасываем
    исключение наружу, только логируем."""
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump({"pairs": RECENT_PAIRS, "game_index": GAME_INDEX}, f, ensure_ascii=False)
    except OSError as e:
        logger.error(f'Failed to save history file: {e}')


def reset_history():
    """
    Полностью очищает историю анти-повтора — вызывается в конце вечера миксов (!mix_stop).
    Без этого штрафы за повторы "утекали" бы между разными вечерами: например, если два
    игрока сыграли вместе в последнем матче прошлого раза, балансировщик считал бы их
    недавними тиммейтами и в первом матче следующего вечера, хотя между вечерами прошли дни.
    """
    global RECENT_PAIRS, GAME_INDEX
    RECENT_PAIRS = {}
    GAME_INDEX = 0
    save_history()


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


def _group_penalty(a, b):
    """Суммарный штраф за пару без знания, окажутся ли они тиммейтами или соперниками —
    используется на этапе отбора состава лобби, когда команды ещё не разделены."""
    return ALPHA_TEAMMATE * pair_penalty(a, b, as_mates=True) + ALPHA_OPPONENT * pair_penalty(a, b, as_mates=False)


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
    """ Находит двух ближайших игроков на роли 'Танк', включая queued_players (не более 2). """
    # rating is not None — доп. защита от рассинхрона данных (приоритетная роль выбрана,
    # а рейтинг на ней не указан): без неё abs(None - x) уронит подбор лобби.
    tanks = [p for p in free_players if p.priority_role in ("tank", "flex") and p.tank_rating is not None]
    queued_tanks = [p for p in queued_players
                    if p.priority_role in ("tank", "flex") and p.tank_rating is not None][:2]
    selected = list(queued_tanks)

    if len(tanks) + len(selected) < 2:
        tanks = [p for p in free_players if p.tank_rating is not None]
    if len(tanks) + len(selected) < 2:
        raise ValueError("Недостаточно игроков на роли Танк")

    cand = [p for p in tanks if p not in selected]
    needed = 2 - len(selected)

    if needed == 2:
        best_pair, min_cost = None, float('inf')
        for i in range(len(cand)):
            for j in range(i + 1, len(cand)):
                a, b = cand[i], cand[j]
                diff = abs(a.tank_rating - b.tank_rating)
                cost = diff + _group_penalty(a, b)
                if cost < min_cost:
                    min_cost, best_pair = cost, (a, b)
        if best_pair is None:
            raise ValueError("Недостаточно игроков на роли Танк для формирования пары")
        selected.extend(best_pair)
    elif needed == 1:
        best, min_cost = None, float('inf')
        for p in cand:
            diff = abs(p.tank_rating - selected[0].tank_rating)
            cost = diff + _group_penalty(p, selected[0])
            if cost < min_cost:
                min_cost, best = cost, p
        if best is None:
            raise ValueError("Недостаточно игроков на роли Танк для пары")
        selected.append(best)

    for player in list(selected):
        if player in free_players:
            free_players.remove(player)
        if player in queued_players:
            queued_players.remove(player)
    return selected, free_players, queued_players


def _greedy_pick_with_penalties(role_players, selected, rating_attr, extra_penalty_against=()):
    """
    Добирает следующего игрока, минимизируя:
        sum |rating(candidate) - rating(sel)| + ALPHA*(штрафы за недавние пары)
    Штраф за повтор считается не только против уже выбранных на эту же роль (selected),
    но и против игроков, уже закреплённых в этом лобби на других ролях (extra_penalty_against) —
    иначе повтор состава ловится только внутри одной роли и не ловится, например,
    между танком и саппортом, которые недавно играли вместе.
    """
    penalty_pool = list(selected) + list(extra_penalty_against)
    best_idx, best_cost = None, float('inf')
    for i, candidate in enumerate(role_players):
        diff_sum = sum(abs(getattr(candidate, rating_attr) - getattr(s, rating_attr)) for s in selected)
        pen_sum = sum(_group_penalty(candidate, s) for s in penalty_pool)
        cost = diff_sum + pen_sum
        if cost < best_cost:
            best_cost, best_idx = cost, i
    return best_idx


def find_closest_damage(free_players, queued_players, lobby_so_far=()):
    """ Находит четырех ближайших игроков на роли 'Урон', включая queued_players (не более 4), c анти-повторами. """
    damage = [p for p in free_players if p.priority_role in ("damage", "flex") and p.damage_rating is not None]
    queued_damage = [p for p in queued_players
                      if p.priority_role in ("damage", "flex") and p.damage_rating is not None][:4]
    selected = list(queued_damage)

    if len(damage) + len(selected) < 4:
        damage = [p for p in free_players if p.damage_rating is not None]
    if len(damage) + len(selected) < 4:
        raise ValueError("Недостаточно игроков на роли Урон")

    remaining = [p for p in damage if p not in selected]
    while len(selected) < 4:
        idx = _greedy_pick_with_penalties(remaining, selected, "damage_rating", lobby_so_far)
        if idx is None:
            raise ValueError("Недостаточно игроков на роли Урон")
        selected.append(remaining.pop(idx))

    for player in list(selected):
        if player in free_players:
            free_players.remove(player)
        if player in queued_players:
            queued_players.remove(player)
    return selected, free_players, queued_players


def find_closest_support(free_players, queued_players, lobby_so_far=()):
    """ Находит четырех ближайших игроков на роли 'Поддержка', включая queued_players (не более 4), c анти-повторами. """
    support = [p for p in free_players if p.priority_role in ("support", "flex") and p.support_rating is not None]
    queued_support = [p for p in queued_players
                       if p.priority_role in ("support", "flex") and p.support_rating is not None][:4]
    selected = list(queued_support)

    if len(support) + len(selected) < 4:
        support = [p for p in free_players if p.support_rating is not None]
    if len(support) + len(selected) < 4:
        raise ValueError("Недостаточно игроков на роли Поддержка")

    remaining = [p for p in support if p not in selected]
    while len(selected) < 4:
        idx = _greedy_pick_with_penalties(remaining, selected, "support_rating", lobby_so_far)
        if idx is None:
            raise ValueError("Недостаточно игроков на роли Поддержка")
        selected.append(remaining.pop(idx))

    for player in list(selected):
        if player in free_players:
            free_players.remove(player)
        if player in queued_players:
            queued_players.remove(player)
    return selected, free_players, queued_players


ROLE_NEEDS = {'tank': 2, 'damage': 4, 'support': 4}
RATING_ATTR = {'tank': 'tank_rating', 'damage': 'damage_rating', 'support': 'support_rating'}


def _kuhn_match(num_left, adj):
    """
    Паросочетание Кула: num_left левых узлов (0..num_left-1), adj[i] — список допустимых
    правых узлов для i. Возвращает {left: right} для максимального паросочетания.
    Гарантированно находит полное паросочетание, если оно существует (в отличие от
    жадного перебора) — на этом и строится гарантия сборки лобби.
    """
    match_right = {}

    def try_assign(left, visited):
        for right in adj[left]:
            if right in visited:
                continue
            visited.add(right)
            if right not in match_right or try_assign(match_right[right], visited):
                match_right[right] = left
                return True
        return False

    for left in range(num_left):
        try_assign(left, set())

    return {left: right for right, left in match_right.items()}


def _match_roles(candidates, role_needs, eligible_fn):
    """
    candidates: список Player. role_needs: {role: сколько мест осталось}.
    eligible_fn(player, role) -> bool.
    Возвращает {role: [Player,...]}, если удалось заполнить ВСЕ запрошенные места, иначе None.
    """
    slots = []
    for role, need in role_needs.items():
        slots.extend([role] * need)
    if not slots:
        return {role: [] for role in role_needs}

    adj = [[i for i, p in enumerate(candidates) if eligible_fn(p, role)] for role in slots]
    matching = _kuhn_match(len(slots), adj)
    if len(matching) != len(slots):
        return None

    result = {role: [] for role in role_needs}
    for slot_idx, cand_idx in matching.items():
        result[slots[slot_idx]].append(candidates[cand_idx])
    return result


def _guaranteed_lobby(free_players, queued_players):
    """
    Резервный способ собрать состав лобби, когда жадный find_closest_* не справился.
    Жадный алгоритм может "по ошибке" забрать на роль с избытком кандидатов игрока,
    который был единственным, кто мог закрыть дефицитную роль (например, игрок с рейтингом
    и на танке, и на саппорте уходит в танки, хотя без него не набрать саппортов).
    Эта функция не оптимизирует близость рейтингов — зато гарантированно находит рабочий
    состав, если он математически существует (паросочетание Кула), сначала пробуя уважать
    приоритетные роли игроков, и только если это невозможно — используя любой рейтинг.
    """
    remaining_free = list(free_players)
    remaining_queued = list(queued_players)
    assigned = {'tank': [], 'damage': [], 'support': []}

    # Игроки из очереди обязаны сыграть — каждый на своей приоритетной роли (flex — туда,
    # где сейчас не хватает мест сильнее всего). Роль уже занята другими queued — остаются
    # в очереди для следующего вызова, а не теряются.
    for player in list(remaining_queued):
        role = player.priority_role
        if role == 'flex':
            role = min(ROLE_NEEDS, key=lambda r: len(assigned[r]) - ROLE_NEEDS[r])
        if (role in ROLE_NEEDS and len(assigned[role]) < ROLE_NEEDS[role]
                and getattr(player, RATING_ATTR.get(role, ''), None) is not None):
            assigned[role].append(player)
            remaining_queued.remove(player)

    needs = {r: ROLE_NEEDS[r] - len(assigned[r]) for r in ROLE_NEEDS}
    candidates = [p for p in remaining_free
                  if any(needs[r] > 0 and getattr(p, RATING_ATTR[r], None) is not None for r in ROLE_NEEDS)]

    def priority_eligible(p, role):
        return p.priority_role in (role, 'flex') and getattr(p, RATING_ATTR[role]) is not None

    def fallback_eligible(p, role):
        return getattr(p, RATING_ATTR[role]) is not None

    match = _match_roles(candidates, needs, priority_eligible) or _match_roles(candidates, needs, fallback_eligible)
    if match is None:
        raise ValueError("Недостаточно игроков для полного состава лобби")

    for role, players in match.items():
        assigned[role].extend(players)
        for p in players:
            remaining_free.remove(p)

    return assigned['tank'], assigned['damage'], assigned['support'], remaining_free, remaining_queued


def _split_teams(tank_a, tank_b, damage_four, support_four):
    """
    Перебирает все варианты распределения уже отобранных 10 игроков по двум командам
    (2 танка фиксированы по одному на команду, 4 урона и 4 саппорта делятся 2+2 всеми
    возможными способами — итого 36 вариантов) и выбирает тот, где минимальна сумма:
        |рейтинг_команда1 - рейтинг_команда2| + штраф за повтор состава.
    """
    best_teams, best_cost = None, float('inf')
    for d1 in combinations(damage_four, 2):
        d2 = [p for p in damage_four if p not in d1]
        for s1 in combinations(support_four, 2):
            s2 = [p for p in support_four if p not in s1]

            team1 = {"tank": tank_a, "damage": list(d1), "support": list(s1)}
            team2 = {"tank": tank_b, "damage": d2, "support": s2}

            total1 = tank_a.tank_rating + sum(p.damage_rating for p in team1["damage"]) + sum(p.support_rating for p in team1["support"])
            total2 = tank_b.tank_rating + sum(p.damage_rating for p in team2["damage"]) + sum(p.support_rating for p in team2["support"])
            rating_cost = abs(total1 - total2)

            members1 = [team1["tank"]] + team1["damage"] + team1["support"]
            members2 = [team2["tank"]] + team2["damage"] + team2["support"]

            mates_penalty = sum(pair_penalty(a, b, as_mates=True)
                                 for members in (members1, members2)
                                 for a, b in combinations(members, 2))
            foes_penalty = sum(pair_penalty(a, b, as_mates=False)
                                for a in members1 for b in members2)

            cost = rating_cost + ALPHA_TEAMMATE * mates_penalty + ALPHA_OPPONENT * foes_penalty
            if cost < best_cost:
                best_cost, best_teams = cost, (team1, team2)

    return best_teams


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
        try:
            # основной путь: жадный подбор близких по рейтингу игроков с анти-повтором.
            # Работает на копиях списков — при неудаче ничего не потребляет из оригиналов,
            # чтобы резервный вариант ниже мог использовать полный, нетронутый пул игроков.
            free_copy, queued_copy = list(free_players), list(queued_players)
            tanks, free_copy, queued_copy = find_closest_tanks(free_copy, queued_copy)
            damage, free_copy, queued_copy = find_closest_damage(free_copy, queued_copy, lobby_so_far=tanks)
            support, free_copy, queued_copy = find_closest_support(free_copy, queued_copy, lobby_so_far=tanks + damage)
            free_players, queued_players = free_copy, queued_copy
        except ValueError:
            # жадный подбор не нашёл состав — не значит, что его не существует (см. docstring
            # _guaranteed_lobby). Пробуем гарантированный резервный вариант на полном пуле.
            tanks, damage, support, free_players, queued_players = _guaranteed_lobby(free_players, queued_players)

        team1, team2 = _split_teams(tanks[0], tanks[1], damage, support)
        lobby = {"team1": team1, "team2": team2}

        lobbies.append(lobby)
        update_history_with_lobby(lobby)

    # игроки из очереди, не поместившиеся ни в одно из lobby_count лобби в этом вызове,
    # обязаны попасть в следующий вызов !create_lobby первыми
    return lobbies, free_players + queued_players
