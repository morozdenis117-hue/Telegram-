import telebot
import sqlite3
import random
import time
import threading
import os
from flask import Flask
from supabase import create_client, Client

# --- НАСТРОЙКИ ---
TOKEN = '8737616518:AAGg7qupCISz6q_P0JP_UQ7-nrtTHzo3NsA'
GROUP_ID = -1003764086901

# ДАННЫЕ ДЛЯ ПОДКЛЮЧЕНИЯ К БАЗЕ (из шага 2)
SUPABASE_URL = 'https://lkhuotwwiirhpxvtvyua.supabase.co'   # Ваш Project URL
SUPABASE_KEY = ''               # Ваш anon public key
# -----------------

# --- Веб-сервер для Render ---
server = Flask(__name__)

@server.route('/')
def health_check():
    return "Bot is running!", 200

def run_flask():
    server.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))

threading.Thread(target=run_flask).start()

# --- Бот и База Данных ---
bot = telebot.TeleBot(TOKEN)

# Подключаемся к Supabase
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Удаляем вебхук и сбрасываем обновления
try:
    bot.remove_webhook()
    print("✅ Webhook удалён")
except:
    pass
try:
    bot.get_updates(offset=-1, timeout=1)
    print("✅ Очередь обновлений сброшена")
except:
    pass
time.sleep(1)

print("✅ База данных Supabase подключена")

# --- Функции для работы с Supabase ---
def generate_code():
    return str(random.randint(100000000, 999999999))

def get_user(user_id):
    try:
        result = supabase.table('users').select('topic_id, code, banned').eq('user_id', user_id).execute()
        if result.data:
            row = result.data[0]
            return row['topic_id'], row['code'], row['banned']
        return None
    except Exception as e:
        print("Ошибка get_user:", e)
        return None

def save_user(user_id, topic_id, code):
    try:
        supabase.table('users').upsert({
            'user_id': user_id,
            'topic_id': topic_id,
            'code': code,
            'banned': 0
        }).execute()
    except Exception as e:
        print("Ошибка save_user:", e)

def get_user_by_code(code):
    try:
        result = supabase.table('users').select('user_id, topic_id').eq('code', code).execute()
        if result.data:
            row = result.data[0]
            return row['user_id'], row['topic_id']
        return None
    except Exception as e:
        print("Ошибка get_user_by_code:", e)
        return None

def set_ban_admin(user_id, banned):
    try:
        supabase.table('users').update({'banned': banned}).eq('user_id', user_id).execute()
    except Exception as e:
        print("Ошибка set_ban_admin:", e)

def record_blocked_bot(user_id):
    try:
        supabase.table('blocked_bot').upsert({'user_id': user_id}).execute()
    except Exception as e:
        print("Ошибка record_blocked_bot:", e)

def is_bot_blocked(user_id):
    try:
        result = supabase.table('blocked_bot').select('user_id').eq('user_id', user_id).execute()
        return bool(result.data)
    except Exception as e:
        print("Ошибка is_bot_blocked:", e)
        return False

def get_stats():
    try:
        total_users = supabase.table('users').select('user_id', count='exact').execute().count
        blocked_bot = supabase.table('blocked_bot').select('user_id', count='exact').execute().count
        banned_admin = supabase.table('users').select('user_id', count='exact').eq('banned', 1).execute().count
        pure_users = total_users - (blocked_bot + banned_admin)
        return total_users, blocked_bot, banned_admin, pure_users
    except Exception as e:
        print("Ошибка get_stats:", e)
        return 0, 0, 0, 0

def get_or_create_general_topic():
    try:
        result = supabase.table('settings').select('value').eq('key', 'general_topic_id').execute()
        if result.data:
            return int(result.data[0]['value'])
        topic = bot.create_forum_topic(GROUP_ID, "general")
        topic_id = topic.message_thread_id
        supabase.table('settings').upsert({'key': 'general_topic_id', 'value': str(topic_id)}).execute()
        return topic_id
    except Exception as e:
        print("Ошибка get_or_create_general_topic:", e)
        return None

# --- Обработчик блокировки бота пользователем ---
@bot.my_chat_member_handler()
def handle_user_block(message):
    old = message.old_chat_member
    new = message.new_chat_member
    if old.status != 'kicked' and new.status == 'kicked':
        user_id = message.chat.id
        record_blocked_bot(user_id)
        general_id = get_or_create_general_topic()
        if general_id:
            # Получаем код пользователя, если есть
            result = supabase.table('users').select('code').eq('user_id', user_id).execute()
            code = result.data[0]['code'] if result.data else "неизвестен"
            bot.send_message(GROUP_ID, f"🚫 Пользователь #{code} заблокировал бота.", message_thread_id=general_id)

# --- Обработчики команд ---
@bot.message_handler(commands=['start'])
def start_cmd(message):
    if message.chat.type == 'private':
        bot.send_message(message.chat.id, "Привет! Напишите сообщение, и мы ответим анонимно.")

@bot.message_handler(commands=['stats'])
def stats_cmd(message):
    if message.chat.id != GROUP_ID:
        return
    total, blocked_bot, banned_admin, pure = get_stats()
    text = (f"📊 **Статистика**\n\n"
            f"👥 Всего пользователей: {total}\n"
            f"🚫 Заблокировали бота: {blocked_bot}\n"
            f"🔨 Забанено администратором: {banned_admin}\n"
            f"✅ Чистых пользователей: {pure}")
    bot.send_message(GROUP_ID, text, parse_mode='Markdown')

# --- Пересылка сообщений от пользователя в группу ---
@bot.message_handler(func=lambda m: m.chat.type == 'private' and not m.text == '/start')
def forward_to_group(message):
    user_id = message.chat.id
    row = get_user(user_id)
    if row is None:
        code = generate_code()
        topic_name = f"#{code}"
        try:
            topic = bot.create_forum_topic(GROUP_ID, topic_name)
            topic_id = topic.message_thread_id
            save_user(user_id, topic_id, code)
        except Exception as e:
            print("Ошибка создания топика:", e)
            bot.send_message(user_id, "❌ Техническая ошибка, попробуйте позже.")
            return
    else:
        topic_id, code, banned = row
        if banned == 1:
            bot.send_message(user_id, "❌ Вы заблокированы администратором.")
            return

    try:
        bot.copy_message(GROUP_ID, user_id, message.message_id, message_thread_id=topic_id)
    except Exception as e:
        print("Ошибка copy_message:", e)
        try:
            if message.text:
                bot.send_message(GROUP_ID, message.text, message_thread_id=topic_id)
            elif message.photo:
                bot.send_photo(GROUP_ID, message.photo[-1].file_id, caption=message.caption, message_thread_id=topic_id)
            elif message.video:
                bot.send_video(GROUP_ID, message.video.file_id, caption=message.caption, message_thread_id=topic_id)
            elif message.document:
                bot.send_document(GROUP_ID, message.document.file_id, caption=message.caption, message_thread_id=topic_id)
            elif message.voice:
                bot.send_voice(GROUP_ID, message.voice.file_id, message_thread_id=topic_id)
            elif message.sticker:
                bot.send_sticker(GROUP_ID, message.sticker.file_id, message_thread_id=topic_id)
            elif message.video_note:
                bot.send_video_note(GROUP_ID, message.video_note.file_id, message_thread_id=topic_id)
        except Exception as e2:
            print("Ошибка альтернативной отправки:", e2)

# --- Ответ оператора в топике ---
@bot.message_handler(func=lambda m: m.chat.id == GROUP_ID and m.message_thread_id and not m.text.startswith('/'))
def reply_to_user(message):
    topic_id = message.message_thread_id
    try:
        result = supabase.table('users').select('user_id').eq('topic_id', topic_id).execute()
        if not result.data:
            return
        user_id = result.data[0]['user_id']
        if message.text:
            bot.send_message(user_id, message.text)
        elif message.photo:
            bot.send_photo(user_id, message.photo[-1].file_id, caption=message.caption)
        elif message.video:
            bot.send_video(user_id, message.video.file_id, caption=message.caption)
        elif message.document:
            bot.send_document(user_id, message.document.file_id, caption=message.caption)
        elif message.voice:
            bot.send_voice(user_id, message.voice.file_id)
        elif message.sticker:
            bot.send_sticker(user_id, message.sticker.file_id)
        elif message.video_note:
            bot.send_video_note(user_id, message.video_note.file_id)
    except Exception as e:
        print("Ошибка отправки ответа:", e)

# --- Бан / разбан ---
@bot.message_handler(commands=['ban'])
def ban_user(message):
    if message.chat.id != GROUP_ID:
        return
    user_id = None
    if message.reply_to_message:
        topic_id = message.reply_to_message.message_thread_id
        if topic_id:
            result = supabase.table('users').select('user_id').eq('topic_id', topic_id).execute()
            if result.data:
                user_id = result.data[0]['user_id']
    if not user_id and len(message.text.split()) > 1:
        code = message.text.split()[1]
        row = get_user_by_code(code)
        if row:
            user_id = row[0]
    if user_id:
        set_ban_admin(user_id, 1)
        bot.reply_to(message, "✅ Пользователь заблокирован.")
        general_id = get_or_create_general_topic()
        if general_id:
            result = supabase.table('users').select('code').eq('user_id', user_id).execute()
            code = result.data[0]['code'] if result.data else "неизвестен"
            try:
                user_chat = bot.get_chat(user_id)
                user_name = user_chat.first_name or ""
                if user_chat.last_name:
                    user_name += " " + user_chat.last_name
            except:
                user_name = "Пользователь"
            bot.send_message(GROUP_ID, f"🔨 Администратор заблокировал {user_name} (код #{code}).", message_thread_id=general_id)
        try:
            bot.send_message(user_id, "❌ Вы заблокированы администратором.")
        except:
            pass
    else:
        bot.reply_to(message, "❌ Не найден пользователь. Используйте /ban #код или ответьте на сообщение.")

@bot.message_handler(commands=['unban'])
def unban_user(message):
    if message.chat.id != GROUP_ID:
        return
    user_id = None
    if message.reply_to_message:
        topic_id = message.reply_to_message.message_thread_id
        if topic_id:
            result = supabase.table('users').select('user_id').eq('topic_id', topic_id).execute()
            if result.data:
                user_id = result.data[0]['user_id']
    if not user_id and len(message.text.split()) > 1:
        code = message.text.split()[1]
        row = get_user_by_code(code)
        if row:
            user_id = row[0]
    if user_id:
        set_ban_admin(user_id, 0)
        bot.reply_to(message, "✅ Пользователь разблокирован.")
        general_id = get_or_create_general_topic()
        if general_id:
            result = supabase.table('users').select('code').eq('user_id', user_id).execute()
            code = result.data[0]['code'] if result.data else "неизвестен"
            try:
                user_chat = bot.get_chat(user_id)
                user_name = user_chat.first_name or ""
                if user_chat.last_name:
                    user_name += " " + user_chat.last_name
            except:
                user_name = "Пользователь"
            bot.send_message(GROUP_ID, f"🔓 Администратор разблокировал {user_name} (код #{code}).", message_thread_id=general_id)
        try:
            bot.send_message(user_id, "✅ Вы разблокированы.")
        except:
            pass
    else:
        bot.reply_to(message, "❌ Не найден пользователь. Используйте /unban #код или ответьте на сообщение.")

print("✅ Бот запущен. Группа:", GROUP_ID)
bot.infinity_polling()
