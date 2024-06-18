from config import session
from models import Player


def get_sorted_players():
    players = session.query(Player).all()

    tanks = sorted([p for p in players if p.tank_rating is not None], key=lambda x: x.tank_rating, reverse=True)
    damages = sorted([p for p in players if p.damage_rating is not None], key=lambda x: x.damage_rating, reverse=True)
    supports = sorted([p for p in players if p.support_rating is not None], key=lambda x: x.support_rating, reverse=True)

    return tanks, damages, supports


def distribute_lobbies(num_lobbies):
    tanks, damages, supports = get_sorted_players()

    if len(tanks) < num_lobbies or len(damages) < num_lobbies * 2 or len(supports) < num_lobbies * 2:
        raise ValueError("Not enough players to fill the requested number of lobbies.")

    lobbies = [[] for _ in range(num_lobbies)]
    total_ratings = [{'tank': 0, 'damage': 0, 'support': 0} for _ in range(num_lobbies)]

    for i in range(num_lobbies):
        # Добавляем 1 танка в лобби
        best_tank = min(tanks, key=lambda x: sum(abs(total_ratings[i]['tank'] - x.tank_rating) for i in range(num_lobbies)))
        tanks.remove(best_tank)
        lobbies[i].append(best_tank)
        total_ratings[i]['tank'] += best_tank.tank_rating

        # Добавляем 2 дамагеров в лобби
        for _ in range(2):
            best_damage = min(damages, key=lambda x: sum(abs(total_ratings[i]['damage'] - x.damage_rating) for i in range(num_lobbies)))
            damages.remove(best_damage)
            lobbies[i].append(best_damage)
            total_ratings[i]['damage'] += best_damage.damage_rating

        # Добавляем 2 саппортов в лобби
        for _ in range(2):
            best_support = min(supports, key=lambda x: sum(abs(total_ratings[i]['support'] - x.support_rating) for i in range(num_lobbies)))
            supports.remove(best_support)
            lobbies[i].append(best_support)
            total_ratings[i]['support'] += best_support.support_rating

    # Проверяем уникальность игроков в лобби
    player_names = set()
    for lobby in lobbies:
        for player in lobby:
            if player.name in player_names:
                raise ValueError("Duplicate player found in different lobbies.")
            player_names.add(player.name)

    return lobbies


# Пример вызова функции распределения
try:
    lobbies = distribute_lobbies(2)
    for i, lobby in enumerate(lobbies):
        print(f"Lobby {i + 1}: {[player.name for player in lobby]}")
except ValueError as e:
    print(f"Error: {e}")
