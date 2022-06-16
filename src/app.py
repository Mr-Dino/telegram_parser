from telethon.sync import TelegramClient
from telethon.tl.functions.users import GetFullUserRequest
from collections import defaultdict
from telethon.tl.types import PeerChannel

import asyncio
import os
import yaml
import asyncpg
import threading


loop = asyncio.get_event_loop()

try:
    with open(os.getenv('CONFIG_PATH', '../config/config.yaml')) as f:
        config = yaml.safe_load(f)
except Exception as e:
    print(e)
    print("Config file does not exist")


async def main(url):
    client, db_conn = await connect()
    channel = await client.get_entity(url)
    users_messages = await get_users_messages_count(client, channel)
    spammers = find_spammers(users_messages)
    await insert_users(spammers, client, db_conn)
    await disconnect(client, db_conn)


async def connect():
    """Функция подключения к БД и Telegram"""
    db_conn = await asyncpg.connect(
        user=config['PG']['user'],
        password=config['PG']['password'],
        database=config['PG']['database'],
        host=config['PG']['host'],
        port=config['PG']['port']
    )
    client = TelegramClient(
        config['TELEGRAM']['session_name'],
        config['TELEGRAM']['api_id'],
        config['TELEGRAM']['api_hash'],
        loop=loop
    )
    await client.connect()
    return client, db_conn


async def get_users_messages_count(client, channel):
    """Функция для получения списка пользователей с сообщениями и их кол-вом"""
    users_messages = defaultdict(lambda: defaultdict(int))
    posts = await client.get_messages(channel, limit=50)
    for post in posts:
        if post.replies and post.replies.replies != 0:
            async for message in client.iter_messages(channel, reply_to=post.id):
                if message.from_id and not isinstance(message.from_id, PeerChannel):
                    users_messages[message.from_id.user_id][hash(message.text)] += 1
    return users_messages


async def disconnect(client, db_conn):
    """Функция отключения клиента Telegram и от БД postgres"""
    await db_conn.close()
    await client.disconnect()


async def insert_users(users_list, client, db_conn):
    """Функция добавления спамящих пользователей в БД"""
    for user in users_list:
        user_info = await client(GetFullUserRequest(user))
        command = '''INSERT INTO spam_users (first_name, last_name, phone, user_id, is_avatar, region) VALUES ($1, $2, $3, $4, $5, $6);'''
        values = [
            user_info.user.first_name,
            user_info.user.last_name,
            user_info.user.phone,
            user_info.user.id,
            True if user_info.user.photo else False,
            user_info.settings.geo_distance
        ]
        try:
            await db_conn.execute(command, *values)
        except Exception as err:
            print(err)


def find_spammers(users_list):
    """Функция нахождения пользователей, отправляющих одинаковое сообщение больше N раз (N - устанавливается)"""
    spammers = []
    for user in users_list:
        for message in users_list[user]:
            if users_list[user][message] > config['SPAM_MORE']:
                spammers.append(user)
                break
    return spammers


def go():
    asyncio.run(main(config['TELEGRAM']['urls']['first_url']))


if __name__ == '__main__':
    threading.Thread(target=go).start()
