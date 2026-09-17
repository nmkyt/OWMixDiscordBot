"""Юнит-тесты балансировщика лобби: подбор ролей, анти-повтор, разбиение на команды."""
from types import SimpleNamespace as P

import pytest

import src.balancer as bal


def mk(id, name, role, t=None, d=None, s=None):
    return P(discord_id=str(id), name=name, priority_role=role,
              tank_rating=t, damage_rating=d, support_rating=s)


@pytest.fixture(autouse=True)
def reset_bal_state():
    """Изолируем тесты от истории анти-повтора между собой (не путать с bal.reset_history —
    функцией под тестом в TestResetHistory)."""
    bal.RECENT_PAIRS = {}
    bal.GAME_INDEX = 0
    yield
    bal.RECENT_PAIRS = {}
    bal.GAME_INDEX = 0


class TestFindClosestTanks:
    def test_picks_closest_pair_by_rating(self):
        free = [
            mk(1, 'T1', 'tank', t=3000),
            mk(2, 'T2', 'tank', t=3100),
            mk(3, 'T3', 'tank', t=4000),
        ]
        tanks, free, queued = bal.find_closest_tanks(free, [])
        assert {p.name for p in tanks} == {'T1', 'T2'}
        assert len(tanks) == 2
        assert 'T3' in [p.name for p in free]

    def test_not_enough_tanks_raises(self):
        with pytest.raises(ValueError):
            bal.find_closest_tanks([mk(1, 'T1', 'tank', t=3000)], [])

    def test_queued_tank_forced_in(self):
        queued = [mk(1, 'QT', 'tank', t=1500)]
        free = [mk(2, 'FT1', 'tank', t=3000), mk(3, 'FT2', 'tank', t=3100)]
        tanks, free, queued_after = bal.find_closest_tanks(free, queued)
        assert 'QT' in [p.name for p in tanks]
        assert len(tanks) == 2

    def test_queue_overflow_does_not_lose_players(self):
        """Регрессия: раньше 3-й лишний игрок из очереди на роль терялся навсегда."""
        queued = [mk(1, 'QT1', 'tank', t=3000), mk(2, 'QT2', 'tank', t=3200), mk(3, 'QT3', 'tank', t=2800)]
        free = [mk(4, 'FT1', 'tank', t=3500)]
        tanks, free, queued_after = bal.find_closest_tanks(free, queued)
        assert len(tanks) == 2
        # 3-й игрок должен остаться в очереди, а не пропасть
        assert len(queued_after) == 1
        assert queued_after[0].name == 'QT3'

    def test_ignores_players_with_role_but_no_rating(self):
        """Регрессия: priority_role='tank' без tank_rating не должен попадать в подбор
        (реальный баг, найденный в проде: рассинхрон роли и рейтинга)."""
        broken = mk(99, 'Broken', 'tank', t=None)
        free = [broken, mk(1, 'T1', 'tank', t=3000), mk(2, 'T2', 'tank', t=3100)]
        tanks, free, queued = bal.find_closest_tanks(free, [])
        assert 'Broken' not in [p.name for p in tanks]


class TestFindClosestDamageSupport:
    def test_picks_four(self):
        free = [mk(i, f'D{i}', 'damage', d=2500 + i * 10) for i in range(6)]
        damage, free, queued = bal.find_closest_damage(free, [])
        assert len(damage) == 4

    def test_queue_overflow_does_not_lose_players(self):
        queued = [mk(i, f'QD{i}', 'damage', d=2000 + i * 10) for i in range(1, 6)]
        free = [mk(10 + i, f'FD{i}', 'damage', d=2500 + i * 10) for i in range(1, 4)]
        damage, free, queued_after = bal.find_closest_damage(free, queued)
        assert len(damage) == 4
        assert len(queued_after) == 1

    def test_ignores_players_with_role_but_no_rating(self):
        broken = mk(99, 'Broken', 'damage', d=None)
        free = [broken] + [mk(i, f'D{i}', 'damage', d=2500) for i in range(4)]
        damage, free, queued = bal.find_closest_damage(free, [])
        assert 'Broken' not in [p.name for p in damage]

    def test_cross_role_anti_repeat(self):
        """Кандидат, недавно бывший тиммейтом уже выбранного танка, должен избегаться,
        если есть равноценная по рейтингу альтернатива."""
        bal.GAME_INDEX = 5
        tank = mk(1, 'Tank', 'tank', t=3000)
        d1 = mk(2, 'D1', 'damage', d=2500)
        d2 = mk(3, 'D2', 'damage', d=2500)
        d3 = mk(4, 'D3', 'damage', d=2500)
        d4 = mk(5, 'D4', 'damage', d=2500)
        d5 = mk(6, 'D5', 'damage', d=2500)
        bal.RECENT_PAIRS = {bal._pair_key(tank.discord_id, d1.discord_id):
                             {'last_as_mates': [5], 'last_as_foes': []}}

        damage, _, _ = bal.find_closest_damage([d1, d2, d3, d4, d5], [], lobby_so_far=(tank,))
        assert 'D1' not in [p.name for p in damage]

    def test_support_same_behaviour_as_damage(self):
        free = [mk(i, f'S{i}', 'support', s=2000 + i * 10) for i in range(6)]
        support, free, queued = bal.find_closest_support(free, [])
        assert len(support) == 4


class TestSplitTeams:
    def test_minimizes_rating_difference(self):
        tank_a = mk(1, 'TA', 'tank', t=3000)
        tank_b = mk(2, 'TB', 'tank', t=3100)
        damage = [mk(10 + i, f'D{i}', 'damage', d=v) for i, v in enumerate([2500, 2600, 2400, 2550])]
        support = [mk(20 + i, f'S{i}', 'support', s=v) for i, v in enumerate([2000, 2100, 1900, 2050])]

        team1, team2 = bal._split_teams(tank_a, tank_b, damage, support)

        total1 = team1['tank'].tank_rating + sum(p.damage_rating for p in team1['damage']) + sum(p.support_rating for p in team1['support'])
        total2 = team2['tank'].tank_rating + sum(p.damage_rating for p in team2['damage']) + sum(p.support_rating for p in team2['support'])

        # Для этого набора данных существует идеально сбалансированное разбиение —
        # значит найденное _split_teams должно быть именно им (разница 0).
        assert abs(total1 - total2) == 0

    def test_avoids_recent_teammate_pairing(self):
        bal.GAME_INDEX = 5
        tank_a = mk(1, 'TA', 'tank', t=3000)
        tank_b = mk(2, 'TB', 'tank', t=3000)
        damage = [mk(10 + i, f'D{i}', 'damage', d=2500) for i in range(4)]
        support = [mk(20 + i, f'S{i}', 'support', s=2000) for i in range(4)]

        bal.RECENT_PAIRS = {bal._pair_key(tank_a.discord_id, damage[0].discord_id):
                             {'last_as_mates': [5], 'last_as_foes': []}}

        team1, team2 = bal._split_teams(tank_a, tank_b, damage, support)
        assert damage[0].name not in [p.name for p in team1['damage']]


def _try_form_lobby(free, queued=()):
    """Повторяет оркестрацию create_lobbies: жадный путь, при неудаче — гарантированный."""
    queued = list(queued)
    try:
        free_copy, queued_copy = list(free), list(queued)
        tanks, free_copy, queued_copy = bal.find_closest_tanks(free_copy, queued_copy)
        damage, free_copy, queued_copy = bal.find_closest_damage(free_copy, queued_copy, lobby_so_far=tanks)
        support, free_copy, queued_copy = bal.find_closest_support(free_copy, queued_copy, lobby_so_far=tanks + damage)
        return tanks, damage, support
    except ValueError:
        tanks, damage, support, _, _ = bal._guaranteed_lobby(free, queued)
        return tanks, damage, support


class TestGuaranteedLobbyFormation:
    def test_greedy_failure_still_forms_valid_lobby(self):
        """Регрессия: 10 игроков, у каждого есть рейтинг на нужных ролях, но жадный
        алгоритм 'по ошибке' может забрать гибридного игрока не туда, где он необходим.
        Итог всё равно должен быть полным рабочим лобби."""
        t1 = mk(1, 'T1', 'tank', t=3000)
        t2 = mk(2, 'T2', 'tank', t=3050)
        x = mk(3, 'X', 'tank', t=3010, s=2000)  # приоритет tank, но есть и support_rating
        d = [mk(10 + i, f'D{i}', 'damage', d=2500) for i in range(4)]
        s = [mk(20 + i, f'S{i}', 'support', s=2000) for i in range(3)]  # без X — только 3
        free = [t1, t2, x] + d + s

        with pytest.raises(ValueError):
            # убеждаемся, что жадный путь САМ ПО СЕБЕ действительно не справляется —
            # иначе тест ничего не проверяет.
            tanks, f2, q2 = bal.find_closest_tanks(list(free), [])
            damage, f2, q2 = bal.find_closest_damage(f2, q2, lobby_so_far=tanks)
            bal.find_closest_support(f2, q2, lobby_so_far=tanks + damage)

        tanks, damage, support = _try_form_lobby(free)
        assert len(tanks) == 2 and len(damage) == 4 and len(support) == 4
        assert x.name in [p.name for p in support]

    def test_truly_infeasible_still_raises(self):
        """Когда валидного состава не существует математически (саппортов физически
        не хватает даже с учётом гибридов) — должно честно упасть, а не выдумать состав."""
        free = ([mk(1, 'T1', 'tank', t=3000), mk(2, 'T2', 'tank', t=3000)] +
                [mk(10 + i, f'D{i}', 'damage', d=2500) for i in range(4)] +
                [mk(20 + i, f'S{i}', 'support', s=2000) for i in range(2)])  # всего 8 игроков
        with pytest.raises(ValueError):
            _try_form_lobby(free)

    def test_guaranteed_lobby_respects_priority_when_both_options_exist(self):
        """Если жадный путь не нужен вообще (запас кандидатов есть на обеих ролях),
        резервная функция всё равно должна уважать приоритетную роль, а не расставлять
        игроков произвольно."""
        t = [mk(i, f'T{i}', 'tank', t=3000) for i in range(2)]
        d = [mk(10 + i, f'D{i}', 'damage', d=2500) for i in range(4)]
        s = [mk(20 + i, f'S{i}', 'support', s=2000) for i in range(4)]
        result = bal._guaranteed_lobby(t + d + s, [])
        tanks, damage, support, _, _ = result
        assert {p.name for p in tanks} == {'T0', 'T1'}
        assert {p.name for p in damage} == {'D0', 'D1', 'D2', 'D3'}
        assert {p.name for p in support} == {'S0', 'S1', 'S2', 'S3'}


class TestResetHistory:
    def test_clears_in_memory_state(self):
        bal.RECENT_PAIRS = {'1-2': {'last_as_mates': [1], 'last_as_foes': []}}
        bal.GAME_INDEX = 7
        bal.reset_history()
        assert bal.RECENT_PAIRS == {}
        assert bal.GAME_INDEX == 0

    def test_persists_reset_to_disk(self, tmp_path, monkeypatch):
        """Регрессия: сброс должен переживать перезапуск бота (init_history не должен
        снова подхватить старую историю с диска)."""
        history_file = tmp_path / "recent_pairs.json"
        monkeypatch.setattr(bal, "HISTORY_FILE", str(history_file))
        monkeypatch.setattr(bal, "DATA_DIR", str(tmp_path))

        bal.RECENT_PAIRS = {'1-2': {'last_as_mates': [1], 'last_as_foes': []}}
        bal.GAME_INDEX = 7
        bal.save_history()

        bal.reset_history()
        bal.RECENT_PAIRS = {'stale': 'data'}  # эмулируем как будто ничего не грузили
        bal.init_history()

        assert bal.RECENT_PAIRS == {}
        assert bal.GAME_INDEX == 0


class TestPairPenalty:
    def test_decays_outside_window(self):
        bal.GAME_INDEX = 10
        bal.RECENT_PAIRS = {'1-2': {'last_as_mates': [3], 'last_as_foes': []}}  # age=7, окно=6
        a, b = mk(1, 'A', 'tank'), mk(2, 'B', 'tank')
        assert bal.pair_penalty(a, b, as_mates=True) == 0

    def test_penalty_inside_window(self):
        bal.GAME_INDEX = 5
        bal.RECENT_PAIRS = {bal._pair_key('1', '2'): {'last_as_mates': [5], 'last_as_foes': []}}
        a, b = mk(1, 'A', 'tank'), mk(2, 'B', 'tank')
        assert bal.pair_penalty(a, b, as_mates=True) == bal.WINDOW_GAMES
