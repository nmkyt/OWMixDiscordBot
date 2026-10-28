#!/usr/bin/env bash
cd "$(dirname "$0")" || exit 1
if [ ! -x venv/bin/python ]; then
    echo "The bot is not installed yet. Run first: python3 install.py"
    exit 1
fi
exec venv/bin/python -m src.bot_controller
