from config import session
from models import Player, Queue
import random


def get_players():
    free_players = session.query(Player).filter(Player.check_in == 'yes').all()
    random.shuffle(free_players)
    return free_players


def sort_players(player, elo):
    if player.tank_rating is not None:
        if player.tank_rating >= 3800:
            elo['tank']['high'].append(player)
        if 3000 <= player.tank_rating < 3800:
            elo['tank']['mid'].append(player)
        if player.tank_rating < 3000:
            elo['tank']['low'].append(player)
    if player.damage_rating is not None:
        if player.damage_rating >= 3800:
            elo['damage']['high'].append(player)
        if 3000 <= player.damage_rating < 3800:
            elo['damage']['mid'].append(player)
        if player.damage_rating < 3000:
            elo['damage']['low'].append(player)
    if player.support_rating is not None:
        if player.support_rating >= 3800:
            elo['support']['high'].append(player)
        if 3000 <= player.support_rating < 3800:
            elo['support']['mid'].append(player)
        if player.support_rating < 3000:
            elo['support']['low'].append(player)


def elo_cleaner():
    elo = {
        'tank': {"high": [], "mid": [], "low": []},
        'damage': {"high": [], "mid": [], "low": []},
        'support': {"high": [], "mid": [], "low": []},
    }
    return elo


def sum_rating(lobby):
    team1_rating = sum(player.tank_rating for player in [lobby["team1"]["tank"]] if player) + \
                   sum(player.damage_rating for player in lobby["team1"]["damage"]) + \
                   sum(player.support_rating for player in lobby["team1"]["support"])
    team2_rating = sum(player.tank_rating for player in [lobby["team2"]["tank"]] if player) + \
                   sum(player.damage_rating for player in lobby["team2"]["damage"]) + \
                   sum(player.support_rating for player in lobby["team2"]["support"])
    tank1_rating = sum(player.tank_rating for player in [lobby["team1"]["tank"]] if player)
    tank2_rating = sum(player.tank_rating for player in [lobby["team2"]["tank"]] if player)
    return team1_rating, team2_rating, tank1_rating, tank2_rating


def fill_players_soft(free_players):
    players = 0
    lobby = {
        "team1": {"tank": None, "damage": [], "support": []},
        "team2": {"tank": None, "damage": [], "support": []}
    }
    for player in free_players:
        role = player.priority_role
        if role == 'tank':
            if lobby["team1"]["tank"] is None:
                if check_player_status(player, lobby) is False:
                    lobby["team1"]["tank"] = player
                    players += 1
            elif lobby["team2"]["tank"] is None:
                if check_player_status(player, lobby) is False:
                    lobby["team2"]["tank"] = player
                    players += 1
        if role == 'damage':
            if len(lobby["team1"]["damage"]) < 2:
                if check_player_status(player, lobby) is False:
                    lobby["team1"]["damage"].append(player)
                    players += 1
            elif len(lobby["team2"]["damage"]) < 2:
                if check_player_status(player, lobby) is False:
                    lobby["team2"]["damage"].append(player)
                    players += 1
        if role == 'support':
            if len(lobby["team1"]["support"]) < 2:
                if check_player_status(player, lobby) is False:
                    lobby["team1"]["support"].append(player)
                    players += 1
            elif len(lobby["team2"]["support"]) < 2:
                if check_player_status(player, lobby) is False:
                    lobby["team2"]["support"].append(player)
                    players += 1
        if players == 10:
            return lobby
    return False


def fill_players_hard(free_players):
    lobby = {
        "team1": {"tank": None, "damage": [], "support": []},
        "team2": {"tank": None, "damage": [], "support": []}
    }
    players = 0
    for player in free_players:
        if player.tank_rating is not None:
            if lobby["team1"]["tank"] is None:
                if check_player_status(player, lobby) is False:
                    lobby["team1"]["tank"] = player
                    players += 1
            elif lobby["team2"]["tank"] is None:
                if check_player_status(player, lobby) is False:
                    lobby["team2"]["tank"] = player
                    players += 1
        if player.damage_rating is not None:
            if len(lobby["team1"]["damage"]) < 2:
                if check_player_status(player, lobby) is False:
                    lobby["team1"]["damage"].append(player)
                    players += 1
            elif len(lobby["team2"]["damage"]) < 2:
                if check_player_status(player, lobby) is False:
                    lobby["team2"]["damage"].append(player)
                    players += 1
        if player.support_rating is not None:
            if len(lobby["team1"]["support"]) < 2:
                if check_player_status(player, lobby) is False:
                    lobby["team1"]["support"].append(player)
                    players += 1
            elif len(lobby["team2"]["support"]) < 2:
                if check_player_status(player, lobby) is False:
                    lobby["team2"]["support"].append(player)
                    players += 1
        if players == 10:
            return lobby
    return False


def free_current_lobby(lobby, free_players):
    free_players.append(lobby['team1']['tank'])
    for player in lobby['team1']['damage']:
        free_players.append(player)
    for player in lobby['team1']['support']:
        free_players.append(player)
    free_players.append(lobby['team2']['tank'])
    for player in lobby['team2']['damage']:
        free_players.append(player)
    for player in lobby['team2']['support']:
        free_players.append(player)


def select_current_lobby(lobby, free_players):
    free_players.remove(lobby['team1']['tank'])
    for player in lobby['team1']['damage']:
        free_players.remove(player)
    for player in lobby['team1']['support']:
        free_players.remove(player)
    free_players.remove(lobby['team2']['tank'])
    for player in lobby['team2']['damage']:
        free_players.remove(player)
    for player in lobby['team2']['support']:
        free_players.remove(player)


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


def soft_balance(lobby, free_players, elo):
    team1_rating, team2_rating, tank1_rating, tank2_rating = sum_rating(lobby)
    if (abs(team1_rating - team2_rating) <= 300) and (abs(tank1_rating - tank2_rating) <= 300):
        return True
    else:
        if abs(tank1_rating - tank2_rating) > 300:
            for player in free_players:
                if player.priority_role == 'tank':
                    if tank1_rating > tank2_rating:
                        if player in elo['tank']['high']:
                            if lobby['team1']['tank'] in elo['tank']['high']:
                                if check_player_status(player, lobby) is False:
                                    lobby['team2']['tank'] = player
                        if check_player_status(player, lobby) is False:
                            lobby['team1']['tank'] = player
                    else:
                        if player in elo['tank']['high']:
                            if lobby['team2']['tank'] in elo['tank']['high']:
                                if check_player_status(player, lobby) is False:
                                    lobby['team1']['tank'] = player
                        if check_player_status(player, lobby) is False:
                            lobby['team2']['tank'] = player
                team1_rating, team2_rating, tank1_rating, tank2_rating = sum_rating(lobby)
                if abs(tank1_rating - tank2_rating) <= 300:
                    break
        if abs(team1_rating - team2_rating) > 300:
            for player in free_players:
                if team1_rating > team2_rating:
                    if player.priority_role == 'damage':
                        if (lobby['team1']['damage'][0] or lobby['team1']['damage'][1]) in elo['damage']['high']:
                            if player in elo['damage']['high']:
                                if check_player_status(player, lobby) is False:
                                    lobby['team2']['damage'][0] = lobby['team2']['damage'][1]
                                    lobby['team2']['damage'][0] = player
                        if check_player_status(player, lobby) is False:
                            lobby['team1']['damage'][0] = lobby['team1']['damage'][1]
                            lobby['team1']['damage'][0] = player
                    if player.priority_role == 'support':
                        if (lobby['team1']['support'][0] or lobby['team1']['support'][1]) in elo['support']['high']:
                            if player in elo['support']['high']:
                                if check_player_status(player, lobby) is False:
                                    lobby['team2']['support'][0] = lobby['team2']['support'][1]
                                    lobby['team2']['support'][0] = player
                        if check_player_status(player, lobby) is False:
                            lobby['team1']['support'][0] = lobby['team1']['support'][1]
                            lobby['team1']['support'][0] = player
                else:
                    if player.priority_role == 'damage':
                        if (lobby['team2']['damage'][0] or lobby['team2']['damage'][1]) in elo['damage']['high']:
                            if player in elo['damage']['high']:
                                if check_player_status(player, lobby) is False:
                                    lobby['team1']['damage'][0] = lobby['team2']['damage'][1]
                                    lobby['team1']['damage'][0] = player
                        if check_player_status(player, lobby) is False:
                            lobby['team2']['damage'][0] = lobby['team2']['damage'][1]
                            lobby['team2']['damage'][0] = player
                    if player.priority_role == 'support':
                        if (lobby['team2']['support'][0] or lobby['team2']['support'][1]) in elo['support']['high']:
                            if player in elo['support']['high']:
                                if check_player_status(player, lobby) is False:
                                    lobby['team1']['support'][0] = lobby['team2']['support'][1]
                                    lobby['team1']['support'][0] = player
                        if check_player_status(player, lobby) is False:
                            lobby['team2']['support'][0] = lobby['team2']['support'][1]
                            lobby['team2']['support'][0] = player
                team1_rating, team2_rating, tank1_rating, tank2_rating = sum_rating(lobby)
                if abs(team1_rating - team2_rating) <= 300:
                    break
    if (abs(team1_rating - team2_rating) <= 300) and (abs(tank1_rating - tank2_rating) <= 300):
        return True
    else:
        return False


def hard_balance(lobby, free_players, elo):
    team1_rating, team2_rating, tank1_rating, tank2_rating = sum_rating(lobby)
    if (abs(team1_rating - team2_rating) <= 300) and (abs(tank1_rating - tank2_rating) <= 300):
        return True
    else:
        if abs(tank1_rating - tank2_rating) > 300:
            for player in free_players:
                if player.tank_rating is not None:
                    if tank1_rating > tank2_rating:
                        if player in elo['tank']['high']:
                            if lobby['team1']['tank'] in elo['tank']['high']:
                                if check_player_status(player, lobby) is False:
                                    lobby['team2']['tank'] = player
                        if check_player_status(player, lobby) is False:
                            lobby['team1']['tank'] = player
                    else:
                        if player in elo['tank']['high']:
                            if lobby['team2']['tank'] in elo['tank']['high']:
                                if check_player_status(player, lobby) is False:
                                    lobby['team1']['tank'] = player
                    if check_player_status(player, lobby) is False:
                        lobby['team2']['tank'] = player
                team1_rating, team2_rating, tank1_rating, tank2_rating = sum_rating(lobby)
                if abs(tank1_rating - tank2_rating) <= 300:
                    break
        if abs(team1_rating - team2_rating) > 300:
            for player in free_players:
                if team1_rating > team2_rating:
                    if player.damage_rating is not None:
                        if (lobby['team1']['damage'][0] or lobby['team1']['damage'][1]) in elo['damage']['high']:
                            if player in elo['damage']['high']:
                                if check_player_status(player, lobby) is False:
                                    lobby['team2']['damage'][1] = lobby['team2']['damage'][0]
                                    lobby['team2']['damage'][0] = player
                        if check_player_status(player, lobby) is False:
                            lobby['team1']['damage'][1] = lobby['team1']['damage'][0]
                            lobby['team1']['damage'][0] = player
                    if player.support_rating is not None:
                        if (lobby['team1']['support'][0] or lobby['team1']['support'][1]) in elo['support']['high']:
                            if player in elo['support']['high']:
                                if check_player_status(player, lobby) is False:
                                    lobby['team2']['support'][1] = lobby['team2']['support'][0]
                                    lobby['team2']['support'][0] = player
                        if check_player_status(player, lobby) is False:
                            lobby['team1']['support'][1] = lobby['team1']['support'][0]
                            lobby['team1']['support'][0] = player
                else:
                    if player.damage_rating is not None:
                        if (lobby['team2']['damage'][0] or lobby['team2']['damage'][1]) in elo['damage']['high']:
                            if player in elo['damage']['high']:
                                if check_player_status(player, lobby) is False:
                                    lobby['team1']['damage'][1] = lobby['team2']['damage'][0]
                                    lobby['team1']['damage'][0] = player
                        if check_player_status(player, lobby) is False:
                            lobby['team2']['damage'][1] = lobby['team2']['damage'][0]
                            lobby['team2']['damage'][0] = player
                    if player.support_rating is not None:
                        if (lobby['team2']['support'][0] or lobby['team2']['support'][1]) in elo['support']['high']:
                            if player in elo['support']['high']:
                                if check_player_status(player, lobby) is False:
                                    lobby['team1']['support'][1] = lobby['team2']['support'][0]
                                    lobby['team1']['support'][0] = player
                        if check_player_status(player, lobby) is False:
                            lobby['team2']['support'][1] = lobby['team2']['support'][0]
                            lobby['team2']['support'][0] = player
                team1_rating, team2_rating, tank1_rating, tank2_rating = sum_rating(lobby)
                if abs(team1_rating - team2_rating) <= 300:
                    break
    if (abs(team1_rating - team2_rating) <= 300) and (abs(tank1_rating - tank2_rating) <= 300):
        return True
    else:
        return False


def fill_queued_players(lobby, free_players, queued_players):
    uq_players = []
    for player in queued_players:
        if player not in free_players:
            uq_players.append(player)
        role = player.priority_role
        if role == 'tank':
            for team_name in ["team1", "team2"]:
                if abs(lobby[team_name]['tank'].tank_rating - player.tank_rating) < 500:
                    if player in free_players:
                        old_player = lobby[team_name]['tank']
                        replace_player(lobby[team_name], 'tank', old_player, player, free_players, uq_players)
        if role == 'damage':
            for team_name in ["team1", "team2"]:
                for team_player in [0, 1]:
                    if abs(lobby[team_name]['damage'][team_player].damage_rating - player.damage_rating) < 700:
                        if player in free_players:
                            old_player = lobby[team_name][role][0]
                            replace_player(lobby[team_name], role, old_player, player, free_players, uq_players)
        if role == 'support':
            for team_name in ["team1", "team2"]:
                for team_player in [0, 1]:
                    if abs(lobby[team_name]['support'][team_player].support_rating - player.support_rating) < 700:
                        if player in free_players:
                            old_player = lobby[team_name][role][0]
                            replace_player(lobby[team_name], role, old_player, player, free_players, uq_players)
    for player in uq_players:
        queued_players.remove(player)
    if queued_players:
        return False
    else:
        return True


def replace_player(team, role, old_player, new_player, free_players, uq_players):
    if role == 'tank':
        team['tank'] = new_player
        free_players.remove(new_player)
        uq_players.remove(new_player)
        free_players.append(old_player)
    else:
        free_players.remove(new_player)
        uq_players.append(new_player)
        free_players.append(old_player)
        team[role] = [new_player if player == old_player else player for player in team[role]]


def create_lobbies(lobby_count):
    free_players = get_players()
    queued_players = []
    players = session.query(Queue).all()
    for player in players:
        queued_players.append(session.query(Player).filter(Player.discord_id == player.discord_id).first())
    if len(free_players) >= 10 * lobby_count:
        count = 0
        lobbies = []
        trigger = False
        while count < lobby_count:
            elo = elo_cleaner()
            for player in free_players:
                sort_players(player, elo)
            if trigger is False:
                if fill_players_soft(free_players):
                    lobby = fill_players_soft(free_players)
                    if soft_balance(lobby, free_players, elo) is True:
                        lobbies.append(lobby)
                        count += 1
                        select_current_lobby(lobby, free_players)
                    else:
                        trigger = True
                        count = 0
                        for lobby in lobbies:
                            free_current_lobby(lobby, free_players)
                        lobbies = []
                elif fill_players_soft(free_players) is False:
                    trigger = True
                    count = 0
                    for lobby in lobbies:
                        free_current_lobby(lobby, free_players)
                    lobbies = []
            if trigger is True:
                if fill_players_hard(free_players):
                    lobby = fill_players_hard(free_players)
                    if hard_balance(lobby, free_players, elo) is True:
                        lobbies.append(lobby)
                        count += 1
                        select_current_lobby(lobby, free_players)
                    else:
                        raise ValueError('Balance not found.')
                elif fill_players_hard(free_players) is False:
                    raise ValueError('Not enough free players.')
        step = 0
        for lobby in lobbies:
            step += 1
            queue = fill_queued_players(lobby, free_players, queued_players)
            if len(lobbies) == step and queue is False:
                raise ValueError('Cant fill queue players')
        players = session.query(Queue).all()
        for player in players:
            session.delete(player)
        session.commit()
        return lobbies, free_players
