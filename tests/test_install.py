"""Юнит-тесты install.py: проверка ввода и формирование .env (сам процесс установки не запускается)."""
import io

import pytest
from dotenv import dotenv_values

import install

TOKEN = 'A' * 24 + '.' + 'B' * 6 + '.' + 'C' * 38


class TestValidation:
    def test_token_accepted(self):
        assert install.validate_token(TOKEN) == TOKEN

    @pytest.mark.parametrize('raw', ['', 'short', 'x' * 30 + ' ' + 'y' * 30])
    def test_bad_token_rejected(self, raw):
        with pytest.raises(ValueError):
            install.validate_token(raw)

    def test_admin_ids_parsed(self):
        assert install.parse_admin_ids('111111111111111111, 222222222222222222') == \
            ['111111111111111111', '222222222222222222']

    @pytest.mark.parametrize('raw', ['', 'nmkyt', '123', '111111111111111111,abc'])
    def test_bad_admin_ids_rejected(self, raw):
        with pytest.raises(ValueError):
            install.parse_admin_ids(raw)

    def test_postgres_url(self):
        url = 'postgresql://user:pass@localhost:5432/owmix'
        assert install.validate_postgres_url(url) == url

    @pytest.mark.parametrize('raw', ['', 'sqlite:///x.db', 'mysql://u:p@h/db', "postgresql://u:p'@h/db"])
    def test_bad_postgres_url_rejected(self, raw):
        with pytest.raises(ValueError):
            install.validate_postgres_url(raw)


class TestBuildEnv:
    def parse(self, text):
        return dotenv_values(stream=io.StringIO(text))

    def test_sqlite_env_has_no_database_url(self):
        values = self.parse(install.build_env(TOKEN, ['111111111111111111']))
        assert values == {'BOT_TOKEN': TOKEN, 'ADMIN_IDS': '111111111111111111'}

    def test_admins_joined_with_commas(self):
        values = self.parse(install.build_env(TOKEN, ['111111111111111111', '222222222222222222']))
        assert values['ADMIN_IDS'] == '111111111111111111,222222222222222222'

    def test_postgres_url_survives_special_characters(self):
        url = 'postgresql://user:p#ss w$rd@localhost:5432/owmix'
        values = self.parse(install.build_env(TOKEN, ['111111111111111111'], url))
        assert values['DATABASE_URL'] == url


class TestReadEnvValue:
    def test_reads_plain_and_quoted(self):
        text = "BOT_TOKEN=abc\nDATABASE_URL='postgresql://u:p@h/db'\n"
        assert install.read_env_value(text, 'BOT_TOKEN') == 'abc'
        assert install.read_env_value(text, 'DATABASE_URL') == 'postgresql://u:p@h/db'

    def test_commented_out_value_is_ignored(self):
        assert install.read_env_value('# DATABASE_URL=postgresql://u:p@h/db\n', 'DATABASE_URL') is None

    def test_missing_or_empty(self):
        assert install.read_env_value('BOT_TOKEN=abc\n', 'DATABASE_URL') is None
        assert install.read_env_value('DATABASE_URL=\n', 'DATABASE_URL') is None


class TestNeedsPostgresDriver:
    @pytest.mark.parametrize('url, expected', [
        (None, False),
        ('sqlite:///data/owmix.db', False),
        ('postgresql://u:p@h/db', True),
        ('postgresql+psycopg2://u:p@h/db', True),
    ])
    def test_detection(self, url, expected):
        assert install.needs_postgres_driver(url) is expected


class TestConfigureEnv:
    @pytest.fixture(autouse=True)
    def isolated_paths(self, monkeypatch, tmp_path):
        monkeypatch.setattr(install, 'ENV_FILE', tmp_path / '.env')
        monkeypatch.setattr(install, 'ENV_BACKUP', tmp_path / '.env.bak')

    def answers(self, monkeypatch, *replies):
        replies = iter(replies)
        monkeypatch.setattr('builtins.input', lambda prompt='': next(replies))
        monkeypatch.setattr(install.getpass, 'getpass', lambda prompt='': next(replies))

    def test_fresh_install_with_sqlite_writes_env(self, monkeypatch):
        self.answers(monkeypatch, TOKEN, 'bad id', '111111111111111111', '')
        assert install.configure_env() is None
        values = dotenv_values(install.ENV_FILE)
        assert values == {'BOT_TOKEN': TOKEN, 'ADMIN_IDS': '111111111111111111'}

    def test_postgres_choice_stores_url(self, monkeypatch):
        url = 'postgresql://u:p@localhost:5432/owmix'
        self.answers(monkeypatch, TOKEN, '111111111111111111', '2', 'oops', url)
        assert install.configure_env() == url
        assert dotenv_values(install.ENV_FILE)['DATABASE_URL'] == url

    def test_existing_env_is_kept_by_default(self, monkeypatch):
        install.ENV_FILE.write_text("BOT_TOKEN=keep\nDATABASE_URL='postgresql://u:p@h/db'\n", encoding='utf-8')
        self.answers(monkeypatch, '')
        assert install.configure_env() == 'postgresql://u:p@h/db'
        assert install.ENV_FILE.read_text(encoding='utf-8').startswith('BOT_TOKEN=keep')
        assert not install.ENV_BACKUP.exists()

    def test_overwriting_env_makes_a_backup(self, monkeypatch):
        install.ENV_FILE.write_text('BOT_TOKEN=old\n', encoding='utf-8')
        self.answers(monkeypatch, 'н', TOKEN, '111111111111111111', '1')
        install.configure_env()
        assert install.ENV_BACKUP.read_text(encoding='utf-8') == 'BOT_TOKEN=old\n'
        assert dotenv_values(install.ENV_FILE)['BOT_TOKEN'] == TOKEN
