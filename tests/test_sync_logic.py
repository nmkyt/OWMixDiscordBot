"""Юнит-тесты src/sync_logic.py: парсинг рейтинга, ранги, служебные DB-функции."""
import pytest

from src import sync_logic as sl
from src.config import session
from src.models import MIN_RATING, MAX_RATING, Queue


class TestGetMap:
    @pytest.fixture(autouse=True)
    def fresh_bag(self, monkeypatch):
        monkeypatch.setattr(sl, '_map_bag', [])
        monkeypatch.setattr(sl, '_last_map', None)

    def test_full_cycle_has_no_repeats(self):
        drawn = [sl.get_map() for _ in sl.maps]
        assert sorted(drawn) == sorted(sl.maps)

    def test_every_cycle_covers_all_maps(self):
        for _ in range(3):
            drawn = [sl.get_map() for _ in sl.maps]
            assert set(drawn) == set(sl.maps)

    def test_no_back_to_back_repeat_across_cycles(self):
        drawn = [sl.get_map() for _ in range(len(sl.maps) * 50)]
        assert all(a != b for a, b in zip(drawn, drawn[1:]))

    def test_cycle_boundary_swaps_when_next_map_equals_last(self, monkeypatch):
        monkeypatch.setattr(sl, '_last_map', sl.maps[-1])
        # shuffle подменён: порядок остаётся прежним, поэтому следующей по pop() была бы maps[-1]
        monkeypatch.setattr(sl.random, 'shuffle', lambda seq: None)
        assert sl.get_map() != sl.maps[-1]


class TestConvertRankToValue:
    def test_known_rank(self):
        assert sl.convert_rank_to_value('gm3') == 4200

    def test_unknown_rank_raises(self):
        with pytest.raises(ValueError):
            sl.convert_rank_to_value('zz9')


class TestParseRatingInput:
    def test_zero_means_no_role(self):
        assert sl.parse_rating_input('0') is None

    def test_rank_shorthand(self):
        assert sl.parse_rating_input('gm3') == 4200
        assert sl.parse_rating_input('GM3') == 4200  # регистр не важен

    def test_bronze_is_valid(self):
        """Регрессия: минимальная граница диапазона должна пропускать Bronze (b1-b5)."""
        assert sl.parse_rating_input('b5') == MIN_RATING == 500

    def test_numeric_within_range(self):
        assert sl.parse_rating_input('3000') == 3000

    def test_numeric_below_min_rejected(self):
        with pytest.raises(ValueError):
            sl.parse_rating_input(str(MIN_RATING - 1))

    def test_numeric_above_max_rejected(self):
        with pytest.raises(ValueError):
            sl.parse_rating_input(str(MAX_RATING + 1))

    def test_garbage_rejected(self):
        with pytest.raises(ValueError):
            sl.parse_rating_input('not-a-number')

    def test_takes_first_token_before_comma(self):
        assert sl.parse_rating_input('3000,ignored') == 3000


class TestPickPriorityRole:
    def test_keeps_role_that_still_has_rating(self):
        assert sl.pick_priority_role('support', 3000, None, 2500) == 'support'

    def test_switches_to_first_rated_role_when_priority_zeroed(self):
        assert sl.pick_priority_role('tank', None, 3000, 2500) == 'damage'

    def test_flex_kept_with_all_ratings(self):
        assert sl.pick_priority_role('flex', 3000, 3000, 3000) == 'flex'

    def test_flex_dropped_when_any_role_zeroed(self):
        assert sl.pick_priority_role('flex', 3000, 3000, None) == 'tank'

    def test_no_priority_gets_first_rated_role(self):
        assert sl.pick_priority_role(None, None, None, 2000) == 'support'


class TestGetRating:
    def test_balanced_lobby_zero_diff(self):
        from types import SimpleNamespace as P
        # team1 = 3000+2400+2550+2100+2050 = 12100, team2 = 3100+2500+2600+2000+1900 = 12100
        lobby = {
            'team1': {'tank': P(tank_rating=3000), 'damage': [P(damage_rating=2400), P(damage_rating=2550)],
                      'support': [P(support_rating=2100), P(support_rating=2050)]},
            'team2': {'tank': P(tank_rating=3100), 'damage': [P(damage_rating=2500), P(damage_rating=2600)],
                      'support': [P(support_rating=2000), P(support_rating=1900)]},
        }
        diff, match_rating = sl.get_rating(lobby)
        assert diff == 0
        assert match_rating == 2420  # (12100+12100)/10

    def test_unbalanced_lobby_nonzero_diff(self):
        from types import SimpleNamespace as P
        lobby = {
            'team1': {'tank': P(tank_rating=3000), 'damage': [P(damage_rating=2500), P(damage_rating=2600)],
                      'support': [P(support_rating=2000), P(support_rating=2100)]},
            'team2': {'tank': P(tank_rating=3100), 'damage': [P(damage_rating=2400), P(damage_rating=2550)],
                      'support': [P(support_rating=1900), P(support_rating=2050)]},
        }
        diff, _ = sl.get_rating(lobby)
        assert diff == 40  # |12200 - 12000| / 5


class TestDescribeBalance:
    @staticmethod
    def _lobby(team1_total, team2_total):
        """Лобби, где у каждого из 5 игроков команды одинаковый рейтинг total/5 (total кратен 5)."""
        from types import SimpleNamespace as P

        def team(total):
            r = total // 5
            return {'tank': P(tank_rating=r), 'damage': [P(damage_rating=r)] * 2, 'support': [P(support_rating=r)] * 2}
        return {'team1': team(team1_total), 'team2': team(team2_total)}

    def test_equal_teams(self):
        text = sl.describe_balance(self._lobby(12000, 12000))
        assert text == ('Средний рейтинг матча 2400 SR\n'
                        '🟢 Идеальный баланс (💙 2400 · 💖 2400)')

    def test_ideal_balance_names_no_team_and_no_diff(self):
        # 8 SR на игрока — ещё «Идеальный баланс»: ни сильной команды, ни числа SR
        text = sl.describe_balance(self._lobby(12040, 12000))
        assert text == ('Средний рейтинг матча 2404 SR\n'
                        '🟢 Идеальный баланс (💙 2408 · 💖 2400)')

    def test_names_stronger_team_and_diff_per_player(self):
        # |12150 - 12000| / 5 = 30 SR на игрока, сильнее команда 1 (синие)
        text = sl.describe_balance(self._lobby(12150, 12000))
        assert '💙 Синие — 🟡 Небольшой перевес: +30 SR на игрока' in text
        assert text.endswith('(💙 2430 · 💖 2400)')

    def test_red_team_stronger(self):
        text = sl.describe_balance(self._lobby(12000, 12150))
        assert '💖 Красные — 🟡 Небольшой перевес: +30 SR на игрока' in text

    @pytest.mark.parametrize('diff_per_player, expected', [
        (5, '🟢 Идеальный баланс'),
        (9, '🟢 Идеальный баланс'),
        (10, '🟢 Ровные команды'),
        (24, '🟢 Ровные команды'),
        (25, '🟡 Небольшой перевес'),
        (49, '🟡 Небольшой перевес'),
        (50, '🟠 Заметный перевес'),
        (99, '🟠 Заметный перевес'),
        (100, '🔴 Сильный перевес'),
        (400, '🔴 Сильный перевес'),
    ])
    def test_level_boundaries(self, diff_per_player, expected):
        text = sl.describe_balance(self._lobby(12000 + diff_per_player * 5, 12000))
        assert expected in text


class TestDbBackedHelpers:
    def test_active_players_filters_checked_in(self, make_player):
        make_player('1', name='A', check_in='yes')
        make_player('2', name='B', check_in='no')
        names, count = sl.active_players()
        assert names == ['A']
        assert count == 1

    def test_end_resets_all_checkins(self, make_player):
        make_player('1', check_in='yes')
        make_player('2', check_in='yes')
        sl.end()
        names, count = sl.active_players()
        assert count == 0

    def test_leftover_players_requeued_on_partial_success(self, make_player):
        """Регрессия: раньше оставшихся игроков возвращали в очередь только при
        ПОЛНОМ успехе (все N лобби собраны) — при частичном успехе они терялись
        из очереди (хотя из чек-ина не выпадали)."""
        from src.models import Queue

        for i in range(4):
            make_player(f't{i}', priority_role='tank', tank_rating=3000, check_in='yes')
        for i in range(12):
            make_player(f'd{i}', priority_role='damage', damage_rating=2500, check_in='yes')
        for i in range(4):
            make_player(f's{i}', priority_role='support', support_rating=2000, check_in='yes')

        lobbies, leftover = sl.create_lobbies_caller(2)

        assert len(lobbies) == 1
        assert len(leftover) == 10
        assert session.query(Queue).count() == 10

    def test_full_evening_without_manual_queue_cleanup(self, make_player):
        """Регрессия: 30 отметившихся + !create_lobby 2 оставляли 10 человек в очереди,
        а create_lobbies отказывалась работать при очереди >= 10 — каждый следующий
        !create_lobby падал до ручного !queue_clear. Теперь вечер идёт сам, а ждавшие
        играют в следующем вызове первыми."""
        for i in range(6):
            make_player(f't{i}', priority_role='tank', tank_rating=2500 + i * 100, check_in='yes')
        for i in range(12):
            make_player(f'd{i}', priority_role='damage', damage_rating=2000 + i * 50, check_in='yes')
        for i in range(12):
            make_player(f's{i}', priority_role='support', support_rating=1800 + i * 50, check_in='yes')

        def lobby_ids(lobbies):
            return {p.discord_id for lobby in lobbies for team in (lobby['team1'], lobby['team2'])
                    for p in [team['tank']] + team['damage'] + team['support']}

        def queue_ids():
            return [q.discord_id for q in session.query(Queue).order_by(Queue.id)]

        waiting = set()
        for _ in range(3):
            lobbies, leftover = sl.create_lobbies_caller(2)
            played = lobby_ids(lobbies)
            assert len(lobbies) == 2 and len(played) == 20
            assert waiting <= played  # все ждавшие сыграли в этом вызове
            assert queue_ids() == [p.discord_id for p in leftover]
            assert len(leftover) == 10 and not (set(queue_ids()) & played)
            waiting = set(queue_ids())

    def test_queue_order_is_priority_order(self, make_player):
        """Мест на роли меньше, чем ждущих: играют стоящие в очереди раньше, а
        не попавший остаётся в начале новой очереди — перед новыми ожидающими."""
        make_player('q1', priority_role='tank', tank_rating=3000, check_in='yes')
        make_player('q2', priority_role='tank', tank_rating=3500, check_in='yes')
        make_player('q3', priority_role='tank', tank_rating=4000, check_in='yes')
        make_player('ft', priority_role='tank', tank_rating=4000, check_in='yes')
        for i in range(4):
            make_player(f'd{i}', priority_role='damage', damage_rating=2500, check_in='yes')
            make_player(f's{i}', priority_role='support', support_rating=2000, check_in='yes')
        for discord_id in ('q2', 'q3', 'q1'):
            session.add(Queue(discord_id=discord_id))
            session.commit()

        lobbies, leftover = sl.create_lobbies_caller(1)

        tanks = {lobbies[0]['team1']['tank'].discord_id, lobbies[0]['team2']['tank'].discord_id}
        assert tanks == {'q2', 'q3'}
        assert [q.discord_id for q in session.query(Queue).order_by(Queue.id)] == ['q1', 'ft']

    def test_queue_untouched_when_no_lobby_formed(self, make_player):
        """Ноль лобби — это не повод ставить в очередь всех отметившихся: тогда
        приоритет реально ждущих игроков потерялся бы."""
        for i in range(10):
            make_player(f'd{i}', priority_role='damage', damage_rating=2500, check_in='yes')
        session.add(Queue(discord_id='d3'))
        session.commit()

        lobbies, _ = sl.create_lobbies_caller(1)

        assert lobbies == []
        assert [q.discord_id for q in session.query(Queue)] == ['d3']

    def test_check_queue_lists_queued_player_names(self, make_player):
        from src.config import session
        from src.models import Queue

        make_player('1', name='Alice')
        make_player('2', name='Bob')
        session.add(Queue(discord_id='1'))
        session.commit()

        assert sl.check_queue() == ['Alice']


class TestMixStatus:
    def test_empty_db(self):
        status = sl.mix_status()
        assert status['total'] == 0
        assert status['checked_in'] == 0
        assert status['queued'] == 0
        assert status['lobbies'] == 0

    def test_counts_and_roles(self, make_player):
        make_player('1', check_in='yes', priority_role='tank', tank_rating=3000, damage_rating=2500)
        make_player('2', check_in='yes', priority_role='flex',
                    tank_rating=3000, damage_rating=3000, support_rating=3000)
        make_player('3', check_in='yes', priority_role='support', support_rating=2000)
        make_player('4', check_in='no', priority_role='damage', damage_rating=2000)

        status = sl.mix_status()
        assert status['total'] == 4
        assert status['checked_in'] == 3
        assert status['by_priority'] == {'tank': 1, 'damage': 0, 'support': 1, 'flex': 1}
        assert status['can_play'] == {'tank': 2, 'damage': 2, 'support': 2}
        assert status['lobbies'] == 0
        assert status['to_next_lobby'] == 7

    def test_queue_counts_only_checked_in(self, make_player):
        make_player('1', check_in='yes', priority_role='tank', tank_rating=3000)
        make_player('2', check_in='no', priority_role='tank', tank_rating=3000)
        session.add_all([Queue(discord_id='1'), Queue(discord_id='2')])
        session.commit()
        assert sl.mix_status()['queued'] == 1

    def test_lobby_count(self, make_player):
        for i in range(23):
            make_player(str(i), check_in='yes', priority_role='damage', damage_rating=2000)
        status = sl.mix_status()
        assert status['lobbies'] == 2
        assert status['to_next_lobby'] == 7
        assert status['short_roles'] == ['tank', 'support']

    def test_no_short_roles_when_enough(self, make_player):
        for i in range(10):
            make_player(str(i), check_in='yes', priority_role='flex',
                        tank_rating=3000, damage_rating=3000, support_rating=3000)
        assert sl.mix_status()['short_roles'] == []



class TestUpdateUserStatusRegistration:
    def test_unregistered_user(self):
        assert sl.update_user_status('999999', 'checked_in', 'yes') == 'not_registered'


class TestCheckIn:
    def test_check_in_requires_role(self, make_player):
        """Регрессия: раньше можно было чек-инится вообще без выбранной роли."""
        p = make_player('1', priority_role=None)
        result = sl.update_user_status('1', 'checked_in', 'yes')
        assert result == 'no_role'
        assert p.check_in == 'no'

    def test_check_in_succeeds_with_role(self, make_player):
        p = make_player('1', priority_role='tank', tank_rating=3000)
        result = sl.update_user_status('1', 'checked_in', 'yes')
        assert result is True
        assert p.check_in == 'yes'

    def test_check_out_works_without_role(self, make_player):
        """Выйти из миксов можно всегда, даже если роль не выбрана."""
        p = make_player('1', priority_role=None, check_in='yes')
        result = sl.update_user_status('1', 'checked_in', 'no')
        assert result is True
        assert p.check_in == 'no'


class TestPriorityRoleSelection:
    def test_cannot_select_role_without_rating(self, make_player):
        p = make_player('1', tank_rating=None)
        result = sl.update_user_status('1', 'priority_role', 'tank')
        assert result is False
        assert p.priority_role is None

    def test_can_select_role_with_rating(self, make_player):
        p = make_player('1', tank_rating=3000)
        result = sl.update_user_status('1', 'priority_role', 'tank')
        assert result is True
        assert p.priority_role == 'tank'

    def test_flex_requires_all_three_ratings(self, make_player):
        p = make_player('1', tank_rating=3000, damage_rating=3000, support_rating=None)
        result = sl.update_user_status('1', 'priority_role', 'flex')
        assert result is False
        assert p.priority_role is None

    def test_flex_succeeds_with_all_ratings(self, make_player):
        p = make_player('1', tank_rating=3000, damage_rating=3100, support_rating=3200)
        result = sl.update_user_status('1', 'priority_role', 'flex')
        assert result is True
        assert p.priority_role == 'flex'


class TestParseBattleTagAndRatings:
    def test_battle_tag_to_name(self):
        assert sl.parse_battle_tag('Sacr1ficed#2456') == 'Sacr1ficed'

    def test_bad_battle_tag(self):
        with pytest.raises(ValueError, match='BattleTag'):
            sl.parse_battle_tag('Sacr1ficed')

    def test_ratings_parsed(self):
        assert sl.parse_ratings('4000', 'd2', '0') == (4000, 3300, None)

    def test_rating_error_names_role(self):
        with pytest.raises(ValueError, match='^DPS: '):
            sl.parse_ratings('4000', 'xyz', '0')

    def test_all_zero_rejected(self):
        with pytest.raises(ValueError, match='хотя бы на одной роли'):
            sl.parse_ratings('0', '0', '0')


class TestPlayerAndQueueOperations:
    def test_register_sets_first_rated_role_as_priority(self):
        assert sl.register_player('1', 'Alice', None, 3000, 2500) is True
        assert sl.get_player('1').priority_role == 'damage'

    def test_register_twice_rejected(self, make_player):
        make_player('1')
        assert sl.register_player('1', 'Alice', 3000, None, None) is False

    def test_update_ratings(self, make_player):
        make_player('1', name='Alice', priority_role='tank', tank_rating=3000)
        assert sl.update_player_ratings('1', '3500', '0', 'g4') == ('Alice', 'tank', 'tank')
        p = sl.get_player('1')
        assert (p.tank_rating, p.damage_rating, p.support_rating) == (3500, None, 1600)

    def test_zeroing_priority_role_switches_priority(self, make_player):
        make_player('1', name='Alice', priority_role='tank', tank_rating=3000, check_in='yes')
        assert sl.update_player_ratings('1', '0', '0', 'g4') == ('Alice', 'tank', 'support')
        p = sl.get_player('1')
        assert (p.tank_rating, p.priority_role, p.check_in) == (None, 'support', 'yes')

    def test_update_ratings_unknown_player(self):
        assert sl.update_player_ratings('404', '3000', '0', '0') is None

    def test_add_to_queue_statuses(self, make_player):
        assert sl.add_to_queue('1') == ('not_registered', None)
        make_player('1')
        assert sl.add_to_queue('1')[0] == 'added'
        assert sl.add_to_queue('1')[0] == 'already_queued'

    def test_remove_and_clear_queue(self, make_player):
        make_player('1')
        make_player('2')
        sl.add_to_queue('1')
        sl.add_to_queue('2')
        assert sl.remove_from_queue('1') is True
        assert sl.remove_from_queue('1') is False
        sl.clear_queue()
        assert session.query(Queue).count() == 0

    def test_uncheck_player(self, make_player):
        make_player('1', check_in='yes')
        sl.add_to_queue('1')
        assert sl.uncheck_player('1') is True
        assert sl.get_player('1').check_in == 'no'
        assert session.query(Queue).count() == 0
        assert sl.uncheck_player('404') is False
