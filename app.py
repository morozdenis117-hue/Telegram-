import telebot
import sqlite3
import random
import time
import threading
import os
from flask import Flask

# ========== НАСТРОЙКИ ==========
TOKEN = '8737616518:AAGg7qupCISz6q_P0JP_UQ7-nrtTHzo3NsA'
GROUP_ID = -1003764086901
# ================================

# --- Веб-сервер для Render (чтобы не засыпал) ---
server = Flask(__name__)
@server.route('/')
def health():
    return "OK", 200
def run_flask():
    server.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))
threading.Thread(target=run_flask).start()

# --- Бот ---
bot = telebot.TeleBot(TOKEN)
bot.remove_webhook()
time.sleep(1)

# --- База данных ---
conn = sqlite3.connect('support.db', check_same_thread=False)
c = conn.cursor()
c.execute('''CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    topic_id INTEGER,
    code TEXT,
    banned INTEGER DEFAULT 0
)''')
c.execute('''CREATE TABLE IF NOT EXISTS blocked_bot (
    user_id INTEGER PRIMARY KEY
)''')
c.execute('''CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
)''')
conn.commit()

# --- Функции ---
def gen_code():
    return str(random.randint(100000000, 999999999))

def get_user(user_id):
    c.execute('SELECT topic_id, code, banned FROM users WHERE user_id = ?', (user_id,))
    return c.fetchone()

def save_user(user_id, topic_id, code):
    c.execute('INSERT OR REPLACE INTO users (user_id, topic_id, code, banned) VALUES (?, ?, ?, COALESCE((SELECT banned FROM users WHERE user_id = ?), 0))', (user_id, topic_id, code, user_id))
    conn.commit()

def get_user_by_code(code):
    c.execute('SELECT user_id FROM users WHERE code = ?', (code,))
    row = c.fetchone()
    return row[0] if row else None

def set_ban(user_id, banned):
    c.execute('UPDATE users SET banned = ? WHERE user_id = ?', (banned, user_id))
    conn.commit()

def add_blocked_bot(user_id):
    c.execute('INSERT OR IGNORE INTO blocked_bot (user_id) VALUES (?)', (user_id,))
    conn.commit()

def get_stats():
    total = c.execute('SELECT COUNT(*) FROM users').fetchone()[0]
    blocked_bot = c.execute('SELECT COUNT(*) FROM blocked_bot').fetchone()[0]
    banned_admin = c.execute('SELECT COUNT(*) FROM users WHERE banned = 1').fetchone()[0]
    pure = total - (blocked_bot + banned_admin)
    return total, blocked_bot, banned_admin, pure

def get_or_create_general_topic():
    c.execute('SELECT value FROM settings WHERE key = "general_topic_id"')
    row = c.fetchone()
    if row:
        return int(row[0])
    topic = bot.create_forum_topic(GROUP_ID, "general")
    c.execute('REPLACE INTO settings (key, value) VALUES (?, ?)', ('general_topic_id', str(topic.message_thread_id)))
    conn.commit()
    return topic.message_thread_id

# --- Обработчик блокировки бота пользователем ---
@bot.my_chat_member_handler()
def on_user_block(message):
    if message.old_chat_member.status != 'kicked' and message.new_chat_member.status == 'kicked':
        add_blocked_bot(message.chat.id)
        general = get_or_create_general_topic()
        bot.send_message(GROUP_ID, f"🚫 Пользователь #{message.chat.id} заблокировал бота.", message_thread_id=general)

# --- Команды ---
@bot.message_handler(commands=['start'])
def start_cmd(m):
    if m.chat.type == 'private':
        bot.send_message(m.chat.id, "Привет! Напишите что-нибудь, мы ответим анонимно.")

@bot.message_handler(commands=['stats'])
def stats_cmd(m):
    if m.chat.id != GROUP_ID:
        return
    total, blocked_bot, banned_admin, pure = get_stats()
    bot.send_message(GROUP_ID, f"📊 Статистика:\nВсего: {total}\nЗаблокировали бота: {blocked_bot}\nЗабанено админом: {banned_admin}\nЧистых: {pure}")

# --- Пересылка сообщений от пользователя в группу ---
@bot.message_handler(func=lambda m: m.chat.type == 'private' and m.text != '/start')
def forward_to_group(m):
    user_id = m.chat.id
    row = get_user(user_id)
    if not row:
        code = gen_code()
        topic_name = f"#{code}"
        topic = bot.create_forum_topic(GROUP_ID, topic_name)
        topic_id = topic.message_thread_id
        save_user(user_id, topic_id, code)
    else:
        topic_id, code, banned = row
        if banned:
            bot.send_message(user_id, "❌ Вы заблокированы.")
            return
    # Гарантированная пересылка любого медиа через forward_message
    # Но forward показывает имя отправителя – чтобы скрыть, используем copy_message, а если не работает – forward.
    try:
        bot.copy_message(GROUP_ID, user_id, m.message_id, message_thread_id=topic_id)
    except:
        # fallback: пересылаем как есть, но в группе увидит "Переслано от..."
        bot.forward_message(GROUP_ID, user_id, m.message_id, message_thread_id=topic_id)

# --- Ответ оператора в топике ---
@bot.message_handler(func=lambda m: m.chat.id == GROUP_ID and m.message_thread_id and not m.text.startswith('/'))
def reply_to_user(m):
    topic_id = m.message_thread_id
    c.execute('SELECT user_id FROM users WHERE topic_id = ?', (topic_id,))
    row = c.fetchone()
    if not row:
        return
    user_id = row[0]
    try:
        if m.text:
            bot.send_message(user_id, m.text)
        elif m.photo:
            bot.send_photo(user_id, m.photo[-1].file_id, caption=m.caption)
        elif m.video:
            bot.send_video(user_id, m.video.file_id, caption=m.caption)
        elif m.document:
            bot.send_document(user_id, m.document.file_id, caption=m.caption)
        elif m.voice:
            bot.send_voice(user_id, m.voice.file_id)
        elif m.audio:
            bot.send_audio(user_id, m.audio.file_id, caption=m.caption)
        elif m.sticker:
            bot.send_sticker(user_id, m.sticker.file_id)
        elif m.video_note:
            bot.send_video_note(user_id, m.video_note.file_id)
        else:
            bot.send_message(user_id, "Сообщение не поддерживается")
    except Exception as e:
        print("Ошибка ответа:", e)

# --- Бан / разбан ---
@bot.message_handler(commands=['ban'])
def ban_cmd(m):
    if m.chat.id != GROUP_ID:
        return
    uid = None
    if m.reply_to_message:
        tid = m.reply_to_message.message_thread_id
        if tid:
            c.execute('SELECT user_id FROM users WHERE topic_id = ?', (tid,))
            r = c.fetchone()
            if r:
                uid = r[0]
    if not uid and len(m.text.split()) > 1:
        code = m.text.split()[1]
        uid = get_user_by_code(code)
    if uid:
        set_ban(uid, 1)
        bot.reply_to(m, "✅ Забанен")
        general = get_or_create_general_topic()
        bot.send_message(GROUP_ID, f"🔨 Забанен пользователь #{code if 'code' in locals() else uid}", message_thread_id=general)
        try:
            bot.send_message(uid, "❌ Вы заблокированы администратором.")
        except:
            pass
    else:
        bot.reply_to(m, "❌ Не найден. Укажите код или ответьте на сообщение.")

@bot.message_handler(commands=['unban'])
def unban_cmd(m):
    if m.chat.id != GROUP_ID:
        return
    uid = None
    if m.reply_to_message:
        tid = m.reply_to_message.message_thread_id
        if tid:
            c.execute('SELECT user_id FROM users WHERE topic_id = ?', (tid,))
            r = c.fetchone()
            if r:
                uid = r[0]
    if not uid and len(m.text.split()) > 1:
        code = m.text.split()[1]
        uid = get_user_by_code(code)
    if uid:
        set_ban(uid, 0)
        bot.reply_to(m, "✅ Разбанен")
        general = get_or_create_general_topic()
        bot.send_message(GROUP_ID, f"🔓 Разбанен пользователь #{code if 'code' in locals() else uid}", message_thread_id=general)
        try:
            bot.send_message(uid, "✅ Вы разблокированы.")
        except:
            pass
    else:
        bot.reply_to(m, "❌ Не найден.")

print("✅ Бот запущен")
bot.infinity_polling()
