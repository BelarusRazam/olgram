from aiogram import Bot as AioBot, Dispatcher
from aiogram.dispatcher.webhook import WebhookRequestHandler
from aiogram.dispatcher.webhook import SendMessage
from aiogram import exceptions
from aiogram import types
from contextvars import ContextVar
from aiohttp.web_exceptions import HTTPNotFound
from aioredis.commands import create_redis_pool
from aioredis import Redis
from tortoise.expressions import F
import logging
import typing as ty
from olgram.settings import ServerSettings
from olgram.models.models import Bot, GroupChat, BannedUser
from locales.locale import _
from server.inlines import inline_handler

_logger = logging.getLogger(__name__)
_logger.setLevel(logging.INFO)

db_bot_instance: ContextVar[Bot] = ContextVar('db_bot_instance')

_redis: ty.Optional[Redis] = None


async def init_redis():
    global _redis
    _redis = await create_redis_pool(ServerSettings.redis_path())


def _message_unique_id(bot_id: int, message_id: int) -> str:
    return f"{bot_id}_{message_id}"


def _thread_uniqie_id(bot_id: int, chat_id: int) -> str:
    return f"thread_{bot_id}_{chat_id}"


def _on_security_policy(message: types.Message, bot):
    text = _("<b>Политика конфиденциальности</b>\n\n"
             "Этот бот не хранит ваши сообщения, имя пользователя и @username. При отправке сообщения (кроме команд "
             "/start и /security_policy) ваш идентификатор пользователя записывается в кеш на некоторое время и потом "
             "удаляется из кеша. Этот идентификатор используется только для общения с оператором; боты Olgram "
             "не делают массовых рассылок.\n\n")
    if bot.enable_additional_info:
        text += _("При отправке сообщения (кроме команд /start и /security_policy) оператор <b>видит</b> ваши имя "
                  "пользователя, @username и идентификатор пользователя в силу настроек, которые оператор указал при "
                  "создании бота.")
    else:
        text += _("В зависимости от ваших настроек конфиденциальности Telegram, оператор может видеть ваш username, "
                  "имя пользователя и другую информацию.")

    return SendMessage(chat_id=message.chat.id,
                       text=text,
                       parse_mode="HTML")


async def send_user_message(message: types.Message, super_chat_id: int, bot):
    """Переслать сообщение от пользователя, добавлять к нему user info при необходимости"""
    if bot.enable_additional_info:
        user_info = _("Сообщение от пользователя ")
        user_info += message.from_user.full_name
        if message.from_user.username:
            user_info += " | @" + message.from_user.username
        user_info += f" | #{message.from_user.id}"
        new_message = await message.bot.send_message(super_chat_id, text=user_info)
        await _redis.set(_message_unique_id(bot.pk, new_message.message_id), message.chat.id,
                         pexpire=ServerSettings.redis_timeout_ms())
        new_message_2 = await message.copy_to(super_chat_id, reply_to_message_id=new_message.message_id)
        await _redis.set(_message_unique_id(bot.pk, new_message_2.message_id), message.chat.id,
                         pexpire=ServerSettings.redis_timeout_ms())
        return new_message
    else:
        new_message = await message.forward(super_chat_id)
        await _redis.set(_message_unique_id(bot.pk, new_message.message_id), message.chat.id,
                         pexpire=ServerSettings.redis_timeout_ms())
        return new_message


async def handle_user_message(message: types.Message, super_chat_id: int, bot):
    """Обычный пользователь прислал сообщение в бот, нужно переслать его операторам"""
    is_super_group = super_chat_id < 0

    # Проверить, не забанен ли пользователь
    banned = await bot.banned_users.filter(telegram_id=message.chat.id)
    if banned:
        return SendMessage(chat_id=message.chat.id,
                           text=_("Вы заблокированы в этом боте"))

    # Пересылаем сообщение в супер-чат
    if is_super_group and bot.enable_threads:
        thread_first_message = await _redis.get(_thread_uniqie_id(bot.pk, message.chat.id))
        if thread_first_message:
            # переслать в супер-чат, отвечая на предыдущее сообщение
            try:
                new_message = await message.copy_to(super_chat_id, reply_to_message_id=int(thread_first_message))
                await _redis.set(_message_unique_id(bot.pk, new_message.message_id), message.chat.id,
                                 pexpire=ServerSettings.redis_timeout_ms())
            except exceptions.BadRequest:
                new_message = await send_user_message(message, super_chat_id, bot)
                await _redis.set(_thread_uniqie_id(bot.pk, message.chat.id), new_message.message_id,
                                 pexpire=ServerSettings.thread_timeout_ms())
        else:
            # переслать супер-чат
            new_message = await send_user_message(message, super_chat_id, bot)
            await _redis.set(_thread_uniqie_id(bot.pk, message.chat.id), new_message.message_id,
                             pexpire=ServerSettings.thread_timeout_ms())
    else:  # личные сообщения не поддерживают потоки сообщений: простой forward
        await send_user_message(message, super_chat_id, bot)

    bot.incoming_messages_count = F("incoming_messages_count") + 1
    await bot.save(update_fields=["incoming_messages_count"])

    # И отправить пользователю специальный текст, если он указан
    if bot.second_text:
        return SendMessage(chat_id=message.chat.id, text=bot.second_text)


async def handle_operator_message(message: types.Message, super_chat_id: int, bot):
    """Оператор написал что-то, нужно переслать сообщение обратно пользователю, или забанить его и т.д."""
    if message.reply_to_message:
        # В супер-чате кто-то ответил на сообщение пользователя, нужно переслать тому пользователю
        chat_id = await _redis.get(_message_unique_id(bot.pk, message.reply_to_message.message_id))
        if not chat_id:
            chat_id = message.reply_to_message.forward_from_chat
            if not chat_id:
                return SendMessage(chat_id=message.chat.id,
                                   text=_("<i>Невозможно переслать сообщение: автор не найден (сообщение слишком "
                                          "старое?)</i>"),
                                   parse_mode="HTML")
        chat_id = int(chat_id)

        if message.text == "/ban":
            user, create = await BannedUser.get_or_create(telegram_id=chat_id, bot=bot)
            await user.save()
            return SendMessage(chat_id=message.chat.id, text=_("Пользователь заблокирован"))

        if message.text == "/unban":
            banned_user = await bot.banned_users.filter(telegram_id=chat_id).first()
            if not banned_user:
                return SendMessage(chat_id=message.chat.id, text=_("Пользователь не был забанен"))
            else:
                await banned_user.delete()
                return SendMessage(chat_id=message.chat.id, text=_("Пользователь разбанен"))

        try:
            await message.copy_to(chat_id)
        except (exceptions.MessageError, exceptions.Unauthorized):
            await message.reply(_("<i>Невозможно переслать сообщение (автор заблокировал бота?)</i>"),
                                parse_mode="HTML")
            return

        bot.outgoing_messages_count = F("outgoing_messages_count") + 1
        await bot.save(update_fields=["outgoing_messages_count"])

    elif super_chat_id > 0:
        # в супер-чате кто-то пишет сообщение сам себе, только для личных сообщений
        await message.forward(super_chat_id)
        # И отправить пользователю специальный текст, если он указан
        if bot.second_text:
            return SendMessage(chat_id=message.chat.id, text=bot.second_text)


async def message_handler(message: types.Message, *args, **kwargs):
    _logger.info("message handler")
    bot = db_bot_instance.get()

    if message.text and message.text == "/start":
        # На команду start нужно ответить, не пересылая сообщение никуда
        return SendMessage(chat_id=message.chat.id,
                           text=bot.start_text + _(ServerSettings.append_text()))

    if message.text and message.text == "/security_policy":
        # На команду security_policy нужно ответить, не пересылая сообщение никуда
        return _on_security_policy(message, bot)

    super_chat_id = await bot.super_chat_id()

    if message.chat.id != super_chat_id:
        # Это обычный чат
        return await handle_user_message(message, super_chat_id, bot)
    else:
        # Это супер-чат
        return await handle_operator_message(message, super_chat_id, bot)


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


async def receive_inline(inline_query):
    _logger.info("inline handler")
    bot = db_bot_instance.get()
    return await inline_handler(inline_query, bot)


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
        dp.register_inline_handler(receive_inline)

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
