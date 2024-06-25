from balancer import create_lobbies
from config import session
from models import Queue

rank_to_value = {
    'b5': 1000, 'b4': 1100, 'b3': 1200, 'b2': 1300, 'b1': 1400,
    's5': 1500, 's4': 1600, 's3': 1700, 's2': 1800, 's1': 1900,
    'g5': 2000, 'g4': 2100, 'g3': 2200, 'g2': 2300, 'g1': 2400,
    'p5': 2500, 'p4': 2600, 'p3': 2700, 'p2': 2800, 'p1': 2900,
    'd5': 3000, 'd4': 3100, 'd3': 3200, 'd2': 3300, 'd1': 3400,
    'm5': 3500, 'm4': 3600, 'm3': 3700, 'm2': 3800, 'm1': 3900,
    'gm5': 4000, 'gm4': 4100, 'gm3': 4200, 'gm2': 4300, 'gm1': 4400,
    'cp5': 4500, 'cp4': 4600, 'cp3': 4700, 'cp2': 4800, 'cp1': 4900
}


def convert_rank_to_value(rank: str) -> int:
    if rank in rank_to_value:
        return rank_to_value.get(rank, "Invalid rank")
    else:
        raise ValueError("Invalid rank")


def lobbies_players(lobbies):
    active_players = []
    for lobby in lobbies:
        active_players.append(lobby['team1']['tank'].discord_id)
        active_players.append(lobby['team2']['tank'].discord_id)
        for player in lobby['team1']['damage']:
            active_players.append(player.discord_id)
        for player in lobby['team2']['damage']:
            active_players.append(player.discord_id)
        for player in lobby['team1']['support']:
            active_players.append(player.discord_id)
        for player in lobby['team2']['support']:
            active_players.append(player.discord_id)
    return active_players


def create_lobbies_caller(lobby_count, create_option):
    queued_players = []
    lobbies = []
    count = 0
    if create_option == 'free':
        pass
    if create_option == 'balance':
        try:
            while True:
                count += 1
                try:
                    lobbies, queued_players = create_lobbies(lobby_count)
                except ValueError as e:
                    print(f"Error: {e}")
                if len(lobbies) == lobby_count:
                    for player in queued_players:
                        user = Queue(discord_id=player.discord_id)
                        session.add(user)
                        session.commit()
                    break
                if count == 100:
                    raise StopIteration('Balancer cant find players')
        except StopIteration as e:
            print(f"Error: {e}")
    if create_option == 'queued_players':
        pass
    return lobbies, queued_players
