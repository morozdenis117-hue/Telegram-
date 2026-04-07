import sys
import traceback
import time

try:
    import telebot
    import sqlite3
    import random
    import threading
    import os
    from flask import Flask
except Exception as e:
    print("Ошибка импорта:", e)
    traceback.print_exc()
    sys.exit(1)

try:
    # ========== НАСТРОЙКИ ==========
    TOKEN = '8737616518:AAGg7qupCISz6q_P0JP_UQ7-nrtTHzo3NsA'
    GROUP_ID = -1003764086901
    # ================================

    # --- Принудительно удаляем вебхук и сбрасываем обновления ---
    bot = telebot.TeleBot(TOKEN)
    try:
        bot.remove_webhook()  # удаляем вебхук
        print("✅ Webhook удалён")
    except:
        pass
    # Сбрасываем getUpdates (чтобы не было конфликта)
    try:
        bot.get_updates(offset=-1, timeout=1)
        print("✅ Очередь обновлений сброшена")
    except:
        pass
    time.sleep(1)  # небольшая пауза

    # --- Веб-сервер для Render ---
    server = Flask(__name__)

    @server.route('/')
    def health_check():
        return "Bot is running!", 200

    def run_flask():
        server.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))

    threading.Thread(target=run_flask).start()

    # ----- База данных -----
    conn = sqlite3.connect('support.db', check_same_thread=False)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            topic_id INTEGER,
            code TEXT,
            banned INTEGER DEFAULT 0
        )
    ''')
    conn.commit()

    c.execute("PRAGMA table_info(users)")
    columns = [col[1] for col in c.fetchall()]
    if 'code' not in columns:
        c.execute('ALTER TABLE users ADD COLUMN code TEXT')
        conn.commit()
    if 'banned' not in columns:
        c.execute('ALTER TABLE users ADD COLUMN banned INTEGER DEFAULT 0')
        conn.commit()

    c.execute('CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)')
    conn.commit()

    print("✅ База данных инициализирована")

    # ----- Функции (без изменений) -----
    def generate_code():
        return str(random.randint(100000000, 999999999))

    def get_user(user_id):
        c.execute('SELECT topic_id, code, banned FROM users WHERE user_id = ?', (user_id,))
        return c.fetchone()

    def save_user(user_id, topic_id, code):
        c.execute('REPLACE INTO users (user_id, topic_id, code, banned) VALUES (?, ?, ?, COALESCE((SELECT banned FROM users WHERE user_id = ?), 0))',
                  (user_id, topic_id, code, user_id))
        conn.commit()

    def get_user_by_code(code):
        c.execute('SELECT user_id, topic_id FROM users WHERE code = ?', (code,))
        return c.fetchone()

    def set_ban(user_id, banned):
        c.execute('UPDATE users SET banned = ? WHERE user_id = ?', (banned, user_id))
        conn.commit()

    general_topic_id = None
    def get_or_create_general_topic():
        global general_topic_id
        if general_topic_id:
            return general_topic_id
        c.execute('SELECT value FROM settings WHERE key = "general_topic_id"')
        row = c.fetchone()
        if row:
            general_topic_id = int(row[0])
            return general_topic_id
        try:
            topic = bot.create_forum_topic(GROUP_ID, "general")
            general_topic_id = topic.message_thread_id
            c.execute('REPLACE INTO settings (key, value) VALUES (?, ?)', ('general_topic_id', str(general_topic_id)))
            conn.commit()
        except Exception as e:
            print("Не удалось создать general топик:", e)
        return general_topic_id

    # ----- Обработчики (без изменений) -----
    @bot.message_handler(commands=['start'])
    def start_cmd(message):
        if message.chat.type == 'private':
            bot.send_message(message.chat.id, "Привет! Напишите сообщение, и мы ответим анонимно.")

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
                return
        else:
            topic_id, code, banned = row
            if banned == 1:
                bot.send_message(user_id, "❌ Вы заблокированы.")
                return
        try:
            bot.copy_message(GROUP_ID, user_id, message.message_id, message_thread_id=topic_id)
        except Exception as e:
            print("Ошибка копирования:", e)

    @bot.message_handler(func=lambda m: m.chat.id == GROUP_ID and m.message_thread_id)
    def reply_to_user(message):
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
            set_ban(user_id, 1)
            bot.reply_to(message, "✅ Пользователь заблокирован.")
            general_id = get_or_create_general_topic()
            if general_id:
                c.execute('SELECT code FROM users WHERE user_id = ?', (user_id,))
                row_code = c.fetchone()
                code = row_code[0] if row_code else "неизвестен"
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
            set_ban(user_id, 0)
            bot.reply_to(message, "✅ Пользователь разблокирован.")
            general_id = get_or_create_general_topic()
            if general_id:
                c.execute('SELECT code FROM users WHERE user_id = ?', (user_id,))
                row_code = c.fetchone()
                code = row_code[0] if row_code else "неизвестен"
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

except Exception as e:
    print("КРИТИЧЕСКАЯ ОШИБКА:")
    traceback.print_exc()
    sys.exit(1)
