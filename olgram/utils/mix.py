from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup
from aiogram.utils.exceptions import TelegramAPIError

from typing import Optional


async def try_delete_message(message: Message):
    try:
        await message.delete()
    except TelegramAPIError:
        pass


async def edit_or_create(call: CallbackQuery, message: str,
                         reply_markup: Optional[InlineKeyboardMarkup] = None,
                         parse_mode: Optional[str] = None):
    try:
        await call.message.edit_text(message, parse_mode=parse_mode)
        await call.message.edit_reply_markup(reply_markup)
    except TelegramAPIError:  # кнопка устарела
        await call.bot.send_message(call.message.chat.id, text=message, reply_markup=reply_markup,
                                    parse_mode=parse_mode)


def wrap(data: str, max_len: int) -> str:
    if len(data) > max_len:
        data = data[:max_len-4] + "..."
    return data


def button_text_limit(data: str) -> str:
    return wrap(data, 30)
