import telebot
import random
import time
import threading
import os
from flask import Flask
from supabase import create_client, Client

# ========== НАСТРОЙКИ ==========
TOKEN = '8737616518:AAGg7qupCISz6q_P0JP_UQ7-nrtTHzo3NsA'
GROUP_ID = -1003764086901

# Данные Supabase (замените на свои)
SUPABASE_URL = 'https://lkhuotwwiirhpxvtvyua.supabase.co'   # Ваш Project URL
SUPABASE_KEY = 'sb_publishable_MUPGJlwyMlxLjyymv0N1ug_mfwk1QQc'              # Ключ
# ================================

# --- Веб-сервер для Render ---
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

# --- Supabase ---
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- Функции БД (без изменений) ---
def generate_code():
    return str(random.randint(100000000, 999999999))

def get_user(user_id):
    try:
        res = supabase.table('users').select('topic_id, code, banned').eq('user_id', user_id).execute()
        if res.data:
            row = res.data[0]
            return row['topic_id'], row['code'], row['banned']
        return None
    except Exception as e:
        print("get_user error:", e)
        return None

def save_user(user_id, topic_id, code):
    try:
        supabase.table('users').upsert({'user_id': user_id, 'topic_id': topic_id, 'code': code, 'banned': 0}).execute()
    except Exception as e:
        print("save_user error:", e)

def get_user_by_code(code):
    try:
        res = supabase.table('users').select('user_id').eq('code', code).execute()
        if res.data:
            return res.data[0]['user_id']
        return None
    except Exception as e:
        print("get_user_by_code error:", e)
        return None

def set_ban(user_id, banned):
    try:
        supabase.table('users').update({'banned': banned}).eq('user_id', user_id).execute()
    except Exception as e:
        print("set_ban error:", e)

def record_blocked_bot(user_id):
    try:
        supabase.table('blocked_bot').upsert({'user_id': user_id}).execute()
    except Exception as e:
        print("record_blocked_bot error:", e)

def get_stats():
    try:
        total = supabase.table('users').select('user_id', count='exact').execute().count
        blocked = supabase.table('blocked_bot').select('user_id', count='exact').execute().count
        banned = supabase.table('users').select('user_id', count='exact').eq('banned', 1).execute().count
        pure = total - (blocked + banned)
        return total, blocked, banned, pure
    except Exception as e:
        print("get_stats error:", e)
        return 0, 0, 0, 0

def get_or_create_general_topic():
    try:
        res = supabase.table('settings').select('value').eq('key', 'general_topic_id').execute()
        if res.data:
            return int(res.data[0]['value'])
        topic = bot.create_forum_topic(GROUP_ID, "general")
        supabase.table('settings').upsert({'key': 'general_topic_id', 'value': str(topic.message_thread_id)}).execute()
        return topic.message_thread_id
    except Exception as e:
        print("general topic error:", e)
        return None

# --- Обработчик блокировки бота ---
@bot.my_chat_member_handler()
def on_block(message):
    if message.old_chat_member.status != 'kicked' and message.new_chat_member.status == 'kicked':
        uid = message.chat.id
        record_blocked_bot(uid)
        gen = get_or_create_general_topic()
        if gen:
            bot.send_message(GROUP_ID, f"🚫 Пользователь #{uid} заблокировал бота.", message_thread_id=gen)

# --- Команды ---
@bot.message_handler(commands=['start'])
def start(m):
    if m.chat.type == 'private':
        bot.send_message(m.chat.id, "Привет! Напишите что угодно (стикеры, голосовые, видео) — всё будет анонимно передано оператору.")

@bot.message_handler(commands=['stats'])
def stats(m):
    if m.chat.id != GROUP_ID:
        return
    total, blocked, banned, pure = get_stats()
    bot.send_message(GROUP_ID, f"📊 Статистика:\nВсего: {total}\nЗаблокировали бота: {blocked}\nЗабанено админом: {banned}\nЧистых: {pure}")

# --- ПЕРЕСЫЛКА ЛЮБОГО СООБЩЕНИЯ ОТ ПОЛЬЗОВАТЕЛЯ ---
@bot.message_handler(func=lambda m: m.chat.type == 'private' and m.text != '/start')
def forward_to_group(m):
    uid = m.chat.id
    row = get_user(uid)
    if not row:
        code = generate_code()
        topic_name = f"#{code}"
        try:
            topic = bot.create_forum_topic(GROUP_ID, topic_name)
            tid = topic.message_thread_id
            save_user(uid, tid, code)
        except Exception as e:
            bot.send_message(uid, "❌ Ошибка, попробуйте позже.")
            return
    else:
        tid, code, banned = row
        if banned:
            bot.send_message(uid, "❌ Вы заблокированы.")
            return

    # ГАРАНТИРОВАННАЯ ОТПРАВКА МЕДИА (без copy_message)
    try:
        if m.text:
            bot.send_message(GROUP_ID, f"✉️ #{code}\n{m.text}", message_thread_id=tid)
        elif m.photo:
            bot.send_photo(GROUP_ID, m.photo[-1].file_id, caption=f"✉️ #{code}\n{m.caption or ''}", message_thread_id=tid)
        elif m.video:
            bot.send_video(GROUP_ID, m.video.file_id, caption=f"✉️ #{code}\n{m.caption or ''}", message_thread_id=tid)
        elif m.document:
            bot.send_document(GROUP_ID, m.document.file_id, caption=f"✉️ #{code}\n{m.caption or ''}", message_thread_id=tid)
        elif m.voice:
            bot.send_voice(GROUP_ID, m.voice.file_id, caption=f"✉️ #{code}", message_thread_id=tid)
        elif m.audio:
            bot.send_audio(GROUP_ID, m.audio.file_id, caption=f"✉️ #{code}\n{m.caption or ''}", message_thread_id=tid)
        elif m.sticker:
            # Стикеры отправляются без подписи (caption не поддерживается)
            bot.send_sticker(GROUP_ID, m.sticker.file_id, message_thread_id=tid)
            # Дополнительно отправляем текстовую подпись в тот же топик
            bot.send_message(GROUP_ID, f"✉️ #{code} (стикер)", message_thread_id=tid)
        elif m.video_note:
            # Кружок (video note)
            bot.send_video_note(GROUP_ID, m.video_note.file_id, message_thread_id=tid)
            bot.send_message(GROUP_ID, f"✉️ #{code} (кружок)", message_thread_id=tid)
        else:
            bot.send_message(GROUP_ID, f"✉️ #{code}\n[Неподдерживаемый тип]", message_thread_id=tid)
    except Exception as e:
        print("Ошибка отправки в группу:", e)
        bot.send_message(uid, "❌ Ошибка при отправке, попробуйте другой формат.")

# --- ОТВЕТ ОПЕРАТОРА (тоже поддерживает все медиа) ---
@bot.message_handler(func=lambda m: m.chat.id == GROUP_ID and m.message_thread_id and not m.text.startswith('/'))
def reply_to_user(m):
    tid = m.message_thread_id
    try:
        res = supabase.table('users').select('user_id').eq('topic_id', tid).execute()
        if not res.data:
            return
        uid = res.data[0]['user_id']
        # Отправляем пользователю точно такой же тип сообщения
        if m.text:
            bot.send_message(uid, m.text)
        elif m.photo:
            bot.send_photo(uid, m.photo[-1].file_id, caption=m.caption)
        elif m.video:
            bot.send_video(uid, m.video.file_id, caption=m.caption)
        elif m.document:
            bot.send_document(uid, m.document.file_id, caption=m.caption)
        elif m.voice:
            bot.send_voice(uid, m.voice.file_id)
        elif m.audio:
            bot.send_audio(uid, m.audio.file_id, caption=m.caption)
        elif m.sticker:
            bot.send_sticker(uid, m.sticker.file_id)
        elif m.video_note:
            bot.send_video_note(uid, m.video_note.file_id)
    except Exception as e:
        print("Ошибка ответа пользователю:", e)

# --- БАН / РАЗБАН (без изменений) ---
@bot.message_handler(commands=['ban'])
def ban_cmd(m):
    if m.chat.id != GROUP_ID:
        return
    uid = None
    if m.reply_to_message:
        tid = m.reply_to_message.message_thread_id
        if tid:
            res = supabase.table('users').select('user_id').eq('topic_id', tid).execute()
            if res.data:
                uid = res.data[0]['user_id']
    if not uid and len(m.text.split()) > 1:
        code = m.text.split()[1]
        uid = get_user_by_code(code)
    if uid:
        set_ban(uid, 1)
        bot.reply_to(m, "✅ Забанен")
        gen = get_or_create_general_topic()
        if gen:
            bot.send_message(GROUP_ID, f"🔨 Администратор заблокировал пользователя #{code if 'code' in locals() else uid}", message_thread_id=gen)
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
            res = supabase.table('users').select('user_id').eq('topic_id', tid).execute()
            if res.data:
                uid = res.data[0]['user_id']
    if not uid and len(m.text.split()) > 1:
        code = m.text.split()[1]
        uid = get_user_by_code(code)
    if uid:
        set_ban(uid, 0)
        bot.reply_to(m, "✅ Разбанен")
        gen = get_or_create_general_topic()
        if gen:
            bot.send_message(GROUP_ID, f"🔓 Администратор разблокировал пользователя #{code if 'code' in locals() else uid}", message_thread_id=gen)
        try:
            bot.send_message(uid, "✅ Вы разблокированы.")
        except:
            pass
    else:
        bot.reply_to(m, "❌ Не найден.")

print("✅ Бот запущен. Группа:", GROUP_ID)
bot.infinity_polling()
