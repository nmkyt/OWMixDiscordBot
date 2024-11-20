from src.config import session
from src.models import Player, Queue
import random


def get_players():
    free_players = session.query(Player).filter(Player.check_in == 'yes').all()
    random.shuffle(free_players)
    return free_players


def get_queue():
    queued_players = session.query(Queue).all()
    free_players = get_players()
    queue = []
    for player_queue in queued_players:
        for player_free in free_players:
            if player_queue.discord_id == player_free.discord_id:
                queue.append(player_free)
    return queue


def find_closest_tanks(free_players, queued_players):
    """
    Находит двух ближайших игроков на роли 'Танк', включая queued_players.
    """
    tanks = [p for p in free_players if p.priority_role == "tank"]
    selected = []

    # Добавляем игроков из очереди, если они есть
    queued_tanks = [p for p in queued_players if p.priority_role == "tank"]
    selected.extend(queued_tanks)

    if len(tanks) + len(selected) < 2:
        raise ValueError("Недостаточно игроков на роли Танк")

    # Заполняем оставшиеся места методом перебора
    min_difference = float('inf')
    closest_pair = None
    for i in range(len(tanks)):
        for j in range(i + 1, len(tanks)):
            if tanks[i] in selected or tanks[j] in selected:
                continue
            diff = abs(tanks[i].tank_rating - tanks[j].tank_rating)
            if diff < min_difference:
                min_difference = diff
                closest_pair = [tanks[i], tanks[j]]

    selected.extend(closest_pair[: 2 - len(selected)])
    return selected


def find_closest_damage(free_players, queued_players):
    """
    Находит четырех ближайших игроков на роли 'Урон', включая queued_players.
    """
    damage = [p for p in free_players if p.priority_role == "damage"]
    selected = []

    # Добавляем игроков из очереди
    queued_damage = [p for p in queued_players if p.priority_role == "damage"]
    selected.extend(queued_damage)

    if len(damage) + len(selected) < 4:
        raise ValueError("Недостаточно игроков на роли Урон")

    # Заполняем оставшиеся места
    remaining = [p for p in damage if p not in selected]
    while len(selected) < 4:
        closest = None
        min_difference = float('inf')
        for i, player in enumerate(remaining):
            diff = sum(abs(player.damage_rating - sel.damage_rating) for sel in selected)
            if diff < min_difference:
                min_difference = diff
                closest = i

        selected.append(remaining.pop(closest))

    return selected


def find_closest_support(players, queued_players):
    """
    Находит четырех ближайших игроков на роли 'Поддержка', включая queued_players.
    """
    support = [p for p in players if p.priority_role == "support"]
    selected = []

    # Добавляем игроков из очереди
    queued_support = [p for p in queued_players if p.priority_role == "support"]
    selected.extend(queued_support)

    if len(support) + len(selected) < 4:
        raise ValueError("Недостаточно игроков на роли Поддержка")

    # Заполняем оставшиеся места
    remaining = [p for p in support if p not in selected]
    while len(selected) < 4:
        closest = None
        min_difference = float('inf')
        for i, player in enumerate(remaining):
            diff = sum(abs(player.support_rating - sel.support_rating) for sel in selected)
            if diff < min_difference:
                min_difference = diff
                closest = i

        selected.append(remaining.pop(closest))

    return selected


def print_lobby(lobby):
    print('TEAM 1 TANK:')
    print(lobby['team1']['tank'].name)
    print('TEAM 1 DPSES:')
    for player in lobby['team1']['damage']:
        print(player.name)
    print('TEAM 1 SUPPORTS:')
    for player in lobby['team1']['support']:
        print(player.name)
    print('TEAM 2 TANK:')
    print(lobby['team2']['tank'].name)
    print('TEAM 2 DPSES:')
    for player in lobby['team2']['damage']:
        print(player.name)
    print('TEAM 2 SUPPORTS:')
    for player in lobby['team2']['support']:
        print(player.name)


def check_lobby_status(lobby):
    if lobby['team1']['tank'] is None:
        return False
    for player in lobby['team1']['damage']:
        if player is None:
            return False
    for player in lobby['team1']['support']:
        if player is None:
            return False
    if lobby['team2']['tank'] is None:
        return False
    for player in lobby['team2']['damage']:
        if player is None:
            return False
    for player in lobby['team2']['support']:
        if player is None:
            return False
    return True


def check_player_status(client, lobby):
    if client == lobby['team1']['tank']:
        return True
    for player in lobby['team1']['damage']:
        if client == player:
            return True
    for player in lobby['team1']['support']:
        if client == player:
            return True
    if client == lobby['team2']['tank']:
        return True
    for player in lobby['team2']['damage']:
        if client == player:
            return True
    for player in lobby['team2']['support']:
        if client == player:
            return True
    return False


def select_current_lobby(lobby, free_players, queued_players):
    free_players.remove(lobby['team1']['tank'])
    for player in lobby['team1']['damage']:
        if player in free_players:
            free_players.remove(player)
        if player in queued_players:
            queued_players.remove(player)
    for player in lobby['team1']['support']:
        if player in free_players:
            free_players.remove(player)
        if player in queued_players:
            queued_players.remove(player)
    free_players.remove(lobby['team2']['tank'])
    for player in lobby['team2']['damage']:
        if player in free_players:
            free_players.remove(player)
        if player in queued_players:
            queued_players.remove(player)
    for player in lobby['team2']['support']:
        if player in free_players:
            free_players.remove(player)
        if player in queued_players:
            queued_players.remove(player)
    return free_players, queued_players


def create_lobbies(lobby_count):
    free_players = get_players()
    queued_players = get_queue()
    for player in queued_players:
        free_players.remove(player)
    lobbies = []
    for i in range(lobby_count):
        lobby = {
            "team1": {"tank": None, "damage": [], "support": []},
            "team2": {"tank": None, "damage": [], "support": []}
        }
        tanks = find_closest_tanks(free_players, queued_players)
        damage = find_closest_damage(free_players, queued_players)
        support = find_closest_support(free_players, queued_players)
        lobby["team1"]["tank"], lobby["team2"]["tank"] = tanks[0], tanks[1]
        lobby["team1"]["damage"].append(damage[0]), lobby["team2"]["damage"].append(damage[1])
        lobby["team1"]["damage"].append(damage[2]), lobby["team2"]["damage"].append(damage[3])
        lobby["team1"]["support"].append(support[0]), lobby["team2"]["support"].append(support[1])
        lobby["team1"]["support"].append(support[2]), lobby["team2"]["support"].append(support[3])
        if check_lobby_status(lobby):
            print_lobby(lobby)
            free_players, queued_players = select_current_lobby(lobby, free_players, queued_players)
            lobbies.append(lobby)
    return lobbies, free_players


create_lobbies(4)