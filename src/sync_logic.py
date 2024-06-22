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
