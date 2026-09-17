"""Юнит-тесты src/config.py: парсинг ADMIN_IDS."""
from src.config import _parse_admin_ids


class TestParseAdminIds:
    def test_comma_separated(self):
        assert _parse_admin_ids('1,2,3') == {1, 2, 3}

    def test_space_separated(self):
        assert _parse_admin_ids('1 2 3') == {1, 2, 3}

    def test_mixed_separators_and_spaces(self):
        assert _parse_admin_ids(' 1, 2 ,3 ') == {1, 2, 3}

    def test_empty_string(self):
        assert _parse_admin_ids('') == set()

    def test_invalid_entries_are_skipped_not_fatal(self):
        """Регрессия: опечатка в ADMIN_IDS не должна ронять запуск бота."""
        assert _parse_admin_ids('1,not-an-id,3') == {1, 3}

    def test_duplicates_collapsed(self):
        assert _parse_admin_ids('1,1,2') == {1, 2}
