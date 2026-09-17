"""Юнит-тесты update_user_status — логики чек-ина и выбора приоритетной роли."""
import src.bot_controller as bc


class TestUpdateUserStatusRegistration:
    def test_unregistered_user(self):
        assert bc.update_user_status('999999', 'checked_in', 'yes') == 'not_registered'


class TestCheckIn:
    def test_check_in_requires_role(self, make_player):
        """Регрессия: раньше можно было чек-инится вообще без выбранной роли."""
        p = make_player('1', priority_role=None)
        result = bc.update_user_status('1', 'checked_in', 'yes')
        assert result == 'no_role'
        assert p.check_in == 'no'

    def test_check_in_succeeds_with_role(self, make_player):
        p = make_player('1', priority_role='tank', tank_rating=3000)
        result = bc.update_user_status('1', 'checked_in', 'yes')
        assert result is True
        assert p.check_in == 'yes'

    def test_check_out_works_without_role(self, make_player):
        """Выйти из миксов можно всегда, даже если роль не выбрана."""
        p = make_player('1', priority_role=None, check_in='yes')
        result = bc.update_user_status('1', 'checked_in', 'no')
        assert result is True
        assert p.check_in == 'no'


class TestPriorityRoleSelection:
    def test_cannot_select_role_without_rating(self, make_player):
        p = make_player('1', tank_rating=None)
        result = bc.update_user_status('1', 'priority_role', 'tank')
        assert result is False
        assert p.priority_role is None

    def test_can_select_role_with_rating(self, make_player):
        p = make_player('1', tank_rating=3000)
        result = bc.update_user_status('1', 'priority_role', 'tank')
        assert result is True
        assert p.priority_role == 'tank'

    def test_flex_requires_all_three_ratings(self, make_player):
        p = make_player('1', tank_rating=3000, damage_rating=3000, support_rating=None)
        result = bc.update_user_status('1', 'priority_role', 'flex')
        assert result is False
        assert p.priority_role is None

    def test_flex_succeeds_with_all_ratings(self, make_player):
        p = make_player('1', tank_rating=3000, damage_rating=3100, support_rating=3200)
        result = bc.update_user_status('1', 'priority_role', 'flex')
        assert result is True
        assert p.priority_role == 'flex'
