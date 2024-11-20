import random
from src.balancer import create_lobbies
from src.config import session
from src.models import Queue, Player

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


maps = [
    'Lijiang Tower', 'Antarctic Peninsula', 'Ilios', 'Nepal', 'Samoa',
    'Circuit Royal', 'Dorado', 'Havana', 'Junkertown', 'Rialto', 'Route 66',
    'Watchpoint: Gibraltar', 'Blizzard World', 'Eichenwalde', 'Hollywood',
    'Midtown', 'Paraiso', 'Colosseo', 'Runasapi', 'Oasis'
]


def get_map():
    return random.choice(maps)


def convert_rank_to_value(rank: str) -> int:
    if rank in rank_to_value:
        return rank_to_value.get(rank, "Invalid rank")
    else:
        raise ValueError("Invalid rank")


def check_queue():
    queue = []
    queued_players = session.query(Queue).all()
    players = session.query(Player).all()
    for player in players:
        for queued in queued_players:
            if queued.discord_id == player.discord_id:
                queue.append(player.name)
    return queue


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
    queued_players = []
    lobbies = []
    try:
        lobbies, queued_players = create_lobbies(lobby_count)
        if len(lobbies) == lobby_count:
            for player in queued_players:
                user = Queue(discord_id=player.discord_id)
                session.add(user)
                session.commit()
        else:
            raise StopIteration('Balancer cant find players')
    except StopIteration as e:
        print(f"Error: {e}")
    return lobbies, queued_players

