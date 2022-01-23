from aiogram import Bot as AioBot, Dispatcher
from aiogram.dispatcher.webhook import WebhookRequestHandler
from aiogram.dispatcher.webhook import SendMessage
from aiogram import exceptions
from aiogram import types
from contextvars import ContextVar
from aiohttp.web_exceptions import HTTPNotFound
from aioredis.commands import create_redis_pool
from aioredis import Redis
import logging
import typing as ty
from olgram.settings import ServerSettings
from olgram.models.models import Bot, GroupChat, BannedUser


_logger = logging.getLogger(__name__)
_logger.setLevel(logging.INFO)

db_bot_instance: ContextVar[Bot] = ContextVar('db_bot_instance')

_redis: ty.Optional[Redis] = None


async def init_redis():
    global _redis
    _redis = await create_redis_pool(ServerSettings.redis_path())


def _message_unique_id(bot_id: int, message_id: int) -> str:
    return f"{bot_id}_{message_id}"


async def message_handler(message: types.Message, *args, **kwargs):
    _logger.info("message handler")
    bot = db_bot_instance.get()

    if message.text and message.text == "/start":
        # На команду start нужно ответить, не пересылая сообщение никуда
        return SendMessage(chat_id=message.chat.id,
                           text=bot.start_text + ServerSettings.append_text())

    super_chat_id = await bot.super_chat_id()

    if message.chat.id != super_chat_id:
        # Это обычный чат

        # Проверить, не забанен ли пользователь
        banned = await bot.banned_users.filter(telegram_id=message.chat.id)
        if banned:
            return SendMessage(chat_id=message.chat.id,
                               text="Вы заблокированы в этом боте")

        # сообщение нужно переслать в супер-чат
        new_message = await message.forward(super_chat_id)
        await _redis.set(_message_unique_id(bot.pk, new_message.message_id), message.chat.id)

        # И отправить пользователю специальный текст, если он указан
        if bot.second_text:
            return SendMessage(chat_id=message.chat.id, text=bot.second_text)
    else:
        # Это супер-чат

        if message.reply_to_message:
            # В супер-чате кто-то ответил на сообщение пользователя, нужно переслать тому пользователю
            chat_id = await _redis.get(_message_unique_id(bot.pk, message.reply_to_message.message_id))
            if not chat_id:
                chat_id = message.reply_to_message.forward_from_chat
                if not chat_id:
                    return SendMessage(chat_id=message.chat.id,
                                       text="<i>Невозможно переслать сообщение: автор не найден</i>",
                                       parse_mode="HTML")
            chat_id = int(chat_id)

            if message.text == "/ban":
                user, _ = await BannedUser.get_or_create(telegram_id=chat_id, bot=bot)
                await user.save()
                return SendMessage(chat_id=message.chat.id, text="Пользователь заблокирован")

            if message.text == "/unban":
                banned_user = await bot.banned_users.filter(telegram_id=chat_id).first()
                if not banned_user:
                    return SendMessage(chat_id=message.chat.id, text="Пользователь не был забанен")
                else:
                    await banned_user.delete()
                    return SendMessage(chat_id=message.chat.id, text="Пользователь разбанен")

            try:
                await message.copy_to(chat_id)
            except (exceptions.MessageError, exceptions.BotBlocked):
                await message.reply("<i>Невозможно переслать сообщение (автор заблокировал бота?)</i>",
                                    parse_mode="HTML")
                return
        else:
            # в супер-чате кто-то пишет сообщение сам себе
            await message.forward(super_chat_id)
            # И отправить пользователю специальный текст, если он указан
            if bot.second_text:
                return SendMessage(chat_id=message.chat.id, text=bot.second_text)


async def receive_invite(message: types.Message):
    bot = db_bot_instance.get()
    for member in message.new_chat_members:
        if member.id == message.bot.id:
            chat, _ = await GroupChat.get_or_create(chat_id=message.chat.id,
                                                    defaults={"name": message.chat.full_name})
            chat.name = message.chat.full_name
            await chat.save()
            if chat not in await bot.group_chats.all():
                await bot.group_chats.add(chat)
                await bot.save()
            break


async def receive_group_create(message: types.Message):
    bot = db_bot_instance.get()

    chat, _ = await GroupChat.get_or_create(chat_id=message.chat.id,
                                            defaults={"name": message.chat.full_name})
    chat.name = message.chat.full_name
    await chat.save()
    if chat not in await bot.group_chats.all():
        await bot.group_chats.add(chat)
        await bot.save()


async def receive_left(message: types.Message):
    bot = db_bot_instance.get()
    if message.left_chat_member.id == message.bot.id:
        chat = await bot.group_chats.filter(chat_id=message.chat.id).first()
        if chat:
            await bot.group_chats.remove(chat)
            bot_group_chat = await bot.group_chat
            if bot_group_chat == chat:
                bot.group_chat = None
            await bot.save()


async def receive_migrate(message: types.Message):
    bot = db_bot_instance.get()
    from_id = message.chat.id
    to_id = message.migrate_to_chat_id

    chats = await bot.group_chats.filter(chat_id=from_id)
    for chat in chats:
        chat.chat_id = to_id
        await chat.save(update_fields=["chat_id"])


class CustomRequestHandler(WebhookRequestHandler):

    def __init__(self, *args, **kwargs):
        self._dispatcher = None
        super(CustomRequestHandler, self).__init__(*args, **kwargs)

    async def _create_dispatcher(self):
        key = self.request.url.path[1:]

        bot = await Bot.filter(code=key).first()
        if not bot:
            return None
        db_bot_instance.set(bot)
        dp = Dispatcher(AioBot(bot.decrypted_token()))

        dp.register_message_handler(message_handler, content_types=[types.ContentType.TEXT,
                                                                    types.ContentType.CONTACT,
                                                                    types.ContentType.ANIMATION,
                                                                    types.ContentType.AUDIO,
                                                                    types.ContentType.DOCUMENT,
                                                                    types.ContentType.PHOTO,
                                                                    types.ContentType.STICKER,
                                                                    types.ContentType.VIDEO,
                                                                    types.ContentType.VOICE])
        dp.register_message_handler(receive_invite, content_types=[types.ContentType.NEW_CHAT_MEMBERS])
        dp.register_message_handler(receive_left, content_types=[types.ContentType.LEFT_CHAT_MEMBER])
        dp.register_message_handler(receive_migrate, content_types=[types.ContentType.MIGRATE_TO_CHAT_ID])
        dp.register_message_handler(receive_group_create, content_types=[types.ContentType.GROUP_CHAT_CREATED])

        return dp

    async def post(self):
        dispatcher = await self._create_dispatcher()
        if not dispatcher:
            raise HTTPNotFound()

        Dispatcher.set_current(dispatcher)
        AioBot.set_current(dispatcher.bot)
        return await super(CustomRequestHandler, self).post()

    def get_dispatcher(self):
        """
        Get Dispatcher instance from environment

        :return: :class:`aiogram.Dispatcher`
        """
        return Dispatcher.get_current()
