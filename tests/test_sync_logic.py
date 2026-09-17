"""Юнит-тесты src/sync_logic.py: парсинг рейтинга, ранги, служебные DB-функции."""
import pytest

from src import sync_logic as sl
from src.models import MIN_RATING, MAX_RATING


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
        assert sl.parse_rating_input('b5') == 1000

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


class TestParseRatingUpdate:
    def test_allows_zero_when_not_priority(self):
        assert sl.parse_rating_update('0', 'tank', current_priority='damage') is None

    def test_blocks_zero_on_own_priority_role(self):
        with pytest.raises(ValueError):
            sl.parse_rating_update('0', 'tank', current_priority='tank')

    def test_blocks_zero_when_priority_is_flex(self):
        with pytest.raises(ValueError):
            sl.parse_rating_update('0', 'support', current_priority='flex')

    def test_normal_value_passes_through(self):
        assert sl.parse_rating_update('gm1', 'tank', current_priority='tank') == 4400


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

    def test_check_queue_lists_queued_player_names(self, make_player):
        from src.config import session
        from src.models import Queue

        make_player('1', name='Alice')
        make_player('2', name='Bob')
        session.add(Queue(discord_id='1'))
        session.commit()

        assert sl.check_queue() == ['Alice']
