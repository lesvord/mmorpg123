# tg_bot_runner.py
import os
import threading
import time
import telebot
from telebot import types

BOT_TOKEN  = os.getenv("TG_BOT_TOKEN", "8134690532:AAETe0Hgj8rjrKBU4fpVhFcfgqqOjMMryhI")
BOT_USER   = os.getenv("TG_BOT_USERNAME", "flirtmod_bot")  # без @, напр. flirtmod_bot
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://95.164.23.186.sslip.io/accounts/tg/start")

_bot = None
_thread = None
_started = False

def _build_bot():
    if not BOT_TOKEN:
        raise RuntimeError("TG_BOT_TOKEN is empty. Set it in env.")
    bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")
    return bot

def _build_menu_button() -> types.MenuButtonWebApp | None:
    """
    Совместимое создание MenuButtonWebApp для разных версий pyTelegramBotAPI.
    """
    wai = types.WebAppInfo(url=WEBAPP_URL)
    try:
        # Новые версии принимают именованные аргументы
        return types.MenuButtonWebApp(type="web_app", text="Играть", web_app=wai)
    except TypeError:
        try:
            # Старые версии — позиционные аргументы
            return types.MenuButtonWebApp("web_app", "Играть", wai)
        except TypeError:
            return None

def _set_menu_button(bot):
    btn = _build_menu_button()
    if btn:
        try:
            bot.set_chat_menu_button(menu_button=btn)
        except TypeError:
            # некоторые версии принимают без имени параметра
            bot.set_chat_menu_button(btn)
    else:
        # если совсем старая версия lib — просто ничего не делаем
        print("[TG BOT] MenuButtonWebApp not supported by your telebot version; skipping set_chat_menu_button")

def _register_handlers(bot):
    @bot.message_handler(commands=["start", "play"])
    def start(m: types.Message):
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton(
            text="🎮 Играть (в Telegram)",
            web_app=types.WebAppInfo(url=WEBAPP_URL)
        ))
        deep_link = f"https://t.me/{os.getenv('TG_BOT_USERNAME','')}" + "?startapp=play"
        kb.add(types.InlineKeyboardButton(text="Открыть в Telegram (deep link)", url=deep_link))
        bot.send_message(m.chat.id, "Добро пожаловать! Жми «Играть».", reply_markup=kb)

    @bot.message_handler(commands=["menu"])
    def menu(m: types.Message):
        _set_menu_button(bot)
        bot.reply_to(m, "Кнопка меню «Играть» установлена.")

def _polling_loop(bot):
    _set_menu_button(bot)
    while True:
        try:
            bot.infinity_polling(skip_pending=True, timeout=60, long_polling_timeout=50)
        except Exception as e:
            print(f"[TG BOT] polling error: {e}. Restarting in 5s...")
            time.sleep(5)

def start_bot_if_enabled(app=None):
    """
    Запускает бота в фоне, если RUN_BOT=1 и заданы TG_BOT_TOKEN/TG_BOT_USERNAME.
    Безопасно для Flask dev reloader: стартуем только в рабочем процессе.
    """
    global _bot, _thread, _started
    if _started:
        return

    run_bot = os.getenv("RUN_BOT", "0") == "1"
    if not run_bot:
        print("[TG BOT] RUN_BOT != 1, бот не запускается.")
        return

    # избежать двойного старта при Werkzeug reloader
    is_child = (os.getenv("WERKZEUG_RUN_MAIN") == "true") or (not os.getenv("WERKZEUG_RUN_MAIN"))
    if app is not None and app.debug and not is_child:
        print("[TG BOT] debug parent process detected, skip.")
        return

    _bot = _build_bot()
    _register_handlers(_bot)

    _thread = threading.Thread(target=_polling_loop, args=(_bot,), daemon=True)
    _thread.start()
    _started = True
    print("[TG BOT] started in background thread.")
