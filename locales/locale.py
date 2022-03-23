import gettext
from olgram.settings import BotSettings
from os.path import dirname

locales_dir = dirname(__file__)


def dummy_translator(x: str) -> str:
    return x


lang = BotSettings.language()
if lang == "ru":
    _ = dummy_translator
else:
    t = gettext.translation("olgram", localedir=locales_dir, languages=[lang])
    _ = t.gettext
