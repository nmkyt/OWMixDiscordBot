from config import session
from models import Player
import random

free_players = session.query(Player).filter(Player.check_in == 'yes').all()
random.shuffle(free_players)


def balancer(lobby, phase):
    global free_players
    # Проверка баланса команд по рейтингу
    team1_rating = sum(player.tank_rating for player in [lobby["team1"]["tank"]] if player) + \
                   sum(player.damage_rating for player in lobby["team1"]["damage"]) + \
                   sum(player.support_rating for player in lobby["team1"]["support"])

    team2_rating = sum(player.tank_rating for player in [lobby["team2"]["tank"]] if player) + \
                   sum(player.damage_rating for player in lobby["team2"]["damage"]) + \
                   sum(player.support_rating for player in lobby["team2"]["support"])
    tank1_rating = sum(player.tank_rating for player in [lobby["team1"]["tank"]] if player)
    tank2_rating = sum(player.tank_rating for player in [lobby["team2"]["tank"]] if player)

    if phase == 1:
        if (abs(team1_rating - team2_rating) <= 400) and (abs(tank1_rating - tank2_rating) <= 300):
            return True
        elif abs(tank1_rating - tank2_rating) > 400:
            for player in free_players:
                if player.priority_role == 'tank':
                    if tank1_rating > tank2_rating:
                        free_players.remove(player)
                        free_players.append(lobby["team1"]["tank"])
                        lobby["team1"]["tank"] = player
                        return False
                    else:
                        free_players.remove(player)
                        free_players.append(lobby["team2"]["tank"])
                        lobby["team2"]["tank"] = player
                        return False
        elif abs(team1_rating - team2_rating) > 300:
            for player in free_players:
                if player.priority_role == "damage":
                    if team1_rating > team2_rating:
                        free_players.remove(player)
                        free_players.append(lobby["team1"]["damage"][0])
                        lobby["team1"]["damage"][0] = lobby["team1"]["damage"][1]
                        lobby["team1"]["damage"].pop(1)
                        lobby["team1"]["damage"].append(player)
                        return False
                    else:
                        free_players.remove(player)
                        free_players.append(lobby["team2"]["damage"][0])
                        lobby["team2"]["damage"][0] = lobby["team1"]["damage"][1]
                        lobby["team2"]["damage"].pop(1)
                        lobby["team2"]["damage"].append(player)
                        return False
                elif player.priority_role == "support":
                    if team1_rating > team2_rating:
                        free_players.remove(player)
                        free_players.append(lobby["team1"]["support"][0])
                        lobby["team1"]["support"][0] = lobby["team1"]["support"][1]
                        lobby["team1"]["support"].pop(1)
                        lobby["team1"]["support"].append(player)
                        return False
                    else:
                        free_players.remove(player)
                        free_players.append(lobby["team2"]["support"][0])
                        lobby["team1"]["support"][0] = lobby["team1"]["support"][1]
                        lobby["team1"]["support"].pop(1)
                        lobby["team1"]["support"].append(player)
                        return False
    if phase == 2:
        if (abs(team1_rating - team2_rating) <= 400) and (abs(tank1_rating - tank2_rating) <= 400):
            return True
        elif abs(tank1_rating - tank2_rating) > 400:
            for player in free_players:
                if player.tank_rating is not None:
                    if tank1_rating > tank2_rating:
                        free_players.remove(player)
                        free_players.append(lobby["team1"]["tank"])
                        lobby["team1"]["tank"] = player
                        return False
                    else:
                        free_players.remove(player)
                        free_players.append(lobby["team2"]["tank"])
                        lobby["team2"]["tank"] = player
                        return False
        elif abs(team1_rating - team2_rating) > 300:
            for player in free_players:
                if player.damage_rating is not None:
                    if team1_rating > team2_rating:
                        free_players.remove(player)
                        free_players.append(lobby["team1"]["damage"][0])
                        lobby["team1"]["damage"][0] = lobby["team1"]["damage"][1]
                        lobby["team1"]["damage"].pop(1)
                        lobby["team1"]["damage"].append(player)
                        return False
                    else:
                        free_players.remove(player)
                        free_players.append(lobby["team2"]["damage"][0])
                        lobby["team2"]["damage"][0] = lobby["team1"]["damage"][1]
                        lobby["team2"]["damage"].pop(1)
                        lobby["team2"]["damage"].append(player)
                        return False
                elif player.support_rating is not None:
                    if team1_rating > team2_rating:
                        free_players.remove(player)
                        free_players.append(lobby["team1"]["support"][0])
                        lobby["team1"]["support"][0] = lobby["team1"]["support"][1]
                        lobby["team1"]["support"].pop(1)
                        lobby["team1"]["support"].append(player)
                        return False
                    else:
                        free_players.remove(player)
                        free_players.append(lobby["team2"]["support"][0])
                        lobby["team1"]["support"][0] = lobby["team1"]["support"][1]
                        lobby["team1"]["support"].pop(1)
                        lobby["team1"]["support"].append(player)
                        return False


def fill_teams(fill_parameter, normal_iterations):
    global free_players
    player_count = 0
    iterations = 0
    lobby = {
        "team1": {"tank": None, "damage": [], "support": []},
        "team2": {"tank": None, "damage": [], "support": []}
    }
    while player_count < 10:
        if fill_parameter == 'priority_role' and iterations <= normal_iterations:
            player = free_players[:1]
            free_players = free_players[1:]
            role = player[0].priority_role
            assigned = False
            if role == "tank":
                if lobby["team1"]["tank"] is None:
                    lobby["team1"]["tank"] = player[0]
                    assigned = True
                    player_count += 1
                elif lobby["team2"]["tank"] is None:
                    lobby["team2"]["tank"] = player[0]
                    assigned = True
                    player_count += 1
            elif role == "damage":
                if len(lobby["team1"]["damage"]) < 2:
                    lobby["team1"]["damage"].append(player[0])
                    assigned = True
                    player_count += 1
                elif len(lobby["team2"]["damage"]) < 2:
                    lobby["team2"]["damage"].append(player[0])
                    assigned = True
                    player_count += 1
            elif role == "support":
                if len(lobby["team1"]["support"]) < 2:
                    lobby["team1"]["support"].append(player[0])
                    assigned = True
                    player_count += 1
                elif len(lobby["team2"]["support"]) < 2:
                    lobby["team2"]["support"].append(player[0])
                    assigned = True
                    player_count += 1
            if not assigned:
                free_players.append(player[0])
        if iterations > normal_iterations * 3:
            raise ValueError("Not enough players to fill teams")
        if fill_parameter == 'non-priority_role' or iterations > normal_iterations:
            for player in free_players:
                if player.tank_rating is not None:
                    if lobby["team1"]["tank"] is None:
                        lobby["team1"]["tank"] = player
                        player_count += 1
                        free_players.remove(player)
                    elif lobby["team2"]["tank"] is None:
                        lobby["team2"]["tank"] = player
                        player_count += 1
                        free_players.remove(player)
                elif player.damage_rating is not None:
                    if len(lobby["team1"]["damage"]) < 2:
                        lobby["team1"]["damage"].append(player)
                        player_count += 1
                        free_players.remove(player)
                    elif len(lobby["team2"]["damage"]) < 2:
                        lobby["team2"]["damage"].append(player)
                        player_count += 1
                        free_players.remove(player)
                elif player.support_rating is not None:
                    if len(lobby["team1"]["support"]) < 2:
                        lobby["team1"]["support"].append(player)
                        player_count += 1
                        free_players.remove(player)
                    elif len(lobby["team2"]["support"]) < 2:
                        lobby["team2"]["support"].append(player)
                        player_count += 1
                        free_players.remove(player)
        iterations += 1
    return lobby


def create_lobby(lobby_count):
    lobbies = []
    if len(free_players) >= 10 * lobby_count:
        trigger = False
        count = 0
        normal_iterations = len(free_players)
        fill_parameter = 'priority_role'
        while count < lobby_count:
            iterations = 0
            teams = fill_teams(fill_parameter, normal_iterations)
            balance = False
            while balance is False:
                iterations += 1
                if iterations < normal_iterations and trigger is False:
                    balance = balancer(teams, 1)
                if iterations >= normal_iterations and trigger is False:
                    balance = balancer(teams, 2)
                if iterations > normal_iterations * 3 and trigger is False:
                    for player in teams:
                        free_players.append(player)
                    fill_parameter = 'non-priority_role'
                    count = 0
                    trigger = True
                    balance = True
                if trigger is True:
                    balance = balancer(teams, 2)
                if iterations > normal_iterations * 3 and trigger is True:
                    raise ValueError("Balance not found.")
                if balance is True:
                    lobbies.append(teams)
                    count += 1
    else:
        raise ValueError("Not enough players.")
    for i, lobby in enumerate(lobbies):
        print(f"Lobby {i + 1}:")
        print("Team 1:", [player.name for player in
                          [lobby["team1"]["tank"]] + lobby["team1"]["damage"] + lobby["team1"]["support"]])
        print("Team 2:", [player.name for player in
                          [lobby["team2"]["tank"]] + lobby["team2"]["damage"] + lobby["team2"]["support"]])


try:
    create_lobby(2)
except ValueError as e:
    print(f"Error: {e}")
