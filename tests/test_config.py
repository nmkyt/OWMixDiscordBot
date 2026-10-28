"""Юнит-тесты src/config.py: парсинг ADMIN_IDS, выбор базы данных."""
import os

import pytest
from sqlalchemy import create_engine, text

from src import config
from src.config import _parse_admin_ids, _resolve_database_url


class TestResolveDatabaseUrl:
    def test_explicit_url_is_used_as_is(self):
        assert _resolve_database_url('postgresql://u:p@host:5432/db') == 'postgresql://u:p@host:5432/db'

    def test_surrounding_whitespace_is_stripped(self):
        assert _resolve_database_url('  sqlite:///x.db \n') == 'sqlite:///x.db'

    @pytest.mark.parametrize('raw', [None, '', '   '])
    def test_missing_url_falls_back_to_sqlite_file(self, raw, monkeypatch, tmp_path):
        monkeypatch.setattr(config, 'DATA_DIR', str(tmp_path / 'data'))
        url = _resolve_database_url(raw)
        assert url.get_backend_name() == 'sqlite'
        assert url.database == str(tmp_path / 'data' / 'owmix.db')
        assert os.path.isdir(tmp_path / 'data')

    def test_default_sqlite_url_is_usable(self, monkeypatch, tmp_path):
        monkeypatch.setattr(config, 'DATA_DIR', str(tmp_path / 'data with spaces'))
        engine = create_engine(_resolve_database_url(None))
        with engine.begin() as conn:
            conn.execute(text('CREATE TABLE t (x INTEGER)'))
            conn.execute(text('INSERT INTO t VALUES (1)'))
        engine.dispose()
        assert os.path.exists(tmp_path / 'data with spaces' / 'owmix.db')


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
