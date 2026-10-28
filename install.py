"""Установщик бота: создаёт виртуальное окружение, ставит зависимости и записывает .env.

Нужен только Python 3.12+ (сторонние пакеты не требуются):
    python install.py
Скрипт можно запускать повторно — существующее окружение и .env он не ломает.
"""
import getpass
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV_DIR = ROOT / ".venv"
ENV_FILE = ROOT / ".env"
ENV_BACKUP = ROOT / ".env.bak"
MIN_PYTHON = (3, 12)


def venv_python() -> Path:
    """Интерпретатор виртуального окружения проекта."""
    return VENV_DIR / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def validate_token(raw: str) -> str:
    if len(raw) < 40 or re.search(r"\s", raw):
        raise ValueError("это не похоже на токен бота (длинная строка без пробелов) — скопируйте его заново")
    return raw


def parse_admin_ids(raw: str) -> list[str]:
    """'1, 2 3' -> ['1', '2', '3']; Discord ID — это только цифры (15–20 знаков)."""
    parts = raw.replace(",", " ").split()
    if not parts or not all(p.isdigit() and 15 <= len(p) <= 20 for p in parts):
        raise ValueError("нужен числовой Discord ID (17–19 цифр), не имя пользователя; несколько — через запятую")
    return parts


def validate_postgres_url(raw: str) -> str:
    if not raw.startswith("postgresql") or "'" in raw:
        raise ValueError("строка должна начинаться с postgresql:// "
                         "(пример: postgresql://user:password@localhost:5432/owmix)")
    return raw


def build_env(token: str, admin_ids: list[str], database_url: str | None = None) -> str:
    """Текст .env. Без database_url бот использует локальный SQLite-файл."""
    lines = [
        "# Создано install.py. Файл .env не попадает в git — не публикуйте его: в нём токен бота.",
        f"BOT_TOKEN={token}",
        f"ADMIN_IDS={','.join(admin_ids)}",
    ]
    if database_url:
        lines.append(f"DATABASE_URL='{database_url}'")
    else:
        lines.append("# DATABASE_URL не задан: используется SQLite-файл data/owmix.db")
    return "\n".join(lines) + "\n"


def read_env_value(env_text: str, key: str) -> str | None:
    """Значение переменной из текста .env (без кавычек); закомментированные строки игнорируются."""
    for line in env_text.splitlines():
        name, sep, value = line.strip().partition("=")
        if sep and name.strip() == key:
            return value.strip().strip("'\"") or None
    return None


def needs_postgres_driver(database_url: str | None) -> bool:
    return bool(database_url) and database_url.startswith("postgres")


def ask(prompt: str, validate, default: str | None = None, secret: bool = False):
    """Спрашивает, пока validate(ответ) не перестанет бросать ValueError."""
    suffix = f" [{default}]" if default else ""
    read = getpass.getpass if secret else input
    while True:
        raw = read(f"{prompt}{suffix}: ").strip()
        if not raw and default is not None:
            return default
        try:
            return validate(raw)
        except ValueError as e:
            print(f"  ! {e}")


def ask_yes_no(prompt: str, default: bool) -> bool:
    answer = ask(f"{prompt} ({'Д/н' if default else 'д/Н'})", lambda raw: raw.lower(), default='')
    if not answer:
        return default
    return answer in ("д", "да", "y", "yes")


def configure_env() -> str | None:
    """Записывает .env (или оставляет существующий). Возвращает DATABASE_URL из итогового .env."""
    if ENV_FILE.exists():
        print(f"Найден {ENV_FILE.name}.")
        if ask_yes_no("Оставить его без изменений?", default=True):
            return read_env_value(ENV_FILE.read_text(encoding="utf-8"), "DATABASE_URL")
        shutil.copy(ENV_FILE, ENV_BACKUP)
        print(f"Старый файл сохранён как {ENV_BACKUP.name}.")

    print("\nТокен бота: https://discord.com/developers/applications -> ваше приложение -> Bot -> Token.")
    print("(при вводе токен не отображается — просто вставьте его и нажмите Enter)")
    token = ask("Токен бота", validate_token, secret=True)

    print("\nАдминистраторы бота. Свой ID: Discord -> Настройки -> Расширенные -> Режим разработчика,")
    print("затем ПКМ по себе -> «Копировать ID».")
    admin_ids = ask("Discord ID администраторов (через запятую)", parse_admin_ids)

    print("\nБаза данных:")
    print("  1 — SQLite: файл рядом с ботом, ничего настраивать не нужно (рекомендуется)")
    print("  2 — PostgreSQL: свой сервер баз данных")
    choice = ask("Выбор", lambda raw: raw if raw in ("1", "2") else _raise("введите 1 или 2"), default="1")
    database_url = ask("Строка подключения PostgreSQL", validate_postgres_url) if choice == "2" else None

    ENV_FILE.write_text(build_env(token, admin_ids, database_url), encoding="utf-8")
    try:
        ENV_FILE.chmod(0o600)  # на Windows не действует, на Linux/macOS закрывает файл от других пользователей
    except OSError:
        pass
    print(f"\nГотово: {ENV_FILE.name} записан.")
    return database_url


def _raise(message: str):
    raise ValueError(message)


def run(*args: str) -> None:
    subprocess.check_call(list(args))


def install_dependencies(with_postgres: bool) -> None:
    if not venv_python().exists():
        print("\nСоздаю виртуальное окружение...")
        try:
            run(sys.executable, "-m", "venv", str(VENV_DIR))
        except subprocess.CalledProcessError:
            sys.exit("Не удалось создать окружение. На Debian/Ubuntu установите модуль: sudo apt install python3-venv")

    requirements = "requirements-postgres.txt" if with_postgres else "requirements.txt"
    print(f"Устанавливаю зависимости ({requirements})...")
    try:
        run(str(venv_python()), "-m", "pip", "install", "--disable-pip-version-check", "-r", str(ROOT / requirements))
    except subprocess.CalledProcessError:
        sys.exit("Не удалось установить зависимости — проверьте подключение к интернету и запустите install.py снова.")


def main() -> None:
    # в консоли не с UTF-8 (перенаправление вывода, часть IDE) русский текст не должен ронять установщик
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")

    if sys.version_info < MIN_PYTHON:
        sys.exit(f"Нужен Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+, а запущен {sys.version.split()[0]}. "
                 f"Скачать: https://www.python.org/downloads/")

    print("Установка OWMixDiscordBot\n")
    database_url = configure_env()
    install_dependencies(with_postgres=needs_postgres_driver(database_url))

    launcher = "start.bat" if os.name == "nt" else "bash start.sh"
    print(f"\nУстановка завершена. Запуск бота: {launcher}")
    print("Не забудьте пригласить бота на сервер и включить Message Content Intent — см. README, раздел «Быстрый старт».")


if __name__ == "__main__":
    main()
