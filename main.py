import asyncio
import logging
from datetime import datetime, date
from typing import Optional

import aiosqlite
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    FSInputFile,
)
from aiogram.enums import ParseMode

# ==================== НАСТРОЙКИ ====================
import os

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = 5598701749

# Путь к QR-коду (потом скажу куда положить файл)
QR_PATH = "qr.png"

PRODUCTS = {
    50: 72,
    100: 145,
    150: 217,
    250: 362,
    500: 725,
    1000: 1450,
    2500: 3625
}

PREMIUM_PRODUCTS = {
    3: 1100,
    6: 1470,
    12: 2630
}
# ===================================================

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = Router()
db: Optional[aiosqlite.Connection] = None


class OrderStates(StatesGroup):
    waiting_custom_stars = State()
    waiting_recipient = State()
    waiting_gift_username = State()
    waiting_gift_text = State()
    waiting_payment_check = State()

    waiting_premium_username = State()


async def init_db():
    global db
    db = await aiosqlite.connect("orders.db")
    await db.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            username TEXT,
            recipient TEXT NOT NULL,
            stars INTEGER NOT NULL,
            price INTEGER NOT NULL,
            product_type TEXT DEFAULT 'stars',
            status TEXT DEFAULT 'pending',
            created_at TEXT NOT NULL,
            completed_at TEXT
        )
    """)
    try:
        await db.execute("ALTER TABLE orders ADD COLUMN product_type TEXT DEFAULT 'stars'")
    except:
        pass
    await db.commit()


async def create_order(user_id: int, username: str | None, recipient: str, stars: int, price: int, product_type: str = "stars") -> int:
    now = datetime.now().isoformat()
    cursor = await db.execute(
        """
        INSERT INTO orders (user_id, username, recipient, stars, price, product_type, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)
        """,
        (user_id, username, recipient, stars, price, product_type, now)
    )
    await db.commit()
    return cursor.lastrowid


async def get_order(order_id: int) -> dict | None:
    cursor = await db.execute("SELECT * FROM orders WHERE id = ?", (order_id,))
    row = await cursor.fetchone()
    if not row:
        return None
    columns = [desc[0] for desc in cursor.description]
    return dict(zip(columns, row))


async def complete_order(order_id: int) -> bool:
    order = await get_order(order_id)
    if not order or order["status"] == "completed":
        return False
    now = datetime.now().isoformat()
    await db.execute(
        "UPDATE orders SET status = 'completed', completed_at = ? WHERE id = ?",
        (now, order_id)
    )
    await db.commit()
    return True


def calculate_order_profit(order: dict) -> int:
    product_type = order.get("product_type", "stars")
    
    if product_type == "premium":
        months = order["stars"]
        if months == 3:
            return 52
        elif months == 6:
            return 72
        elif months == 12:
            return 96
        return 0
    
    elif product_type == "gift":
        return 52
    
    else:  # stars
        try:
            stars = int(order["stars"])
            return round(stars * 0.14)
        except:
            return 0


async def get_today_profit() -> int:
    from datetime import timezone, timedelta
    bishkek = timezone(timedelta(hours=6))
    today = datetime.now(bishkek).date().isoformat()
    
    cursor = await db.execute(
        """
        SELECT * FROM orders
        WHERE status = 'completed' AND date(completed_at) = ?
        """,
        (today,)
    )
    rows = await cursor.fetchall()
    
    if not rows:
        return 0
        
    columns = [desc[0] for desc in cursor.description]
    
    total = 0
    for row in rows:
        order = dict(zip(columns, row))
        total += calculate_order_profit(order)
    
    return total
    
async def get_user_stats(user_id: int):
    cursor = await db.execute(
        """
        SELECT COUNT(*), COALESCE(SUM(price), 0)
        FROM orders
        WHERE user_id = ? AND status = 'completed'
        """,
        (user_id,)
    )

    row = await cursor.fetchone()
    return row[0], row[1]

def catalog_keyboard() -> InlineKeyboardMarkup:
    buttons = []

    for stars, price in PRODUCTS.items():
        buttons.append([
            InlineKeyboardButton(
                text=f"⭐️ {stars} звёзд — {price} сом",
                callback_data=f"buy_{stars}"
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            text="✏️ Ввести своё количество",
            callback_data="custom_stars"
        )
    ])

    buttons.append([
        InlineKeyboardButton(
            text="Назад",
icon_custom_emoji_id="5280911767902378209",
            callback_data="back_main"
        )
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)

def premium_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💎 3 месяца — 1100 сом",
                    callback_data="premium_3"
                )
            ],
            [
                InlineKeyboardButton(
                    text="💎 6 месяцев — 1470 сом",
                    callback_data="premium_6"
                )
            ],
            [
                InlineKeyboardButton(
                    text="💎 12 месяцев — 2630 сом",
                    callback_data="premium_12"
                )
            ],
            [
                InlineKeyboardButton(
                    text="Назад",
icon_custom_emoji_id="5280911767902378209",
                    callback_data="back_main"
                )
            ]
        ]
    )
    
def gifts_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
inline_keyboard=[
[
InlineKeyboardButton(
text="145 сом",
                    icon_custom_emoji_id="5345935030143196497",
                    callback_data="gift_tree"
                ),
                InlineKeyboardButton(
                    text="145 сом",
                    icon_custom_emoji_id="5379850840691476775",
                    callback_data="gift_santa_bear"
                )
            ],
            [
                InlineKeyboardButton(
                    text="145 сом",
                    icon_custom_emoji_id="5224628072619216265",
                    callback_data="gift_heart"
                ),
                InlineKeyboardButton(
                    text="145 сом",
                    icon_custom_emoji_id="5226661632259691727",
                    callback_data="gift_blue_bear"
                )
            ],
            [
                InlineKeyboardButton(
                    text="145 сом",
                    icon_custom_emoji_id="5289761157173775507",
                    callback_data="gift_pink_bear"
                ),
                InlineKeyboardButton(
                    text="145 сом",
                    icon_custom_emoji_id="5317000922096769303",
                    callback_data="gift_leprechaun"
                )
            ],
            [
                InlineKeyboardButton(
                    text="145 сом",
                    icon_custom_emoji_id="5359736160224586485",
                    callback_data="gift_clown"
                ),
                InlineKeyboardButton(
                    text="145 сом",
                    icon_custom_emoji_id="5393309541620291208",
                    callback_data="gift_bunny"
                )
            ],
            [
                InlineKeyboardButton(
                    text="145 сом",
                    icon_custom_emoji_id="5447213743417105726",
                    callback_data="gift_worker"
                ),
                InlineKeyboardButton(
                    text="145 сом",
                    icon_custom_emoji_id="5397971251878732060",
                    callback_data="gift_football"
                )
            ],
            [
                InlineKeyboardButton(
                    text="Назад",
                    icon_custom_emoji_id="5280911767902378209",
                    callback_data="back_main"
                )
            ]
        ]
    )

def back_to_catalog_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Назад",
icon_custom_emoji_id="5280911767902378209",
                    callback_data="menu_stars"
                )
            ]
        ]
    )

def complete_keyboard(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Подтвердить оплату",
                    callback_data=f"approve_{order_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ Отклонить чек",
                    callback_data=f"reject_{order_id}"
                )
            ]
        ]
    )
    
def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
    text="Telegram Stars",
    icon_custom_emoji_id="5956098562616988692",
    callback_data="menu_stars"
),
                InlineKeyboardButton(
    text="Telegram Premium",
    icon_custom_emoji_id="5789911984283586269",
    callback_data="menu_premium"
)
            ],
            [
                InlineKeyboardButton(
    text="Удалённые подарки",
    icon_custom_emoji_id="5226661632259691727",
    callback_data="menu_gifts"
)
            ],
            [
                InlineKeyboardButton(
    text="Поддержка",
    icon_custom_emoji_id="5305254693348320081",
    url="https://t.me/podderzhkaDA?text=Здравствуйте!%20Нужна%20помощь."
),
                InlineKeyboardButton(
    text="Профиль",
    icon_custom_emoji_id="5467904284509085470",
    callback_data="menu_profile"
)
            ]
        ]
    )

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()

    text = (
        '<tg-emoji emoji-id="5330033399061037873">☺</tg-emoji>    <b>Приветствуем!</b><tg-emoji emoji-id="5271803701340706125">☺</tg-emoji>\n\n'
        '<tg-emoji emoji-id="5954135079662916434">☺</tg-emoji> Здесь вы можете купить <b>Telegram Stars</b>,'
        "<b>Telegram Premium</b>, удалённые подарки <b>ЗА СОМЫ <tg-emoji emoji-id='5368580468549640460'>☺</tg-emoji></b>.\n"
        "<tg-emoji emoji-id='5963318814958423599'>☺</tg-emoji> Доставка товаров — за несколько минут. Всегда низкие цены.\n\n"
        '<tg-emoji emoji-id="5278702045883292456">☺</tg-emoji>Приятных покупок!'
    )

    await message.answer(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu_keyboard()
    )


@router.message(Command("catalog"))
async def cmd_catalog(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Выберите количество звёзд:", reply_markup=catalog_keyboard())
    
@router.callback_query(F.data == "menu_stars")
async def menu_stars(callback: CallbackQuery):

    await callback.message.edit_text(
        "<tg-emoji emoji-id='5954135079662916434'>☺</tg-emoji> <b>Покупка звёзд</b>\n\n"
        "<tg-emoji emoji-id='5879770735999717115'>☺</tg-emoji> Получатель: <b>@</b>\n\n"
        "<tg-emoji emoji-id='5981137088081301019'>☺</tg-emoji> Выберите необходимый пакет\n"
        "или введите количеством от <b>50</b> до <b>100000</b>.",
        parse_mode=ParseMode.HTML,
        reply_markup=catalog_keyboard()
    )

    await callback.answer()
    
@router.callback_query(F.data == "menu_premium")
async def menu_premium(callback: CallbackQuery):

    await callback.message.edit_text(
        "<tg-emoji emoji-id='5453888208494402519'>☺</tg-emoji> <b>Покупка Telegram Premium</b>\n\n"
        "❗️Получить могут только пользователи без активной подписки❗️\n\n"
        "• Выберите необходимый пакет:",
        parse_mode=ParseMode.HTML,
        reply_markup=premium_keyboard()
    )

    await callback.answer()
    
@router.callback_query(F.data == "menu_profile")
async def menu_profile(callback: CallbackQuery):

    purchases, total = await get_user_stats(callback.from_user.id)

    text = (
        "<tg-emoji emoji-id='5467904284509085470'>☺</tg-emoji> <b>Профиль</b>\n\n"
        f"<tg-emoji emoji-id='5262785644408622689'>☺</tg-emoji> ID: <code>{callback.from_user.id}</code>\n\n"
        f"<tg-emoji emoji-id='5262495450648300372'>☺</tg-emoji>Сумма покупок: <b>{total} сом</b>\n"
        f"<tg-emoji emoji-id='5330261964335635622'>☺</tg-emoji> Количество покупок: <b>{purchases}</b>"
    )

    await callback.message.edit_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Назад",
                        icon_custom_emoji_id="5280911767902378209",
                        callback_data="back_main"
                    )
                ]
            ]
        )
    )

    await callback.answer()    
    
@router.callback_query(F.data.startswith("premium_"))
async def premium_buy(callback: CallbackQuery, state: FSMContext):

    months = int(callback.data.split("_")[1])
    price = PREMIUM_PRODUCTS[months]

    await state.update_data(
        premium_months=months,
        price=price
    )

    await state.set_state(OrderStates.waiting_premium_username)

    await callback.message.answer(
        f"<tg-emoji emoji-id='5453888208494402519'>☺</tg-emoji><b>Telegram Premium {months} мес.</b>\n"
        f"<tg-emoji emoji-id='5192751744471288987'>☺</tg-emoji> К оплате: <b>{price} сом</b>\n\n"
        "<tg-emoji emoji-id='5879770735999717115'>☺</tg-emoji>Теперь отправьте username пользователя.\n\n"
        "Пример:\n"
        "<code>@skobla</code>",
        parse_mode=ParseMode.HTML
    )

    await callback.answer()
    
async def menu_gifts(callback: CallbackQuery):

    await callback.message.edit_text(
        "<tg-emoji emoji-id='5226661632259691727'>☺</tg-emoji> <b>Удалённые подарки</b>\n\n"
        "🎁 Все подарки стоят <b>145 сом</b>.\n\n"
        "👇 Выберите подарок:",
        parse_mode=ParseMode.HTML,
        reply_markup=gifts_keyboard()
    )

    await callback.answer()
    
@router.callback_query(F.data == "back_main")
async def back_main(callback: CallbackQuery):

    text = (
        "<tg-emoji emoji-id='5330033399061037873'>☺</tg-emoji><b>Приветствуем!</b>\n\n"
        "<tg-emoji emoji-id='5954135079662916434'>☺</tg-emoji>Здесь вы можете купить <b>Telegram Stars</b>, "
        "<b>Telegram Premium</b>, удалённые подарки <b>ЗА СОМЫ <tg-emoji emoji-id='5368580468549640460'>☺</tg-emoji></b>.\n"
        "<tg-emoji emoji-id='5963318814958423599'>☺</tg-emoji>Доставка товаров — за несколько минут. Всегда низкие цены.\n\n"
        "<tg-emoji emoji-id='5278702045883292456'>☺</tg-emoji>Приятных покупок!"
    )

    await callback.message.edit_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu_keyboard()
    )

    await callback.answer()
    
@router.callback_query(F.data == "custom_stars")
async def custom_stars(callback: CallbackQuery, state: FSMContext):

    await state.set_state(OrderStates.waiting_custom_stars)

    await callback.message.edit_text(
        "<tg-emoji emoji-id='5395444784611480792'>☺</tg-emoji><b>Введите количество звёзд</b>\n\n"
        "Минимум: <b>50</b>\n"
        "Максимум: <b>100000</b>\n\n"
        "Напишите только число.",
        parse_mode=ParseMode.HTML
    )

    await callback.answer()

@router.message(OrderStates.waiting_custom_stars)
async def custom_stars_input(message: Message, state: FSMContext):

    if not message.text.isdigit():
        await message.answer("❌ Введите только число.")
        return

    stars = int(message.text)

    if stars < 50 or stars > 100000:
        await message.answer("❌ Можно купить от 50 до 100000 звёзд.")
        return

    price = round(stars * 1.45)

    await state.update_data(
        stars=stars,
        price=price
    )

    await state.set_state(OrderStates.waiting_recipient)

    await message.answer(
    f"<tg-emoji emoji-id='5954135079662916434'>☺</tg-emoji> <b>{stars} звёзд</b>\n"
    f"<tg-emoji emoji-id='5882200072581550212'>☺</tg-emoji> Стоимость: <b>{price} сом</b>\n\n"
    "<tg-emoji emoji-id='5879770735999717115'>☺</tg-emoji>Теперь отправьте <b>username получателя</b>.\n\n"
    "<tg-emoji emoji-id='4956611513369494230'>☺</tg-emoji><b>Внимательно проверьте username!</b>\n"
    "Если он указан неправильно, звёзды могут уйти другому пользователю.\n\n"
    "Пример:\n"
    "<code>@skobla</code>",
    parse_mode=ParseMode.HTML,
    reply_markup=back_to_catalog_keyboard()
)

@router.callback_query(F.data.startswith("buy_"))
async def process_buy(callback: CallbackQuery, state: FSMContext):
    stars = int(callback.data.split("_")[1])
    if stars not in PRODUCTS:
        await callback.answer("Ошибка позиции", show_alert=True)
        return

    await state.update_data(stars=stars, price=PRODUCTS[stars])
    price = PRODUCTS[stars]
    await state.set_state(OrderStates.waiting_recipient)

    await callback.message.answer(
    f"<tg-emoji emoji-id='5954135079662916434'>☺</tg-emoji><b>Вы выбрали {stars} звёзд</b>\n"
    f"<tg-emoji emoji-id='5262495450648300372'>☺</tg-emoji>К оплате: <b>{price} сом</b>\n\n"
    "<tg-emoji emoji-id='5879770735999717115'>☺</tg-emoji>Теперь отправьте <b>username получателя</b>.\n\n"
    "<tg-emoji emoji-id='4956611513369494230'>☺</tg-emoji><b>Внимательно проверьте username!</b>\n"
    "Если он указан неправильно, звёзды могут уйти другому пользователю.\n\n"
    "Пример:\n"
    "<code>@skobla</code>",
    parse_mode=ParseMode.HTML,
    reply_markup=back_to_catalog_keyboard()
)
    await callback.answer()
    
GIFTS = {
    "tree": {"name": "Ёлка", "emoji": "5345935030143196497"},
    "santa_bear": {"name": "Мишка в шапке", "emoji": "5379850840691476775"},
    "heart": {"name": "Сердечко", "emoji": "5224628072619216265"},
    "heart_bear": {"name": "Мишка с сердцем", "emoji": "5226661632259691727"},
    "pink_bear": {"name": "Розовый мишка", "emoji": "5289761157173775507"},
    "leprechaun": {"name": "Лепрекон", "emoji": "5317000922096769303"},
    "clown": {"name": "Клоун", "emoji": "5359736160224586485"},
    "bunny": {"name": "Зайчик", "emoji": "5393309541620291208"},
    "worker": {"name": "Рабочий", "emoji": "5447213743417105726"},
    "football": {"name": "Футбольный мишка", "emoji": "5397971251878732060"},
}

def gifts_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="145 сом", icon_custom_emoji_id="5345935030143196497", callback_data="gift_tree"),
                InlineKeyboardButton(text="145 сом", icon_custom_emoji_id="5379850840691476775", callback_data="gift_santa_bear"),
            ],
            [
                InlineKeyboardButton(text="145 сом", icon_custom_emoji_id="5224628072619216265", callback_data="gift_heart"),
                InlineKeyboardButton(text="145 сом", icon_custom_emoji_id="5226661632259691727", callback_data="gift_heart_bear"),
            ],
            [
                InlineKeyboardButton(text="145 сом", icon_custom_emoji_id="5289761157173775507", callback_data="gift_pink_bear"),
                InlineKeyboardButton(text="145 сом", icon_custom_emoji_id="5317000922096769303", callback_data="gift_leprechaun"),
            ],
            [
                InlineKeyboardButton(text="145 сом", icon_custom_emoji_id="5359736160224586485", callback_data="gift_clown"),
                InlineKeyboardButton(text="145 сом", icon_custom_emoji_id="5393309541620291208", callback_data="gift_bunny"),
            ],
            [
                InlineKeyboardButton(text="145 сом", icon_custom_emoji_id="5447213743417105726", callback_data="gift_worker"),
                InlineKeyboardButton(text="145 сом", icon_custom_emoji_id="5397971251878732060", callback_data="gift_football"),
            ],
            [
                InlineKeyboardButton(
                    text="Назад",
                    icon_custom_emoji_id="5280911767902378209",
                    callback_data="back_main"
                )
            ]
        ]
    )

@router.callback_query(F.data == "menu_gifts")
async def menu_gifts(callback: CallbackQuery):
    await callback.message.edit_text(
        "<tg-emoji emoji-id='5226661632259691727'>☺</tg-emoji> <b>Покупка удалённого подарка</b>\n\n"
        "<tg-emoji emoji-id='5879770735999717115'>☺</tg-emoji> Получатель: <b>@</b>\n"
        "<tg-emoji emoji-id='5981137088081301019'>☺</tg-emoji> Подпись: <b>?</b>\n\n"
        "<b>Выберите подарок:</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=gifts_keyboard()
    )
    await callback.answer()

@router.callback_query(F.data.startswith("gift_"))
async def gift_buy(callback: CallbackQuery, state: FSMContext):
    gift = callback.data.replace("gift_", "")

    await state.update_data(
        order_type="gift",
        gift=gift,
        price=145
    )
    await state.set_state(OrderStates.waiting_gift_username)

    await callback.message.answer(
        "<tg-emoji emoji-id='5370781982886220096'>☺</tg-emoji><b>Удалённый подарок</b>\n\n"
        "<tg-emoji emoji-id='5262495450648300372'>☺</tg-emoji> Стоимость: <b>145 сом</b>\n\n"
        "<tg-emoji emoji-id='5879770735999717115'>☺</tg-emoji>Теперь отправьте username получателя.\n\n"
        "Пример:\n"
        "<code>@skobla</code>",
        parse_mode=ParseMode.HTML
    )
    await callback.answer()

@router.message(OrderStates.waiting_gift_username)
async def gift_username(message: Message, state: FSMContext):
    recipient = message.text.strip().lstrip("@")

    if len(recipient) < 3:
        await message.answer("❌ Некорректный username.")
        return

    await state.update_data(recipient=recipient)
    await state.set_state(OrderStates.waiting_gift_text)

    await message.answer(
        "<tg-emoji emoji-id='5258500400918587241'>☺</tg-emoji><b>Теперь отправьте подпись к подарку.</b>\n\n"
        "Если подпись не нужна — отправьте\n"
        "<code>-</code>",
        parse_mode=ParseMode.HTML
    )

@router.message(OrderStates.waiting_gift_text)
async def gift_text(message: Message, state: FSMContext):
    gift_text = message.text.strip()
    if gift_text == "-":
        gift_text = ""

    data = await state.get_data()
    gift = data["gift"]
    recipient = data["recipient"]
    price = data["price"]
    user = message.from_user
    username = user.username or "без_username"

    order_id = await create_order(
        user_id=user.id,
        username=username,
        recipient=recipient,
        stars=gift,
        price=price,
        product_type="gift"
    )

    await state.update_data(
        order_id=order_id,
        gift_text=gift_text
    )
    await state.set_state(OrderStates.waiting_payment_check)

    caption = (
        f"<tg-emoji emoji-id='5204234309472372120'>☺</tg-emoji><b>Заказ #{order_id} создан</b>\n\n"
        f"<tg-emoji emoji-id='5370781982886220096'>☺</tg-emoji> Подарок: <b>{GIFTS[gift]['name']}</b>\n"
        f"👤 Получатель: <b>@{recipient}</b>\n"
        f"<tg-emoji emoji-id='5258500400918587241'>☺</tg-emoji>Подпись: <b>{gift_text if gift_text else 'Без подписи'}</b>\n"
        f"<tg-emoji emoji-id='5262495450648300372'>☺</tg-emoji>К оплате: <b>{price} сом</b>\n\n"
        "<tg-emoji emoji-id='5379732256644405206'>☺</tg-emoji>Отсканируйте QR-код и оплатите любым удобным вам банком."
    )

    try:
        photo = FSInputFile(QR_PATH)
        await message.answer_photo(photo=photo, caption=caption, parse_mode=ParseMode.HTML)
    except Exception:
        await message.answer(caption, parse_mode=ParseMode.HTML)

    await message.answer(
        "<tg-emoji emoji-id='5444856076954520455'>☺</tg-emoji>После оплаты отправьте чек и ожидайте выдачу в течение нескольких минут.",
        parse_mode=ParseMode.HTML
    )
    
@router.message(OrderStates.waiting_premium_username)
async def premium_username(message: Message, state: FSMContext):

    username = message.text.strip().lstrip("@")

    if len(username) < 3:
        await message.answer("❌ Некорректный username.")
        return

    data = await state.get_data()

    months = data["premium_months"]
    price = data["price"]

    user = message.from_user
    username_user = user.username or "без_username"

    order_id = await create_order(
        user_id=user.id,
        username=username_user,
        recipient=username,
        stars=months,
        price=price,
        product_type="premium"
    )

    await state.update_data(
        order_type="premium",
        recipient=username,
        premium_months=months,
        price=price,
        order_id=order_id
    )

    caption = (
        "<tg-emoji emoji-id='5204234309472372120'>☺</tg-emoji> <b>Заказ Telegram Premium создан</b>\n\n"
        f"<tg-emoji emoji-id='5453888208494402519'>☺</tg-emoji> Подписка: <b>{months} мес.</b>\n"
        f"<tg-emoji emoji-id='5192751744471288987'>☺</tg-emoji>К оплате: <b>{price} сом</b>\n"
        f"<tg-emoji emoji-id='5879770735999717115'>☺</tg-emoji>Получатель: <b>@{username}</b>\n\n"
        "<tg-emoji emoji-id='5379732256644405206'>☺</tg-emoji>Отсканируйте QR-код и оплатите любым удобным вам банком."
    )

    try:
        photo = FSInputFile(QR_PATH)
        await message.answer_photo(
            photo=photo,
            caption=caption,
            parse_mode=ParseMode.HTML
        )
    except Exception:
        await message.answer(
            caption,
            parse_mode=ParseMode.HTML
        )

    await state.set_state(OrderStates.waiting_payment_check)

    await message.answer(
        "<tg-emoji emoji-id='5444856076954520455'>☺</tg-emoji>После оплаты отправьте чек и ожидайте выдачи в течение нескольких минут",
        parse_mode=ParseMode.HTML
    )

@router.callback_query(F.data.startswith("reject_"))
async def reject_payment(callback: CallbackQuery, bot: Bot):

    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Только для админа", show_alert=True)
        return

    order_id = int(callback.data.split("_")[1])

    order = await get_order(order_id)

    if not order:
        await callback.answer("Заказ не найден", show_alert=True)
        return

    await bot.send_message(
        chat_id=order["user_id"],
        text=(
            "❌ <b>Чек не прошёл проверку.</b>\n\n"
            "Пожалуйста, отправьте корректный чек ещё раз."
        ),
        parse_mode=ParseMode.HTML
    )

    await callback.answer("Покупатель уведомлён.")

@router.callback_query(F.data.startswith("approve_"))
async def process_complete(callback: CallbackQuery, bot: Bot):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Только для админа", show_alert=True)
        return

    order_id = int(callback.data.split("approve_")[1])
    order = await get_order(order_id)

    if not order:
        await callback.answer("Заказ не найден", show_alert=True)
        return

    if order["status"] == "completed":
        await callback.answer("Уже выдано ранее", show_alert=True)
        return

    success = await complete_order(order_id)
    if not success:
        await callback.answer("Ошибка", show_alert=True)
        return
        
    today_profit = await get_today_profit()
    order_profit = calculate_order_profit(order)

    today_profit += order_profit

    product_type = order.get("product_type", "stars")

    try:
        if product_type == "premium":
            text = (
    f"<tg-emoji emoji-id='5204234309472372120'>☺</tg-emoji><b>Заказ #{order_id} выполнен!</b>\n\n"
    f"<tg-emoji emoji-id='5453888208494402519'>☺</tg-emoji>Telegram Premium на <b>{order['stars']} мес.</b> успешно отправлен пользователю "
    f"@{order['recipient']}.\n\n"
    "Спасибо за покупку и ждем вас еще! ❤️"
)
        elif product_type == "gift":
            text = (
    f"<tg-emoji emoji-id='5204234309472372120'>☺</tg-emoji><b>Заказ #{order_id} выполнен!</b>\n\n"
    f"<tg-emoji emoji-id='5370781982886220096'>☺</tg-emoji>Подарок успешно отправлен пользователю @{order['recipient']}.\n\n"
    "Спасибо за покупку и ждем вас еще! ❤️"
)
        else:
            text = (
    f"<tg-emoji emoji-id='5204234309472372120'>☺</tg-emoji><b>Заказ #{order_id} выполнен!</b>\n\n"
    f"<tg-emoji emoji-id='5954135079662916434'>☺</tg-emoji>{order['stars']} звёзд успешно отправлены пользователю "
    f"@{order['recipient']}.\n\n"
    "Спасибо за покупку и ждем вас еще! ❤️"
)

        await bot.send_message(
            chat_id=order["user_id"],
            text=text,
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.error(f"Не удалось уведомить покупателя: {e}")

    
    new_text = (
        f"✅ <b>ЗАКАЗ #{order_id} ВЫДАН</b>\n\n"
        f"Тип: <b>{product_type}</b>\n"
        f"Значение: <b>{order['stars']}</b>\n"
        f"Цена: <b>{order['price']}</b>\n"
        f"Покупатель: @{order['username']}\n"
        f"Получатель: @{order['recipient']}\n\n"
        f"Прибыль с заказа: <b>{order_profit} сом</b>\n"
        f"Прибыль за сегодня: <b>{today_profit} сом</b>"
    )
    await callback.message.edit_text(new_text, parse_mode=ParseMode.HTML)
    await callback.answer("Готово! Покупатель уведомлён ✅")


@router.message(Command("stats"))
async def cmd_stats(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    profit = await get_today_profit()
    cursor = await db.execute("SELECT COUNT(*) FROM orders WHERE status = 'pending'")
    pending = (await cursor.fetchone())[0]
    await message.answer(
        f"📊 <b>Статистика</b>\n\n"
        f"💰 Прибыль за сегодня: <b>{profit} сом</b>\n"
        f"⏳ Ожидают выдачи: <b>{pending}</b>",
        parse_mode=ParseMode.HTML
    )

@router.message(OrderStates.waiting_recipient)
async def recipient_input(message: Message, state: FSMContext):

    recipient = message.text.strip().lstrip("@")

    if len(recipient) < 3:
        await message.answer("❌ Некорректный username.")
        return

    data = await state.get_data()

    stars = data["stars"]
    price = data["price"]

    user = message.from_user
    username = user.username or "без_username"

    order_id = await create_order(
        user_id=user.id,
        username=username,
        recipient=recipient,
        stars=stars,
        price=price,
        product_type="stars"
    )

    await state.update_data(
        recipient=recipient,
        order_id=order_id,
        order_type="stars"
    )

    caption = (
        f" <tg-emoji emoji-id='5954135079662916434'>☺</tg-emoji><b>Заказ #{order_id} создан</b>\n\n"
        f"<tg-emoji emoji-id='5954135079662916434'>☺</tg-emoji> Количество: <b>{stars}</b>\n"
        f"<tg-emoji emoji-id='5262495450648300372'>☺</tg-emoji>К оплате: <b>{price} сом</b>\n"
        f"<tg-emoji emoji-id='5879770735999717115'>☺</tg-emoji> Получатель: <b>@{recipient}</b>\n\n"
        "<tg-emoji emoji-id='5379732256644405206'>☺</tg-emoji>Отсканируйте QR-код и оплатите любым удобным банком."
    )

    try:
        photo = FSInputFile(QR_PATH)
        await message.answer_photo(
            photo=photo,
            caption=caption,
            parse_mode=ParseMode.HTML
        )
    except Exception:
        await message.answer(
            caption,
            parse_mode=ParseMode.HTML
        )

    await state.set_state(OrderStates.waiting_payment_check)

    await message.answer(
    "<tg-emoji emoji-id='5444856076954520455'>☺</tg-emoji> После оплаты отправьте чек и ожидайте выдачу в течение нескольких минут.",
    parse_mode=ParseMode.HTML
)

@router.message(OrderStates.waiting_payment_check)
async def payment_check(message: Message, state: FSMContext, bot: Bot):

    if not message.photo:
        await message.answer(
            "❌ Отправьте именно фотографию или скриншот чека."
        )
        return

    data = await state.get_data()

    order_type = data.get("order_type", "stars")

    order = await get_order(data["order_id"])

    if not order:
        await message.answer("❌ Заказ не найден.")
        await state.clear()
        return

    today_profit = await get_today_profit()

    gift = data.get("gift")
    gift_text = data.get("gift_text", "")

    if order_type == "gift":
        admin_text = (
            "🎁 <b>Новый заказ удалённого подарка!</b>\n\n"
            f"🎁 Подарок: <b>{GIFTS[gift]['name']}</b>\n"
            f"👤 Покупатель: @{order['username']} (id: <code>{order['user_id']}</code>)\n"
            f"👤 Получатель: @{order['recipient']}\n"
            f"💌 Подпись: <b>{gift_text if gift_text else 'Без подписи'}</b>\n\n"
            f"💷 Цена: <b>{order['price']} сом</b>\n\n"
            f"👛 Прибыль за сегодня: <b>{today_profit} сом</b>\n"
            f"👛 Прибыль с заказа: <b>{calculate_order_profit(order)} сом</b>\n\n"
            f"🔢 Номер заказа: <b>#{order['id']}</b>"
        )
    elif order_type == "premium":
        admin_text = (
            f"💎 <b>Новая покупка Premium!</b>\n\n"
            f"💎 Срок: <b>{order['stars']} мес.</b>\n"
            f"💷 Цена: <b>{order['price']} сом</b>\n"
            f"👤 Покупатель: @{order['username']} (id: <code>{order['user_id']}</code>)\n"
            f"👤 Получатель: @{order['recipient']}\n\n"
            f"👛 Прибыль за сегодня: <b>{today_profit} сом</b>\n"
            f"👛 Прибыль с заказа: <b>{calculate_order_profit(order)} сом</b>\n\n"
            f"🔢 Номер заказа: <b>#{order['id']}</b>"
        )
    else:
        admin_text = (
            f"⭐️ <b>Новая покупка звёзд!</b>\n\n"
            f"⭐️ Сумма: <b>{order['stars']}</b>\n"
            f"💷 Цена: <b>{order['price']} сом</b>\n"
            f"👤 Покупатель: @{order['username']} (id: <code>{order['user_id']}</code>)\n"
            f"👤 Получатель: @{order['recipient']}\n\n"
            f"👛 Прибыль за сегодня: <b>{today_profit} сом</b>\n"
            f"👛 Прибыль с заказа: <b>{calculate_order_profit(order)} сом</b>\n\n"
            f"🔢 Номер заказа: <b>#{order['id']}</b>"
        )

    await bot.send_photo(
        chat_id=ADMIN_ID,
        photo=message.photo[-1].file_id,
        caption=admin_text,
        parse_mode=ParseMode.HTML,
        reply_markup=complete_keyboard(order["id"])
    )

    await message.answer(
    "<tg-emoji emoji-id='5204234309472372120'>☺</tg-emoji> <b>Чек отправлен на проверку.</b>\n\n"
    "<tg-emoji emoji-id='5208619406657082341'>☺</tg-emoji>После проверки оплаты звёзды будут отправлены в течение нескольких минут.",
    parse_mode=ParseMode.HTML
)

    await state.clear()

async def main():
    await init_db()
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    logger.info("Бот запущен")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())