# tg_bot_runner.py
import os
import threading
import time
import telebot
from telebot import types

# Читаем конфиг из env
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

def _set_menu_button(bot):
    # Кнопка в нижнем меню бота — открывает WebApp
    btn = types.MenuButtonWebApp(text="Играть", web_app=types.WebAppInfo(url=WEBAPP_URL))
    bot.set_chat_menu_button(menu_button=btn)

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
    # Пытаемся держать бот в онлайне (перезапуск при сетевых сбоях)
    _set_menu_button(bot)
    while True:
        try:
            bot.infinity_polling(skip_pending=True, timeout=60, long_polling_timeout=50)
        except Exception as e:
            print(f"[TG BOT] polling error: {e}")
            time.sleep(5)


def start_bot_if_enabled(app):
    """Запускает бот в отдельном потоке, если есть токен"""
    global _bot, _thread, _started
    if _started or not BOT_TOKEN:
        return
    
    try:
        _bot = _build_bot()
        _register_handlers(_bot)
        _thread = threading.Thread(target=_polling_loop, args=(_bot,), daemon=True)
        _thread.start()
        _started = True
        print(f"[TG BOT] Started bot @{BOT_USER}")
    except Exception as e:
        print(f"[TG BOT] Failed to start: {e}")