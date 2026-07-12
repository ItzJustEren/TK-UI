# telegram_bot.py
# ربات فروش Tk-Ui با Aiogram — Long Polling

import asyncio
import os
import secrets
from datetime import datetime, timedelta
from typing import Optional

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest

from main import (
    LINKS, LINKS_LOCK, SUBS, SUBS_LOCK,
    PRODUCTS, PRODUCTS_LOCK, ORDERS, ORDERS_LOCK,
    CARD_NUMBER, CARD_OWNER_NAME, PRICE_PER_GB, ADMIN_IDS, OWNER_ID,
    make_link, create_sub_group, set_link_sub,
    get_host, generate_random_password,
    is_link_allowed, fmt_bytes, vless_link_for_link,
    log_activity, save_state, logger,
    DEFAULT_PROTOCOL, DEFAULT_FINGERPRINT,
    DEFAULT_PORT,
    parse_speed_to_bytes,
)

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
if not BOT_TOKEN:
    logger.warning("TELEGRAM_BOT_TOKEN not set")
    raise RuntimeError("Bot token missing")

if not ADMIN_IDS and OWNER_ID:
    ADMIN_IDS.add(OWNER_ID)
    os.environ["TELEGRAM_ADMIN_IDS"] = str(OWNER_ID)

REQUIRED_CHANNEL = os.environ.get("REQUIRED_CHANNEL", "@TaaKaaOrg").strip()
if not REQUIRED_CHANNEL.startswith("@"):
    REQUIRED_CHANNEL = "@" + REQUIRED_CHANNEL

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

class BuyStates(StatesGroup):
    waiting_receipt = State()
    waiting_volume = State()

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

async def check_channel_membership(user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id=REQUIRED_CHANNEL, user_id=user_id)
        return member.status in ("member", "administrator", "creator")
    except Exception:
        return False

def get_products_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for pid, prod in PRODUCTS.items():
        builder.button(
            text=f"{prod['name']} — {prod['volume_gb']}GB / {prod['duration_days']} روز — {prod['price']:,} تومان",
            callback_data=f"buy:{pid}"
        )
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 منوی اصلی", callback_data="main_menu"))
    return builder.as_markup()

async def send_order_to_admins(order_id: str, user_id: int, product: dict, receipt_msg: types.Message):
    order = ORDERS.get(order_id)
    if not order:
        return
    user = await bot.get_chat(user_id)
    username = user.username or "ندارد"
    full_name = user.full_name or "کاربر"

    text = (
        f"🆕 سفارش جدید #{order_id}\n"
        f"👤 کاربر: {full_name} (@{username}) [ID: {user_id}]\n"
        f"📦 محصول: {product['name']}\n"
        f"📊 حجم: {product['volume_gb']} GB\n"
        f"⏳ مدت: {product['duration_days']} روز\n"
        f"🚀 سرعت: {product['speed_mbps']} Mbps {'(نامحدود)' if product['speed_mbps'] == 0 else ''}\n"
        f"💰 قیمت: {product['price']:,} تومان\n"
        f"🕒 زمان سفارش: {order['created_at']}\n"
        f"🖼 رسید:"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ تایید", callback_data=f"approve:{order_id}"),
         InlineKeyboardButton(text="❌ رد", callback_data=f"reject:{order_id}")]
    ])

    for admin_id in ADMIN_IDS:
        try:
            await bot.send_photo(
                chat_id=admin_id,
                photo=receipt_msg.photo[-1].file_id,
                caption=text,
                reply_markup=keyboard
            )
        except Exception:
            pass

# ── Start ────────────────────────────────────────────────────────────────────
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id

    if not await check_channel_membership(user_id):
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📢 عضویت در کانال", url=f"https://t.me/{REQUIRED_CHANNEL.lstrip('@')}")],
            [InlineKeyboardButton(text="✅ عضویت را بررسی کن", callback_data="check_membership")]
        ])
        await message.answer(
            f"👋 کاربر عزیز، برای استفاده از ربات فروش Tk-Ui لطفاً ابتدا در کانال زیر عضو شوید:\n\n{REQUIRED_CHANNEL}",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        return

    await show_main_menu(message)

async def show_main_menu(message: types.Message):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 خرید محصول", callback_data="buy")],
        [InlineKeyboardButton(text="📋 سفارشات من", callback_data="my_orders")],
    ])
    if is_admin(message.from_user.id):
        keyboard.inline_keyboard.append([InlineKeyboardButton(text="⚙️ پنل ادمین", callback_data="admin_panel")])
    await message.answer(
        "👋 به ربات فروش Tk-Ui خوش آمدید.\n"
        "لطفاً یکی از گزینه‌های زیر را انتخاب کنید:",
        reply_markup=keyboard
    )

@dp.callback_query(F.data == "main_menu")
async def callback_main_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer()
    await show_main_menu(callback.message)
    try:
        await callback.message.delete()
    except:
        pass

@dp.callback_query(F.data == "check_membership")
async def callback_check_membership(callback: CallbackQuery):
    if await check_channel_membership(callback.from_user.id):
        await callback.answer("✅ عضویت تأیید شد!", show_alert=True)
        await show_main_menu(callback.message)
        await callback.message.delete()
    else:
        await callback.answer("❌ هنوز عضو نشده‌اید.", show_alert=True)

# ── Buy ──────────────────────────────────────────────────────────────────────
@dp.callback_query(F.data == "buy")
async def callback_buy(callback: CallbackQuery):
    if not PRODUCTS:
        await callback.answer("❌ هیچ محصولی موجود نیست.", show_alert=True)
        return
    await callback.answer()
    await callback.message.edit_text(
        "🛒 لیست محصولات:\n\nلطفاً یکی را انتخاب کنید:",
        reply_markup=get_products_keyboard()
    )

@dp.callback_query(F.data.startswith("buy:"))
async def callback_product_select(callback: CallbackQuery, state: FSMContext):
    product_id = callback.data.split(":")[1]
    product = PRODUCTS.get(product_id)
    if not product:
        await callback.answer("❌ محصول یافت نشد.", show_alert=True)
        return
    await state.update_data(product_id=product_id)

    text = (
        f"📦 <b>{product['name']}</b>\n"
        f"📊 حجم: {product['volume_gb']} GB\n"
        f"⏳ مدت: {product['duration_days']} روز\n"
        f"🚀 سرعت: {product['speed_mbps']} Mbps {'(نامحدود)' if product['speed_mbps'] == 0 else ''}\n"
        f"💰 قیمت: {product['price']:,} تومان\n\n"
        "برای خرید، روی دکمه زیر کلیک کنید."
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 خرید", callback_data=f"confirm_buy:{product_id}")],
        [InlineKeyboardButton(text="🔙 بازگشت", callback_data="buy")]
    ])
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data.startswith("confirm_buy:"))
async def callback_confirm_buy(callback: CallbackQuery, state: FSMContext):
    product_id = callback.data.split(":")[1]
    product = PRODUCTS.get(product_id)
    if not product:
        await callback.answer("❌ محصول یافت نشد.", show_alert=True)
        return

    order_id = secrets.token_hex(8).upper()
    order = {
        "order_id": order_id,
        "user_id": callback.from_user.id,
        "product_id": product_id,
        "volume": product['volume_gb'],
        "duration": product['duration_days'],
        "speed": product['speed_mbps'],
        "price": product['price'],
        "status": "pending",
        "created_at": datetime.now().isoformat(),
        "config_uuid": None,
        "sub_id": None,
    }
    async with ORDERS_LOCK:
        ORDERS[order_id] = order
    asyncio.create_task(save_state())

    # پیام پرداخت با نام صاحب کارت و مهلت ۱ ساعته
    payment_text = (
        f"💳 مشتری عزیز، مبلغ <b>{product['price']:,}</b> تومان را به کارت زیر به نام <b>{CARD_OWNER_NAME}</b> واریز کنید:\n\n"
        f"<b>{CARD_NUMBER}</b>\n\n"
        f"⏳ توجه: شما تا <b>۱ ساعت</b> پس از این پیام مهلت دارید تا رسید را ارسال کنید.\n"
        f"اگر بعد از ۱ ساعت حتی ۱ دقیقه دیرتر رسید را ارسال کنید، کانفیگی دریافت نخواهید کرد و مسئولیتی متوجه ما نیست."
    )
    await callback.message.edit_text(
        f"🛍 سفارش شما ثبت شد.\nشماره سفارش: <code>{order_id}</code>\n\n{payment_text}",
        parse_mode="HTML"
    )
    await state.set_state(BuyStates.waiting_receipt)
    await state.update_data(order_id=order_id, order_time=datetime.now())
    await callback.answer()

# ── Receipt ──────────────────────────────────────────────────────────────────
@dp.message(BuyStates.waiting_receipt, F.photo)
async def handle_receipt(message: types.Message, state: FSMContext):
    data = await state.get_data()
    order_id = data.get("order_id")
    order_time = data.get("order_time")
    order = ORDERS.get(order_id)
    if not order:
        await message.answer("❌ سفارش یافت نشد. لطفاً دوباره از منوی خرید اقدام کنید.")
        await state.clear()
        return

    # بررسی مهلت ۱ ساعته
    if order_time:
        elapsed = (datetime.now() - order_time).total_seconds()
        if elapsed > 3600:
            await message.answer(
                "⛔ متأسفانه مهلت ۱ ساعته شما به پایان رسیده است.\n"
                "لطفاً دوباره از منوی خرید اقدام کنید."
            )
            await state.clear()
            return

    product = PRODUCTS.get(order['product_id'])
    if product:
        await send_order_to_admins(order_id, order['user_id'], product, message)

    await message.answer(
        "✅ رسید شما دریافت شد و در انتظار تأیید ادمین است.\n"
        "به محض تأیید، لینک‌های دانلود برای شما ارسال خواهد شد."
    )
    await state.clear()

@dp.message(BuyStates.waiting_receipt)
async def handle_invalid_receipt(message: types.Message):
    await message.answer("❌ لطفاً تصویر رسید را به‌صورت عکس ارسال کنید.")

# ── Approve/Reject ──────────────────────────────────────────────────────────
@dp.callback_query(F.data.startswith("approve:"))
async def callback_approve_order(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ دسترسی ندارید.", show_alert=True)
        return
    order_id = callback.data.split(":")[1]
    order = ORDERS.get(order_id)
    if not order or order["status"] != "pending":
        await callback.answer("سفارش یافت نشد یا قبلاً بررسی شده.", show_alert=True)
        return

    user_id = order['user_id']
    product = PRODUCTS.get(order['product_id'])
    if not product:
        await callback.answer("❌ محصول حذف شده است.", show_alert=True)
        return

    volume_bytes = product['volume_gb'] * 1024 * 1024 * 1024
    duration_days = product['duration_days']
    expires_at = (datetime.now() + timedelta(days=duration_days)).isoformat()
    speed_bps = 0 if product['speed_mbps'] == 0 else int(product['speed_mbps'] * 1024 * 1024 / 8)

    uuid, link = await make_link(
        label=f"سفارش {order_id} - {product['name']}",
        limit_bytes=volume_bytes,
        expires_at=expires_at,
        note=f"سفارش #{order_id} - حجم {product['volume_gb']}GB",
        protocol=DEFAULT_PROTOCOL,
        fingerprint=DEFAULT_FINGERPRINT,
        alpn="",
        port=DEFAULT_PORT,
        ip_limit=0,
        speed_limit_bytes=speed_bps,
    )

    sub_password = generate_random_password(8)
    sub_id, sub = await create_sub_group(
        name=f"سفارش {order_id} - {product['name']}",
        desc=f"کانفیگ سفارش #{order_id} - حجم {product['volume_gb']}GB",
        password=sub_password
    )
    await set_link_sub(uuid, sub_id)

    async with ORDERS_LOCK:
        ORDERS[order_id]["status"] = "confirmed"
        ORDERS[order_id]["config_uuid"] = uuid
        ORDERS[order_id]["sub_id"] = sub_id

    asyncio.create_task(save_state())

    host = get_host()
    vless_link = vless_link_for_link(link, uuid, host)
    sub_url = f"https://{host}/p/{sub['uuid_key']}"

    # پیام موفقیت به کاربر
    success_msg = (
        f"🎉 تبریک! خرید شما با موفقیت انجام شد.\n"
        f"امیدواریم از خریدتان راضی باشید.\n"
        f"از طرف Tk-Ui ❤️\n\n"
        f"📌 <b>لینک ساب (با پسورد):</b>\n"
        f"<code>{sub_url}</code>\n\n"
        f"🔑 <b>پسورد ساب:</b>\n"
        f"<code>{sub_password}</code>\n\n"
        f"📊 <b>مشخصات کانفیگ:</b>\n"
        f"حجم: {product['volume_gb']} GB\n"
        f"مدت: {product['duration_days']} روز\n"
        f"سرعت: {product['speed_mbps']} Mbps {'(نامحدود)' if product['speed_mbps'] == 0 else ''}\n\n"
        f"🔗 <b>لینک VLESS:</b>\n"
        f"<code>{vless_link}</code>"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📥 دریافت لینک ساب", url=sub_url)],
        [InlineKeyboardButton(text="📥 دریافت کانفیگ VLESS", callback_data=f"get_vless:{uuid}")]
    ])

    await bot.send_message(
        chat_id=user_id,
        text=success_msg,
        parse_mode="HTML",
        reply_markup=keyboard
    )

    await callback.message.edit_text(f"✅ سفارش #{order_id} تأیید و کانفیگ ارسال شد.")
    await callback.answer()

@dp.callback_query(F.data.startswith("reject:"))
async def callback_reject_order(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ دسترسی ندارید.", show_alert=True)
        return
    order_id = callback.data.split(":")[1]
    order = ORDERS.get(order_id)
    if not order or order["status"] != "pending":
        await callback.answer("سفارش یافت نشد.", show_alert=True)
        return
    async with ORDERS_LOCK:
        ORDERS[order_id]["status"] = "rejected"
    asyncio.create_task(save_state())
    await callback.message.edit_text(f"❌ سفارش #{order_id} رد شد.")
    await callback.answer()

@dp.callback_query(F.data.startswith("get_vless:"))
async def callback_get_vless(callback: CallbackQuery):
    uuid = callback.data.split(":")[1]
    link = LINKS.get(uuid)
    if not link or not is_link_allowed(link):
        await callback.answer("❌ کانفیگ یافت نشد یا غیرفعال است.", show_alert=True)
        return
    host = get_host()
    vless = vless_link_for_link(link, uuid, host)
    await callback.message.answer(f"🔗 کانفیگ VLESS:\n<code>{vless}</code>", parse_mode="HTML")
    await callback.answer()

# ── My Orders ──────────────────────────────────────────────────────────────
@dp.callback_query(F.data == "my_orders")
async def callback_my_orders(callback: CallbackQuery):
    user_orders = [o for o in ORDERS.values() if o["user_id"] == callback.from_user.id]
    if not user_orders:
        await callback.answer("شما هیچ سفارشی ندارید.", show_alert=True)
        return
    text = "📋 لیست سفارشات شما:\n\n"
    for o in user_orders[-5:]:
        status_map = {
            "pending": "⏳ در انتظار تأیید",
            "confirmed": "✅ تأیید شده",
            "rejected": "❌ رد شده",
            "delivered": "📦 تحویل داده شده"
        }
        text += f"#{o['order_id']} — {status_map.get(o['status'], o['status'])}\n"
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 منوی اصلی", callback_data="main_menu")]
    ]))
    await callback.answer()

# ── Admin Panel ─────────────────────────────────────────────────────────────
@dp.callback_query(F.data == "admin_panel")
async def callback_admin_panel(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ دسترسی ندارید.", show_alert=True)
        return
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📦 مدیریت محصولات", callback_data="admin_products")],
        [InlineKeyboardButton(text="📋 سفارشات", callback_data="admin_orders:0")],
        [InlineKeyboardButton(text="👥 مدیریت ادمین‌ها", callback_data="admin_admins")],
        [InlineKeyboardButton(text="⚙️ تنظیمات", callback_data="admin_settings")],
        [InlineKeyboardButton(text="📊 آمار", callback_data="admin_stats")],
        [InlineKeyboardButton(text="🔙 منوی اصلی", callback_data="main_menu")]
    ])
    await callback.message.edit_text("⚙️ پنل مدیریت ربات:", reply_markup=keyboard)
    await callback.answer()

@dp.callback_query(F.data == "admin_products")
async def callback_admin_products(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ دسترسی ندارید.", show_alert=True)
        return
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ افزودن محصول", callback_data="admin_add_product")],
    ])
    if PRODUCTS:
        keyboard.inline_keyboard.append([InlineKeyboardButton(text="🗑 حذف محصول", callback_data="admin_delete_product")])
    keyboard.inline_keyboard.append([InlineKeyboardButton(text="🔙 بازگشت", callback_data="admin_panel")])
    await callback.message.edit_text("📦 مدیریت محصولات:", reply_markup=keyboard)
    await callback.answer()

@dp.callback_query(F.data == "admin_add_product")
async def callback_add_product(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ دسترسی ندارید.", show_alert=True)
        return
    await callback.message.edit_text(
        "لطفاً اطلاعات محصول جدید را به صورت زیر ارسال کنید:\n\n"
        "`نام محصول | حجم(GB) | مدت(روز) | سرعت(Mbps)`\n\n"
        "مثال: `کانفیگ استاندارد | 50 | 30 | 100`\n\n"
        "⚠️ قیمت به‌صورت خودکار بر اساس قیمت هر گیگ محاسبه می‌شود."
    )
    await state.set_state("waiting_product_data")
    await callback.answer()

@dp.message(StateFilter("waiting_product_data"))
async def handle_add_product(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ دسترسی ندارید.")
        return
    try:
        parts = [p.strip() for p in message.text.split("|")]
        if len(parts) != 4:
            raise ValueError("تعداد پارامترها صحیح نیست")
        name, volume, duration, speed = parts
        volume = float(volume)
        duration = int(duration)
        speed = float(speed)
        if volume <= 0 or duration <= 0:
            raise ValueError("مقادیر باید مثبت باشند")
        price = volume * PRICE_PER_GB
        product_id = secrets.token_hex(8)
        async with PRODUCTS_LOCK:
            PRODUCTS[product_id] = {
                "product_id": product_id,
                "name": name,
                "volume_gb": volume,
                "duration_days": duration,
                "speed_mbps": speed,
                "price": price,
                "created_at": datetime.now().isoformat(),
            }
        asyncio.create_task(save_state())
        log_activity("product", f"محصول «{name}» با قیمت {price} تومان اضافه شد", "ok")
        await message.answer(f"✅ محصول «{name}» با موفقیت اضافه شد.\nقیمت: {price:,} تومان")
    except Exception as e:
        await message.answer(f"❌ خطا: {e}\nلطفاً فرمت را رعایت کنید.")
    await state.clear()

@dp.callback_query(F.data == "admin_delete_product")
async def callback_delete_product(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ دسترسی ندارید.", show_alert=True)
        return
    builder = InlineKeyboardBuilder()
    for pid, prod in PRODUCTS.items():
        builder.button(text=f"{prod['name']} - {prod['price']:,} تومان", callback_data=f"del_prod:{pid}")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 بازگشت", callback_data="admin_products"))
    await callback.message.edit_text("🗑 برای حذف یک محصول، روی آن کلیک کنید:", reply_markup=builder.as_markup())
    await callback.answer()

@dp.callback_query(F.data.startswith("del_prod:"))
async def callback_del_prod(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ دسترسی ندارید.", show_alert=True)
        return
    product_id = callback.data.split(":")[1]
    async with PRODUCTS_LOCK:
        if product_id in PRODUCTS:
            name = PRODUCTS[product_id]["name"]
            del PRODUCTS[product_id]
            asyncio.create_task(save_state())
            log_activity("product", f"محصول «{name}» حذف شد", "warn")
            await callback.message.edit_text(f"✅ محصول «{name}» حذف شد.")
        else:
            await callback.message.edit_text("❌ محصول یافت نشد.")
    await callback.answer()

@dp.callback_query(F.data == "admin_admins")
async def callback_admin_admins(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ دسترسی ندارید.", show_alert=True)
        return
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ افزودن ادمین", callback_data="admin_add_admin")],
        [InlineKeyboardButton(text="🔙 بازگشت", callback_data="admin_panel")]
    ])
    await callback.message.edit_text(
        f"👥 لیست ادمین‌ها:\n\n" + "\n".join(f"🆔 {uid}" for uid in ADMIN_IDS) +
        f"\n👑 اونر: {OWNER_ID}",
        reply_markup=keyboard
    )
    await callback.answer()

@dp.callback_query(F.data == "admin_add_admin")
async def callback_add_admin(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ دسترسی ندارید.", show_alert=True)
        return
    await callback.message.edit_text("لطفاً آیدی عددی ادمین جدید را ارسال کنید:")
    await state.set_state("waiting_admin_id")
    await callback.answer()

@dp.message(StateFilter("waiting_admin_id"))
async def handle_add_admin(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ دسترسی ندارید.")
        return
    try:
        user_id = int(message.text.strip())
        global ADMIN_IDS
        ADMIN_IDS.add(user_id)
        os.environ["TELEGRAM_ADMIN_IDS"] = ",".join(str(x) for x in ADMIN_IDS)
        asyncio.create_task(save_state())
        log_activity("admin", f"ادمین جدید اضافه شد: {user_id}", "ok")
        await message.answer(f"✅ ادمین {user_id} با موفقیت اضافه شد.")
    except ValueError:
        await message.answer("❌ آیدی باید عددی باشد.")
    await state.clear()

@dp.callback_query(F.data == "admin_settings")
async def callback_admin_settings(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ دسترسی ندارید.", show_alert=True)
        return
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 تغییر شماره کارت", callback_data="admin_change_card")],
        [InlineKeyboardButton(text="💰 تغییر قیمت هر گیگ", callback_data="admin_change_price")],
        [InlineKeyboardButton(text="🔙 بازگشت", callback_data="admin_panel")]
    ])
    await callback.message.edit_text(
        f"⚙️ تنظیمات\n\n"
        f"💳 شماره کارت فعلی: <code>{CARD_NUMBER}</code>\n"
        f"👤 نام صاحب کارت: <b>{CARD_OWNER_NAME}</b>\n"
        f"💰 قیمت هر گیگ: <b>{PRICE_PER_GB} هزار تومان</b>",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await callback.answer()

@dp.callback_query(F.data == "admin_change_card")
async def callback_change_card(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ دسترسی ندارید.", show_alert=True)
        return
    await callback.message.edit_text(
        "لطفاً اطلاعات جدید کارت را به صورت زیر ارسال کنید:\n\n"
        "`شماره کارت | نام صاحب کارت`\n\n"
        "مثال: `6037-9910-1234-5678 | علی محمدی`"
    )
    await state.set_state("waiting_card_data")
    await callback.answer()

@dp.message(StateFilter("waiting_card_data"))
async def handle_card_data(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ دسترسی ندارید.")
        return
    try:
        parts = [p.strip() for p in message.text.split("|")]
        if len(parts) != 2:
            raise ValueError("فرمت صحیح نیست")
        card_number = parts[0]
        owner_name = parts[1]
        if not card_number:
            raise ValueError("شماره کارت نمی‌تواند خالی باشد")
        global CARD_NUMBER, CARD_OWNER_NAME
        CARD_NUMBER = card_number
        CARD_OWNER_NAME = owner_name if owner_name else CARD_OWNER_NAME
        os.environ["CARD_NUMBER"] = card_number
        os.environ["CARD_OWNER_NAME"] = CARD_OWNER_NAME
        asyncio.create_task(save_state())
        log_activity("settings", f"اطلاعات کارت تغییر کرد: {card_number} - {CARD_OWNER_NAME}", "ok")
        await message.answer(f"✅ اطلاعات کارت با موفقیت به‌روزرسانی شد.")
    except Exception as e:
        await message.answer(f"❌ خطا: {e}")
    await state.clear()

@dp.callback_query(F.data == "admin_change_price")
async def callback_change_price(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ دسترسی ندارید.", show_alert=True)
        return
    await callback.message.edit_text(
        "💰 لطفاً قیمت جدید هر گیگ را به <b>هزار تومان</b> وارد کنید:\n\n"
        "مثال: برای قیمت ۶ هزار تومان به ازای هر گیگ، عدد <code>6</code> را ارسال کنید."
    )
    await state.set_state("waiting_price")
    await callback.answer()

@dp.message(StateFilter("waiting_price"))
async def handle_price(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ دسترسی ندارید.")
        return
    try:
        price = float(message.text.strip())
        if price <= 0:
            raise ValueError("قیمت باید مثبت باشد")
        global PRICE_PER_GB
        PRICE_PER_GB = price
        os.environ["PRICE_PER_GB"] = str(price)
        asyncio.create_task(save_state())
        log_activity("settings", f"قیمت هر گیگ تغییر کرد: {price} هزار تومان", "ok")
        await message.answer(f"✅ قیمت هر گیگ به <b>{price} هزار تومان</b> تغییر یافت.\n"
                             f"محصولات جدید با قیمت جدید محاسبه می‌شوند.")
    except Exception as e:
        await message.answer(f"❌ خطا: {e}\nلطفاً یک عدد معتبر وارد کنید.")
    await state.clear()

@dp.callback_query(F.data == "admin_stats")
async def callback_admin_stats(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ دسترسی ندارید.", show_alert=True)
        return
    total_orders = len(ORDERS)
    pending_orders = len([o for o in ORDERS.values() if o["status"] == "pending"])
    confirmed_orders = len([o for o in ORDERS.values() if o["status"] == "confirmed"])
    text = (
        f"📊 آمار ربات:\n\n"
        f"📦 کل سفارشات: {total_orders}\n"
        f"⏳ در انتظار تأیید: {pending_orders}\n"
        f"✅ تأیید شده: {confirmed_orders}\n"
        f"👥 تعداد ادمین‌ها: {len(ADMIN_IDS)}\n"
        f"📌 محصولات: {len(PRODUCTS)}\n"
        f"💰 قیمت هر گیگ: {PRICE_PER_GB} هزار تومان"
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 بازگشت", callback_data="admin_panel")]
    ])
    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()

@dp.callback_query(F.data.startswith("admin_orders:"))
async def callback_admin_orders(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ دسترسی ندارید.", show_alert=True)
        return
    page = int(callback.data.split(":")[1]) if ":" in callback.data else 0
    pending_orders = [o for o in ORDERS.values() if o["status"] == "pending"]
    total = len(pending_orders)
    start = page * 5
    end = min(start + 5, total)
    builder = InlineKeyboardBuilder()
    for i in range(start, end):
        o = pending_orders[i]
        builder.button(
            text=f"#{o['order_id']} — کاربر {o['user_id']}",
            callback_data=f"admin_order_view:{o['order_id']}"
        )
    builder.adjust(1)
    if start > 0:
        builder.button(text="◀ قبلی", callback_data=f"admin_orders:{page-1}")
    if end < total:
        builder.button(text="بعدی ▶", callback_data=f"admin_orders:{page+1}")
    builder.row(InlineKeyboardButton(text="🔙 بازگشت", callback_data="admin_panel"))
    await callback.message.edit_text("📋 سفارشات در انتظار تایید:", reply_markup=builder.as_markup())
    await callback.answer()

@dp.callback_query(F.data.startswith("admin_order_view:"))
async def callback_admin_order_view(callback: CallbackQuery):
    order_id = callback.data.split(":")[1]
    order = ORDERS.get(order_id)
    if not order:
        await callback.answer("سفارش یافت نشد.", show_alert=True)
        return
    product = PRODUCTS.get(order['product_id'])
    text = (
        f"🧾 سفارش #{order_id}\n"
        f"👤 کاربر: {order['user_id']}\n"
        f"📦 محصول: {product['name'] if product else 'نامشخص'}\n"
        f"📊 حجم: {order['volume']} GB\n"
        f"⏳ مدت: {order['duration']} روز\n"
        f"🚀 سرعت: {order['speed']} Mbps\n"
        f"💰 قیمت: {order['price']:,} تومان\n"
        f"🕒 زمان: {order['created_at']}\n"
        f"📌 وضعیت: {order['status']}"
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ تایید", callback_data=f"approve:{order_id}"),
         InlineKeyboardButton(text="❌ رد", callback_data=f"reject:{order_id}")],
        [InlineKeyboardButton(text="🔙 بازگشت", callback_data="admin_orders:0")]
    ])
    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()

# ── Start/Stop ──────────────────────────────────────────────────────────────
_poll_task: Optional[asyncio.Task] = None

async def start_bot():
    global _poll_task
    if not BOT_TOKEN:
        return
    logger.info("🤖 راه‌اندازی ربات تلگرام (Long Polling)...")
    _poll_task = asyncio.create_task(dp.start_polling(bot))

async def stop_bot():
    if _poll_task:
        _poll_task.cancel()
        try:
            await _poll_task
        except:
            pass
        await bot.session.close()
