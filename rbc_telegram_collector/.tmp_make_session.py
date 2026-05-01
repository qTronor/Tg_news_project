import os
import asyncio
from telethon import TelegramClient
from telethon.sessions import StringSession

async def main():
    async with TelegramClient(
        StringSession(),
        int(os.environ["TG_API_ID"]),
        os.environ["TG_API_HASH"],
    ) as client:
        print("\nTG_STRING_SESSION=" + client.session.save() + "\n")

asyncio.run(main())
