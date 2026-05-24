import asyncio
import aiosqlite

from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message,
    CallbackQuery,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.state import State, StatesGroup

from itdpy.client import ITDClient


# =========================
# CONFIG
# =========================

BOT_TOKEN = "8674340378:AAEUej6usFnQhLfzQ5Tf_oI7lGk2ShmvkVQ"
ADMIN_ID = 7544522231

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

DB = "itd.db"

user_feeds = {}
verified_users = set()


# =========================
# DB
# =========================

async def init_db():

    async with aiosqlite.connect(DB) as db:

        await db.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            telegram_id INTEGER PRIMARY KEY,
            refresh_token TEXT
        )
        """)

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


async def get_all_users():

    async with aiosqlite.connect(DB) as db:

        async with db.execute(
            "SELECT telegram_id FROM sessions"
        ) as cur:

            return await cur.fetchall()


# =========================
# STATES
# =========================

class LoginState(StatesGroup):
    token = State()


class PostState(StatesGroup):
    text = State()


class CommentState(StatesGroup):
    text = State()


class AdminState(StatesGroup):
    verify = State()
    broadcast = State()


# =========================
# HELPERS
# =========================

def is_admin(uid):
    return uid == ADMIN_ID


def menu(uid):

    kb = [
        [
            KeyboardButton(text="🏠 Лента"),
            KeyboardButton(text="👤 Профиль")
        ],
        [
            KeyboardButton(text="📝 Пост"),
            KeyboardButton(text="🔔 Уведомления")
        ],
        [
            KeyboardButton(text="🔎 Поиск"),
            KeyboardButton(text="🚪 Выйти")
        ]
    ]

    if is_admin(uid):
        kb.append([
            KeyboardButton(text="/admin")
        ])

    return ReplyKeyboardMarkup(
        keyboard=kb,
        resize_keyboard=True
    )


def feed_kb(i, post_id):

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⬅️",
                    callback_data=f"prev:{i}"
                ),

                InlineKeyboardButton(
                    text="➡️",
                    callback_data=f"next:{i}"
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


async def get_client(tg_id):

    session = await get_session(tg_id)

    if not session:
        return None

    return ITDClient(
        refresh_token=session[0]
    )


def badge(username):

    if username in verified_users:
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

    return f"""👤 {username}{badge(username)}

{content}

❤️ {likes} | 💬 {comments}"""


def extract_media(post):

    try:

        attachments = getattr(post, "attachments", None)

        if attachments:

            for a in attachments:

                for field in [
                    "url",
                    "fileUrl",
                    "imageUrl",
                    "previewUrl"
                ]:

                    value = getattr(a, field, None)

                    if isinstance(value, str):

                        if value.startswith("http"):
                            return value

        for field in [
            "imageUrl",
            "fileUrl",
            "previewUrl",
            "url"
        ]:

            value = getattr(post, field, None)

            if isinstance(value, str):

                if value.startswith("http"):
                    return value

    except:
        pass

    return None


async def safe_send(msg, media, text, kb):

    if media:

        try:

            return await msg.answer_photo(
                media,
                caption=text,
                reply_markup=kb
            )

        except:
            pass

    return await msg.answer(
        text,
        reply_markup=kb
    )


# =========================
# START
# =========================

@dp.message(CommandStart())
async def start(msg: Message, state: FSMContext):

    await state.set_state(LoginState.token)

    await msg.answer(
        "Отправь refresh_token ITD"
    )


# =========================
# LOGIN
# =========================

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
            f"✅ Вход выполнен\n👤 {me.username}",
            reply_markup=menu(msg.from_user.id)
        )

        await state.clear()

    except Exception as e:

        await msg.answer(str(e))


# =========================
# ADMIN
# =========================

@dp.message(Command("admin"))
async def admin(msg: Message):

    if not is_admin(msg.from_user.id):
        return await msg.answer("⛔ Нет доступа")

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📊 Стата",
                    callback_data="admin:stats"
                )
            ],
            [
                InlineKeyboardButton(
                    text="✔ Выдать галочку",
                    callback_data="admin:verify"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📣 Рассылка",
                    callback_data="admin:broadcast"
                )
            ]
        ]
    )

    await msg.answer(
        "🛠 Админ-панель",
        reply_markup=kb
    )


@dp.callback_query(F.data == "admin:stats")
async def admin_stats(c: CallbackQuery):

    if not is_admin(c.from_user.id):
        return

    users = await get_all_users()

    await c.message.answer(
        f"📊 Пользователей: {len(users)}"
    )

    await c.answer()


@dp.callback_query(F.data == "admin:verify")
async def admin_verify(
    c: CallbackQuery,
    state: FSMContext
):

    if not is_admin(c.from_user.id):
        return

    await state.set_state(
        AdminState.verify
    )

    await c.message.answer(
        "Отправь username"
    )

    await c.answer()


@dp.message(AdminState.verify)
async def verify_user(
    msg: Message,
    state: FSMContext
):

    username = msg.text.strip().replace("@", "")

    verified_users.add(username)

    users = await get_all_users()

    for u in users:

        try:

            await bot.send_message(
                u[0],
                f'🎉 Верифицирован! ✔\n\nПользователь "{username}" получил галочку в ИТДграме!'
            )

        except:
            pass

    await msg.answer(
        f"✔ @{username} верифицирован"
    )

    await state.clear()


@dp.callback_query(F.data == "admin:broadcast")
async def admin_broadcast(
    c: CallbackQuery,
    state: FSMContext
):

    if not is_admin(c.from_user.id):
        return

    await state.set_state(
        AdminState.broadcast
    )

    await c.message.answer(
        "Отправь текст рассылки"
    )

    await c.answer()


@dp.message(AdminState.broadcast)
async def send_broadcast(
    msg: Message,
    state: FSMContext
):

    users = await get_all_users()

    sent = 0

    for u in users:

        try:

            await bot.send_message(
                u[0],
                msg.text
            )

            sent += 1

        except:
            pass

    await msg.answer(
        f"📣 Отправлено: {sent}"
    )

    await state.clear()


# =========================
# FEED
# =========================

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

        media = extract_media(post)

        await safe_send(
            msg,
            media,
            render(post),
            feed_kb(0, post.id)
        )

    except Exception as e:

        await msg.answer(str(e))


@dp.callback_query(F.data.startswith("next:"))
async def next_post(c: CallbackQuery):

    posts = user_feeds.get(c.from_user.id)

    if not posts:
        return

    i = int(c.data.split(":")[1])

    i += 1

    if i >= len(posts):
        i = 0

    post = posts[i]

    media = extract_media(post)

    await c.message.delete()

    await safe_send(
        c.message,
        media,
        render(post),
        feed_kb(i, post.id)
    )

    await c.answer()


@dp.callback_query(F.data.startswith("prev:"))
async def prev_post(c: CallbackQuery):

    posts = user_feeds.get(c.from_user.id)

    if not posts:
        return

    i = int(c.data.split(":")[1])

    i -= 1

    if i < 0:
        i = len(posts) - 1

    post = posts[i]

    media = extract_media(post)

    await c.message.delete()

    await safe_send(
        c.message,
        media,
        render(post),
        feed_kb(i, post.id)
    )

    await c.answer()


# =========================
# LIKE
# =========================

@dp.callback_query(F.data.startswith("like:"))
async def like(c: CallbackQuery):

    client = await get_client(c.from_user.id)

    try:

        client.posts.like(
            c.data.split(":")[1]
        )

        await c.answer("❤️")

    except:

        await c.answer("Ошибка")


# =========================
# COMMENT
# =========================

@dp.callback_query(F.data.startswith("comment:"))
async def comment_open(
    c: CallbackQuery,
    state: FSMContext
):

    post_id = c.data.split(":")[1]

    await state.set_state(
        CommentState.text
    )

    await state.update_data(
        post_id=post_id
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

    data = await state.get_data()

    client = await get_client(msg.from_user.id)

    try:

        client.comments.create(
            post_id=data["post_id"],
            content=msg.text
        )

        await msg.answer("💬 Комментарий отправлен")

    except Exception as e:

        await msg.answer(str(e))

    await state.clear()


# =========================
# PROFILE
# =========================

@dp.message(F.text == "👤 Профиль")
async def profile(msg: Message):

    client = await get_client(msg.from_user.id)

    if not client:
        return

    try:

        me = client.users.me()

        await msg.answer(
            f"👤 {me.username}{badge(me.username)}\n🆔 {me.id}"
        )

    except Exception as e:

        await msg.answer(str(e))


# =========================
# SEARCH
# =========================

@dp.message(F.text == "🔎 Поиск")
async def search(msg: Message):

    client = await get_client(msg.from_user.id)

    if not client:
        return

    try:

        users = client.search.users("a")

        text = "🔎 Результаты:\n\n"

        for u in users[:10]:

            text += f"👤 {u.username}{badge(u.username)}\n"

        await msg.answer(text)

    except Exception as e:

        await msg.answer(str(e))


# =========================
# POST
# =========================

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


# =========================
# NOTIFICATIONS
# =========================

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

        chunks = []

        current = "🔔 Последние уведомления:\n\n"

        for n in notes:

            actor = "unknown"

            try:
                actor = n.actor.username
            except:
                pass

            ntype = getattr(
                n,
                "type",
                "notify"
            )

            if ntype == "follow":

                line = f"👤 {actor} подписался(-лась) на вас\n"

            elif ntype == "like":

                line = f"❤️ {actor} лайкнул(а) ваш пост\n"

            elif ntype == "comment":

                line = f"💬 {actor} прокомментировал(а) пост\n"

            else:

                line = f"🔔 {ntype} - {actor}\n"

            if len(current + line) > 3500:

                chunks.append(current)

                current = ""

            current += line

        if current:
            chunks.append(current)

        for chunk in chunks:

            await msg.answer(chunk)

    except Exception as e:

        await msg.answer(str(e))


# =========================
# LOGOUT
# =========================

@dp.message(F.text == "🚪 Выйти")
async def logout(msg: Message):

    await delete_session(
        msg.from_user.id
    )

    await msg.answer(
        "🚪 Вы вышли"
    )


# =========================
# MAIN
# =========================

async def main():

    await init_db()

    print("BOT STARTED")

    await dp.start_polling(bot)


if __name__ == "__main__":

    asyncio.run(main())