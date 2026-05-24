import os
import asyncio
import aiosqlite

from aiohttp import web

from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton
)
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.state import State, StatesGroup

from itdpy.client import ITDClient


# =====================================
# CONFIG
# =====================================

BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN not found")

ADMIN_ID = 7544522231

bot = Bot(token=BOT_TOKEN)

dp = Dispatcher(
    storage=MemoryStorage()
)

DB = "itd.db"

user_feeds = {}
verified_users = set()
live_tasks = {}


# =====================================
# DATABASE
# =====================================

async def init_db():

    async with aiosqlite.connect(DB) as db:

        await db.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            telegram_id INTEGER PRIMARY KEY,
            refresh_token TEXT
        )
        """)

        await db.execute("""
        CREATE TABLE IF NOT EXISTS verified (
            username TEXT PRIMARY KEY
        )
        """)

        await db.commit()

        async with db.execute(
            "SELECT username FROM verified"
        ) as cur:

            rows = await cur.fetchall()

            for row in rows:
                verified_users.add(row[0].lower())


async def save_verified(username):

    verified_users.add(username.lower())

    async with aiosqlite.connect(DB) as db:

        await db.execute(
            "INSERT OR REPLACE INTO verified VALUES (?)",
            (username.lower(),)
        )

        await db.commit()


async def save_session(tg_id, token):

    async with aiosqlite.connect(DB) as db:

        await db.execute(
            "INSERT OR REPLACE INTO sessions VALUES (?, ?)",
            (tg_id, token)
        )

        await db.commit()


async def get_session(tg_id):

    async with aiosqlite.connect(DB) as db:

        async with db.execute(
            "SELECT refresh_token FROM sessions WHERE telegram_id=?",
            (tg_id,)
        ) as cur:

            return await cur.fetchone()


async def delete_session(tg_id):

    async with aiosqlite.connect(DB) as db:

        await db.execute(
            "DELETE FROM sessions WHERE telegram_id=?",
            (tg_id,)
        )

        await db.commit()


# =====================================
# STATES
# =====================================

class LoginState(StatesGroup):
    token = State()


class PostState(StatesGroup):
    text = State()


class CommentState(StatesGroup):
    text = State()


class BroadcastState(StatesGroup):
    text = State()


class VerifyState(StatesGroup):
    text = State()


# =====================================
# KEYBOARDS
# =====================================

menu = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(text="🏠 Лента"),
            KeyboardButton(text="🔔 Уведомления")
        ],
        [
            KeyboardButton(text="📝 Пост"),
            KeyboardButton(text="👤 Профиль")
        ],
        [
            KeyboardButton(text="🔎 Поиск"),
            KeyboardButton(text="🚪 Выйти")
        ]
    ],
    resize_keyboard=True
)


admin_menu = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(text="📊 Стата"),
            KeyboardButton(text="📢 Рассылка")
        ],
        [
            KeyboardButton(text="✔ Выдать галочку")
        ],
        [
            KeyboardButton(text="🔙 Назад")
        ]
    ],
    resize_keyboard=True
)


def feed_kb(index, post_id):

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⬅️",
                    callback_data=f"prev:{index}"
                ),
                InlineKeyboardButton(
                    text="➡️",
                    callback_data=f"next:{index}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="❤️",
                    callback_data=f"like:{post_id}"
                ),
                InlineKeyboardButton(
                    text="💬",
                    callback_data=f"comment:{post_id}"
                )
            ]
        ]
    )


# =====================================
# CLIENT
# =====================================

async def get_client(tg_id):

    session = await get_session(tg_id)

    if not session:
        return None

    return ITDClient(
        refresh_token=session[0]
    )


# =====================================
# HELPERS
# =====================================

def verify_mark(username):

    if username.lower() in verified_users:
        return " ✔"

    return ""


def render(post):

    try:
        username = post.author.username
    except:
        username = "unknown"

    content = getattr(post, "content", "")

    likes = getattr(post, "likes_count", 0)
    comments = getattr(post, "comments_count", 0)

    return f"""👤 {username}{verify_mark(username)}

{content}

❤️ {likes} | 💬 {comments}"""


def notif_text(n):

    try:
        actor = getattr(n, "actor", None)

        username = "unknown"

        if actor:
            username = getattr(actor, "username", "unknown")

        ntype = str(
            getattr(n, "type", "")
        ).lower()

        if "follow" in ntype:
            return f"👤 {username} подписался(-лась) на вас"

        if "like" in ntype:
            return f"❤️ {username} лайкнул ваш пост"

        if "comment" in ntype:
            return f"💬 {username} прокомментировал ваш пост"

        return f"🔔 {username}: {ntype}"

    except:
        return "🔔 Новое уведомление"


def get_post_photo(post):

    try:

        attachments = getattr(post, "attachments", [])

        if not attachments:
            return None

        for a in attachments:

            url = getattr(a, "url", None)

            if url and url.startswith("http"):
                return url

            file = getattr(a, "file", None)

            if file:
                file_url = getattr(file, "url", None)

                if file_url and file_url.startswith("http"):
                    return file_url

    except:
        pass

    return None


# =====================================
# START
# =====================================

@dp.message(CommandStart())
async def start(msg: Message, state: FSMContext):

    await state.set_state(
        LoginState.token
    )

    await msg.answer(
"""Отправь refresh_token ITD

Как получить:

1. itd.com
2. F12
3. Application
4. Cookies
5. refresh_token"""
    )


# =====================================
# HELP
# =====================================

@dp.message(F.text == "/help")
async def help_cmd(msg: Message):

    await msg.answer(
"""ИТДграм — это соцсеть ITD внутри Telegram.

✔ — галочка верификации внутри ИТДграма.
Выдается админом.

Команды:
🏠 Лента
🔔 Уведомления
📝 Пост
👤 Профиль
🔎 Поиск"""
    )


# =====================================
# ADMIN
# =====================================

@dp.message(F.text == "/admin")
async def admin(msg: Message):

    if msg.from_user.id != ADMIN_ID:
        return await msg.answer(
            "❌ Ты не админ"
        )

    await msg.answer(
        "⚙ Админка",
        reply_markup=admin_menu
    )


@dp.message(F.text == "🔙 Назад")
async def back(msg: Message):

    await msg.answer(
        "🏠 Главное меню",
        reply_markup=menu
    )


@dp.message(F.text == "📊 Стата")
async def stats(msg: Message):

    if msg.from_user.id != ADMIN_ID:
        return

    async with aiosqlite.connect(DB) as db:

        async with db.execute(
            "SELECT COUNT(*) FROM sessions"
        ) as cur:

            users = (await cur.fetchone())[0]

    await msg.answer(
        f"👥 Пользователей: {users}\n✔ Верифов: {len(verified_users)}"
    )


@dp.message(F.text == "📢 Рассылка")
async def mailing(msg: Message, state: FSMContext):

    if msg.from_user.id != ADMIN_ID:
        return

    await state.set_state(
        BroadcastState.text
    )

    await msg.answer(
        "Введите текст рассылки"
    )


@dp.message(BroadcastState.text)
async def send_broadcast(msg: Message, state: FSMContext):

    if msg.from_user.id != ADMIN_ID:
        return

    sent = 0

    async with aiosqlite.connect(DB) as db:

        async with db.execute(
            "SELECT telegram_id FROM sessions"
        ) as cur:

            users = await cur.fetchall()

    for u in users:

        try:

            await bot.send_message(
                u[0],
                f"📢 {msg.text}"
            )

            sent += 1

        except:
            pass

    await msg.answer(
        f"✅ Отправлено: {sent}"
    )

    await state.clear()


@dp.message(F.text == "✔ Выдать галочку")
async def verify_start(msg: Message, state: FSMContext):

    if msg.from_user.id != ADMIN_ID:
        return

    await state.set_state(
        VerifyState.text
    )

    await msg.answer(
        "Введите username ITD"
    )


@dp.message(VerifyState.text)
async def verify_user(msg: Message, state: FSMContext):

    if msg.from_user.id != ADMIN_ID:
        return

    username = msg.text.replace("@", "").strip()

    await save_verified(username)

    async with aiosqlite.connect(DB) as db:

        async with db.execute(
            "SELECT telegram_id FROM sessions"
        ) as cur:

            users = await cur.fetchall()

    for u in users:

        try:

            await bot.send_message(
                u[0],
                f'✔ Верифицирован!\n\nПользователь "{username}" получил галочку в ИТДграме!'
            )

        except:
            pass

    await msg.answer(
        f"✔ Галочка выдана @{username}"
    )

    await state.clear()


# =====================================
# LOGIN
# =====================================

@dp.message(LoginState.token)
async def login(msg: Message, state: FSMContext):

    token = msg.text.strip()

    try:

        client = ITDClient(
            refresh_token=token
        )

        me = client.users.me()

        await save_session(
            msg.from_user.id,
            token
        )

        await msg.answer(
            f"✅ Вход выполнен\n\n👤 {me.username}",
            reply_markup=menu
        )

        await state.clear()

    except Exception as e:

        await msg.answer(str(e))


# =====================================
# FEED
# =====================================

@dp.message(F.text == "🏠 Лента")
async def feed(msg: Message):

    client = await get_client(msg.from_user.id)

    if not client:
        return

    try:

        posts = list(
            client.posts.list()
        )

        if not posts:
            return await msg.answer("Лента пуста")

        user_feeds[msg.from_user.id] = posts

        post = posts[0]

        media = get_post_photo(post)

        if media:

            try:

                await msg.answer_photo(
                    media,
                    caption=render(post),
                    reply_markup=feed_kb(0, post.id)
                )

                return

            except:
                pass

        await msg.answer(
            render(post),
            reply_markup=feed_kb(0, post.id)
        )

    except Exception as e:

        await msg.answer(str(e))


# =====================================
# NEXT/PREV
# =====================================

async def send_post(message, post, index):

    media = get_post_photo(post)

    if media:

        try:

            await message.answer_photo(
                media,
                caption=render(post),
                reply_markup=feed_kb(index, post.id)
            )

            return

        except:
            pass

    await message.answer(
        render(post),
        reply_markup=feed_kb(index, post.id)
    )


@dp.callback_query(F.data.startswith("next:"))
async def next_post(c: CallbackQuery):

    posts = user_feeds.get(c.from_user.id)

    if not posts:
        return

    i = int(c.data.split(":")[1]) + 1

    if i >= len(posts):
        i = 0

    await send_post(
        c.message,
        posts[i],
        i
    )

    await c.answer()


@dp.callback_query(F.data.startswith("prev:"))
async def prev_post(c: CallbackQuery):

    posts = user_feeds.get(c.from_user.id)

    if not posts:
        return

    i = int(c.data.split(":")[1]) - 1

    if i < 0:
        i = len(posts) - 1

    await send_post(
        c.message,
        posts[i],
        i
    )

    await c.answer()


# =====================================
# LIKE
# =====================================

@dp.callback_query(F.data.startswith("like:"))
async def like(c: CallbackQuery):

    client = await get_client(c.from_user.id)

    try:

        client.posts.like(
            c.data.split(":")[1]
        )

        await c.answer("❤️")

    except Exception as e:

        await c.answer(str(e))


# =====================================
# COMMENT
# =====================================

@dp.callback_query(F.data.startswith("comment:"))
async def comment_open(
    c: CallbackQuery,
    state: FSMContext
):

    await state.set_state(
        CommentState.text
    )

    await state.update_data(
        post_id=c.data.split(":")[1]
    )

    await c.message.answer(
        "Напиши комментарий"
    )

    await c.answer()


@dp.message(CommentState.text)
async def comment_send(
    msg: Message,
    state: FSMContext
):

    client = await get_client(msg.from_user.id)

    data = await state.get_data()

    try:

        client.comments.create(
            post_id=data["post_id"],
            content=msg.text
        )

        await msg.answer("💬 Комментарий отправлен")

    except Exception as e:

        await msg.answer(str(e))

    await state.clear()


# =====================================
# PROFILE
# =====================================

@dp.message(F.text == "👤 Профиль")
async def profile(msg: Message):

    client = await get_client(msg.from_user.id)

    if not client:
        return

    try:

        me = client.users.me()

        await msg.answer(
            f"👤 {me.username}{verify_mark(me.username)}\n🆔 {me.id}"
        )

    except Exception as e:

        await msg.answer(str(e))


# =====================================
# SEARCH
# =====================================

@dp.message(F.text.startswith("🔎"))
async def search(msg: Message):

    client = await get_client(msg.from_user.id)

    if not client:
        return

    query = msg.text.replace(
        "🔎",
        ""
    ).strip()

    if not query:
        return await msg.answer(
            "🔎 Введите ник после эмодзи"
        )

    try:

        users = client.search.users(query)

        text = "🔎 Результаты поиска\n\n"

        for u in users[:10]:

            text += f"👤 {u.username}{verify_mark(u.username)}\n"

        await msg.answer(text)

    except Exception as e:

        await msg.answer(str(e))


# =====================================
# POST
# =====================================

@dp.message(F.text == "📝 Пост")
async def post_start(
    msg: Message,
    state: FSMContext
):

    await state.set_state(
        PostState.text
    )

    await msg.answer(
        "Отправь текст поста"
    )


@dp.message(PostState.text)
async def post_send(
    msg: Message,
    state: FSMContext
):

    client = await get_client(msg.from_user.id)

    if not client:
        return

    try:

        client.posts.create(
            content=msg.text
        )

        await msg.answer(
            "✅ Пост опубликован"
        )

    except Exception as e:

        await msg.answer(str(e))

    await state.clear()


# =====================================
# NOTIFS
# =====================================

@dp.message(F.text == "🔔 Уведомления")
async def notifs(msg: Message):

    client = await get_client(msg.from_user.id)

    if not client:
        return

    try:

        notes = list(
            client.notifications.list()
        )[:10]

        if not notes:
            return await msg.answer(
                "🔔 Уведомлений нет"
            )

        text = "🔔 Последние уведомления\n\n"

        for n in notes:

            line = notif_text(n)

            if len(text + line) > 3500:
                break

            text += f"{line}\n\n"

        await msg.answer(text)

    except Exception as e:

        await msg.answer(str(e))


# =====================================
# LOGOUT
# =====================================

@dp.message(F.text == "🚪 Выйти")
async def logout(msg: Message):

    await delete_session(
        msg.from_user.id
    )

    await msg.answer(
        "🚪 Вы вышли"
    )


# =====================================
# RENDER HEALTHCHECK
# =====================================

async def health(request):
    return web.Response(text="ITDGram OK")


# =====================================
# MAIN
# =====================================

async def main():

    await init_db()

    app = web.Application()

    app.router.add_get("/", health)

    port = int(
        os.getenv("PORT", 10000)
    )

    runner = web.AppRunner(app)

    await runner.setup()

    site = web.TCPSite(
        runner,
        host="0.0.0.0",
        port=port
    )

    await site.start()

    print(f"WEB STARTED {port}")
    print("BOT STARTED")

    await dp.start_polling(bot)


if __name__ == "__main__":

    asyncio.run(main())
