import aiogram.types as types
from aiogram.dispatcher.handler import CancelHandler, current_handler
from aiogram.dispatcher.middlewares import BaseMiddleware
from locales.locale import _


def public():
    """
    Хендлеры с этим декоратором будут обрабатываться даже если пользователь не является владельцем бота
    (например, команда /help)
    :return:
    """

    def decorator(func):
        setattr(func, "access_public", True)
        return func

    return decorator


class AccessMiddleware(BaseMiddleware):
    def __init__(self, access_chat_id: int):
        self._access_chat_id = access_chat_id
        super(AccessMiddleware, self).__init__()

    @classmethod
    def _is_public_command(cls) -> bool:
        handler = current_handler.get()
        return handler and getattr(handler, "access_public", False)

    async def on_process_message(self, message: types.Message, data: dict):
        admin_id = self._access_chat_id
        if not admin_id:
            return  # Администратор бота вообще не указан

        if self._is_public_command():  # Эта команда разрешена всем пользователям
            return

        if message.chat.id != admin_id:
            await message.answer(_("Владелец бота ограничил доступ к этому функционалу 😞"))
            raise CancelHandler()

    async def on_process_callback_query(self, call: types.CallbackQuery, data: dict):
        admin_id = self._access_chat_id
        if not admin_id:
            return  # Администратор бота вообще не указан

        if self._is_public_command():  # Эта команда разрешена всем пользователям
            return

        if call.message.chat.id != admin_id:
            await call.answer(_("Владелец бота ограничил доступ к этому функционалу😞"))
            raise CancelHandler()
