from __future__ import annotations

import argparse
import asyncio
import os

from telethon import TelegramClient
from telethon.sessions import StringSession

from collector.runner import run_collect


def cmd_collect(args: argparse.Namespace) -> int:
    return run_collect(args.config)


async def _make_string_session(api_id: int, api_hash: str) -> str:
    async with TelegramClient(StringSession(), api_id, api_hash) as client:
        # first run will ask for phone + code, then returns string session
        return client.session.save()


def cmd_make_session(_: argparse.Namespace) -> int:
    api_id = os.getenv("TG_API_ID")
    api_hash = os.getenv("TG_API_HASH")
    if not api_id or not api_hash:
        raise SystemExit("Set TG_API_ID and TG_API_HASH first.")
    s = asyncio.run(_make_string_session(int(api_id), api_hash))
    print("\nTG_STRING_SESSION=" + s + "\n")
    print("Сохраните это значение в переменную окружения TG_STRING_SESSION (и держите в секрете).")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="collector", description="Telegram channel collector (Telethon)")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_collect = sub.add_parser("collect", help="Collect posts from channels in config.yaml")
    p_collect.add_argument("--config", default="config.yaml")
    p_collect.set_defaults(func=cmd_collect)

    p_sess = sub.add_parser("make-session", help="Generate TG_STRING_SESSION interactively")
    p_sess.set_defaults(func=cmd_make_session)

    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
