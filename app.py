import telebot
import sqlite3
import random
import time
import threading
import os
from flask import Flask

# ========== НАСТРОЙКИ ==========
TOKEN = '8737616518:AAGg7qupCISz6q_P0JP_UQ7-nrtTHzo3NsA'   # Ваш токен
GROUP_ID = -1003764086901                                 # ID группы (с минусом)
# ================================

# --- Веб-сервер для Render ---
server = Flask(__name__)

@server.route('/')
def health_check():
    return "Bot is running!", 200

def run_flask():
    server.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))

threading.Thread(target=run_flask).start()

# --- Бот ---
bot = telebot.TeleBot(TOKEN)

# Сброс вебхука и очереди обновлений (чтобы избежать конфликта)
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

# --- База данных (SQLite) ---
conn = sqlite3.connect('support.db', check_same_thread=False)
c = conn.cursor()

# Таблица пользователей
c.execute('''
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        topic_id INTEGER,
        code TEXT,
        banned_by_admin INTEGER DEFAULT 0
    )
''')
# Таблица тех, кто заблокировал бота
c.execute('''
    CREATE TABLE IF NOT EXISTS blocked_bot (
        user_id INTEGER PRIMARY KEY
    )
''')
# Таблица настроек (для general topic)
c.execute('''
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )
''')
conn.commit()

# Проверяем и добавляем недостающие колонки (миграция)
c.execute("PRAGMA table_info(users)")
columns = [col[1] for col in c.fetchall()]
if 'banned_by_admin' not in columns:
    c.execute('ALTER TABLE users ADD COLUMN banned_by_admin INTEGER DEFAULT 0')
    conn.commit()
if 'code' not in columns:
    c.execute('ALTER TABLE users ADD COLUMN code TEXT')
    conn.commit()
if 'topic_id' not in columns:
    c.execute('ALTER TABLE users ADD COLUMN topic_id INTEGER')
    conn.commit()

print("✅ База данных инициализирована")

# --- Функции для работы с БД ---
def generate_code():
    return str(random.randint(100000000, 999999999))

def get_user(user_id):
    c.execute('SELECT topic_id, code, banned_by_admin FROM users WHERE user_id = ?', (user_id,))
    row = c.fetchone()
    return row

def save_user(user_id, topic_id, code):
    c.execute('INSERT OR REPLACE INTO users (user_id, topic_id, code, banned_by_admin) VALUES (?, ?, ?, COALESCE((SELECT banned_by_admin FROM users WHERE user_id = ?), 0))',
              (user_id, topic_id, code, user_id))
    conn.commit()

def get_user_by_code(code):
    c.execute('SELECT user_id, topic_id FROM users WHERE code = ?', (code,))
    return c.fetchone()

def set_ban_admin(user_id, banned):
    c.execute('UPDATE users SET banned_by_admin = ? WHERE user_id = ?', (banned, user_id))
    conn.commit()

def record_blocked_bot(user_id):
    c.execute('INSERT OR IGNORE INTO blocked_bot (user_id) VALUES (?)', (user_id,))
    conn.commit()

def is_bot_blocked(user_id):
    c.execute('SELECT 1 FROM blocked_bot WHERE user_id = ?', (user_id,))
    return c.fetchone() is not None

def get_stats():
    # Всего пользователей
    c.execute('SELECT COUNT(*) FROM users')
    total_users = c.fetchone()[0]
    # Заблокировали бота (кто нажал блокировку)
    c.execute('SELECT COUNT(*) FROM blocked_bot')
    blocked_bot_count = c.fetchone()[0]
    # Забаненные администратором
    c.execute('SELECT COUNT(*) FROM users WHERE banned_by_admin = 1')
    banned_by_admin_count = c.fetchone()[0]
    # Чистые = всего - (заблокировали бота + забаненные админом)
    pure_users = total_users - (blocked_bot_count + banned_by_admin_count)
    return total_users, blocked_bot_count, banned_by_admin_count, pure_users

def get_or_create_general_topic():
    c.execute('SELECT value FROM settings WHERE key = "general_topic_id"')
    row = c.fetchone()
    if row:
        return int(row[0])
    try:
        topic = bot.create_forum_topic(GROUP_ID, "general")
        topic_id = topic.message_thread_id
        c.execute('REPLACE INTO settings (key, value) VALUES (?, ?)', ('general_topic_id', str(topic_id)))
        conn.commit()
        return topic_id
    except Exception as e:
        print("Не удалось создать general топик:", e)
        return None

# --- Обработчик блокировки бота пользователем ---
@bot.my_chat_member_handler()
def handle_user_block(message):
    old = message.old_chat_member
    new = message.new_chat_member
    if old.status != 'kicked' and new.status == 'kicked':
        user_id = message.chat.id
        record_blocked_bot(user_id)
        # Логируем в general
        general_id = get_or_create_general_topic()
        if general_id:
            # Получаем код пользователя, если есть
            c.execute('SELECT code FROM users WHERE user_id = ?', (user_id,))
            row = c.fetchone()
            code = row[0] if row else "неизвестен"
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

@bot.message_handler(func=lambda m: m.chat.id == GROUP_ID and m.message_thread_id)
def reply_to_user(message):
    if message.text and message.text.startswith('/'):
        return
    topic_id = message.message_thread_id
    c.execute('SELECT user_id FROM users WHERE topic_id = ?', (topic_id,))
    row = c.fetchone()
    if not row:
        return
    user_id = row[0]
    try:
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

@bot.message_handler(commands=['ban'])
def ban_user(message):
    if message.chat.id != GROUP_ID:
        return
    user_id = None
    if message.reply_to_message:
        topic_id = message.reply_to_message.message_thread_id
        if topic_id:
            c.execute('SELECT user_id FROM users WHERE topic_id = ?', (topic_id,))
            row = c.fetchone()
            if row:
                user_id = row[0]
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
            c.execute('SELECT code FROM users WHERE user_id = ?', (user_id,))
            row = c.fetchone()
            code = row[0] if row else "неизвестен"
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
            c.execute('SELECT user_id FROM users WHERE topic_id = ?', (topic_id,))
            row = c.fetchone()
            if row:
                user_id = row[0]
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
            c.execute('SELECT code FROM users WHERE user_id = ?', (user_id,))
            row = c.fetchone()
            code = row[0] if row else "неизвестен"
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
