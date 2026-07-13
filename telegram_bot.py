# telegram_bot.py
# ربات فروش Tk-Ui با Aiogram — Long Polling
# شامل: ریمیت، تست رایگان، سطح‌بندی، بازخورد، تمدید اشتراک، سیستم رد با دلیل

import asyncio
import os
import secrets
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import quote

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest

from main import (
    LINKS, LINKS_LOCK, SUBS, SUBS_LOCK,
    PRODUCTS, PRODUCTS_LOCK, ORDERS, ORDERS_LOCK,
    CARD_NUMBER, CARD_OWNER_NAME, PRICE_PER_GB, ADMIN_IDS, OWNER_ID,
    TEST_USERS, USER_CODES, REYMIT_LINKS, FEEDBACKS, TUTORIAL_CHANNEL, ADMIN_GROUP_ID,
    make_link, create_sub_group, set_link_sub,
    get_host, generate_random_password, generate_user_code, calculate_user_level,
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

# ── وضعیت‌های FSM ──────────────────────────────────────────────────────────
class BuyStates(StatesGroup):
    waiting_receipt = State()
    waiting_volume = State()
    waiting_renew_receipt = State()

class FeedbackStates(StatesGroup):
    waiting_feedback = State()

class AdminStates(StatesGroup):
    waiting_reject_reason = State()
    waiting_reject_reason_other = State()

# ── توابع کمکی ──────────────────────────────────────────────────────────────
def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

async def check_channel_membership(user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id=REQUIRED_CHANNEL, user_id=user_id)
        return member.status in ("member", "administrator", "creator")
    except Exception:
        return False

# ── دکمه‌های شیشه‌ای با یونیکد و رنگ‌بندی ─────────────────────────────────

def get_main_menu_keyboard(is_admin_user: bool = False) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    
    # خرید اشتراک جدید (سبز - با رنگ استایل)
    builder.row(
        InlineKeyboardButton(
            text="🛍️  خرید اشتراک جدید",
            callback_data="buy"
        )
    )
    
    # اشتراک‌های من/تمدید (آبی)
    builder.row(
        InlineKeyboardButton(
            text="📂  اشتراک‌های من",
            callback_data="my_subscriptions"
        )
    )
    
    # دکمه‌های بی‌رنگ با آیکون یونیکد
    builder.row(
        InlineKeyboardButton(
            text="💡  آموزش‌ها",
            callback_data="tutorials"
        ),
        InlineKeyboardButton(
            text="👤  حساب کاربری",
            callback_data="my_account"
        )
    )
    
    builder.row(
        InlineKeyboardButton(
            text="🧪  تست رایگان",
            callback_data="test_service"
        ),
        InlineKeyboardButton(
            text="📞  پشتیبانی",
            callback_data="support"
        )
    )
    
    # دکمه‌های قرمز (بازخورد)
    builder.row(
        InlineKeyboardButton(
            text="✍️  ارسال بازخورد",
            callback_data="send_feedback"
        )
    )
    
    builder.row(
        InlineKeyboardButton(
            text="💬  بازخورد کاربران",
            callback_data="view_feedbacks"
        )
    )
    
    if is_admin_user:
        builder.row(
            InlineKeyboardButton(
                text="⚙️  پنل ادمین",
                callback_data="admin_panel"
            )
        )
    
    return builder.as_markup()

def get_subscription_menu_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    
    builder.row(
        InlineKeyboardButton(
            text="📥  دریافت لینک اشتراک‌ها",
            callback_data="get_sub_links"
        )
    )
    
    builder.row(
        InlineKeyboardButton(
            text="🔄  تمدید اشتراک",
            callback_data="renew_subscription"
        )
    )
    
    builder.row(
        InlineKeyboardButton(
            text="🔙  بازگشت به منوی اصلی",
            callback_data="main_menu"
        )
    )
    
    return builder.as_markup()

def get_renew_subscription_keyboard(user_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    user_orders = [o for o in ORDERS.values() if o["user_id"] == user_id and o["status"] == "confirmed"]
    
    if not user_orders:
        builder.row(
            InlineKeyboardButton(
                text="❌  شما اشتراک فعالی ندارید",
                callback_data="no_subscription"
            )
        )
    else:
        for order in user_orders:
            product = PRODUCTS.get(order["product_id"])
            if product:
                builder.row(
                    InlineKeyboardButton(
                        text=f"📦  {product['name']} — {product['volume_gb']}GB",
                        callback_data=f"renew:{order['order_id']}"
                    )
                )
    
    builder.row(
        InlineKeyboardButton(
            text="🔙  بازگشت",
            callback_data="my_subscriptions"
        )
    )
    
    return builder.as_markup()

def get_support_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    
    builder.row(
        InlineKeyboardButton(
            text="📞  ارتباط با پشتیبان",
            url="https://t.me/ItzJustEren"
        )
    )
    
    builder.row(
        InlineKeyboardButton(
            text="🔙  بازگشت به منوی اصلی",
            callback_data="main_menu"
        )
    )
    
    return builder.as_markup()

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

def get_reject_reason_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🖼  رسید فیک", callback_data="reject_reason:fake"),
        InlineKeyboardButton(text="⏰  دیرتر از زمان معین", callback_data="reject_reason:late")
    )
    builder.row(
        InlineKeyboardButton(text="📝  دلیل دیگر (دستی)", callback_data="reject_reason:other")
    )
    return builder.as_markup()

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
    keyboard = get_main_menu_keyboard(is_admin(message.from_user.id))
    await message.answer(
        "👋 **به ربات فروش Tk-Ui خوش آمدید!**\n\n"
        "✨ فروش کانفیگ‌های اختصاصی با بهترین کیفیت\n\n"
        "📌 لطفاً یکی از گزینه‌های زیر را انتخاب کنید:",
        reply_markup=keyboard,
        parse_mode="Markdown"
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
    user_id = callback.from_user.id
    if await check_channel_membership(user_id):
        await callback.answer("✅ عضویت تأیید شد!", show_alert=True)
        await show_main_menu(callback.message)
        await callback.message.delete()
    else:
        await callback.answer("❌ هنوز عضو نشده‌اید.", show_alert=True)

# ── خرید ──────────────────────────────────────────────────────────────────────
@dp.callback_query(F.data == "buy")
async def callback_buy(callback: CallbackQuery):
    if not PRODUCTS:
        await callback.answer("❌ هیچ محصولی موجود نیست.", show_alert=True)
        return
    await callback.answer()
    await callback.message.edit_text(
        "🛒 **لیست محصولات:**\n\nلطفاً یکی را انتخاب کنید:",
        reply_markup=get_products_keyboard(),
        parse_mode="Markdown"
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
        f"📦 **{product['name']}**\n"
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
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data.startswith("confirm_buy:"))
async def callback_confirm_buy(callback: CallbackQuery, state: FSMContext):
    product_id = callback.data.split(":")[1]
    product = PRODUCTS.get(product_id)
    if not product:
        await callback.answer("❌ محصول یافت نشد.", show_alert=True)
        return

    # تولید کد کاربری
    user_code = generate_user_code()
    USER_CODES[callback.from_user.id] = {"code": user_code, "created_at": datetime.now()}

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
        "user_code": user_code,
    }
    async with ORDERS_LOCK:
        ORDERS[order_id] = order
    asyncio.create_task(save_state())

    reymit_link = REYMIT_LINKS[0] if REYMIT_LINKS else "https://reymit.ir/itzjusteren"
    payment_text = (
        f"💳 **پرداخت از طریق درگاه امن ریمیت**\n\n"
        f"🔗 لینک پرداخت:\n"
        f"`{reymit_link}`\n\n"
        f"🔑 **کد کاربری شما:**\n"
        f"`{user_code}`\n\n"
        f"⚠️ **توجه بسیار مهم:**\n"
        f"۱. هنگام پرداخت، نام خود را حتماً **کد کاربری** خود وارد کنید.\n"
        f"۲. در صورت مغایرت، Tk-Ui مسئولیتی ندارد.\n"
        f"۳. حتماً در توضیحات پرداخت، این متن را بنویسید:\n"
        f"_خرید کانفیگ با رضایت کامل از Tk-Ui_\n\n"
        f"📌 پس از پرداخت، تصویر رسید را به ربات ارسال کنید.\n"
        f"⏳ مهلت پرداخت: **۱ ساعت**\n\n"
        f"با تشکر از اعتماد شما ❤️\n"
        f"تیم Tk-Ui"
    )

    await callback.message.edit_text(payment_text, parse_mode="Markdown")
    await state.set_state(BuyStates.waiting_receipt)
    await state.update_data(order_id=order_id, order_time=datetime.now(), user_code=user_code, is_renew=False)
    await callback.answer()

# ── دریافت رسید ──────────────────────────────────────────────────────────────
@dp.message(BuyStates.waiting_receipt, F.photo)
async def handle_receipt(message: types.Message, state: FSMContext):
    data = await state.get_data()
    order_id = data.get("order_id")
    order_time = data.get("order_time")
    user_code = data.get("user_code")
    is_renew = data.get("is_renew", False)
    order = ORDERS.get(order_id)
    
    if not order:
        await message.answer("❌ سفارش یافت نشد. لطفاً دوباره از منوی خرید اقدام کنید.")
        await state.clear()
        return

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
        await send_order_to_admins(order_id, order['user_id'], product, user_code, message, is_renew)

    await message.answer(
        "✅ رسید شما دریافت شد و در انتظار تأیید ادمین است.\n"
        "به محض تأیید، لینک‌های دانلود برای شما ارسال خواهد شد."
    )
    await state.clear()

@dp.message(BuyStates.waiting_receipt)
async def handle_invalid_receipt(message: types.Message):
    await message.answer("❌ لطفاً تصویر رسید را به‌صورت عکس ارسال کنید.")

# ── ارسال سفارش به ادمین ────────────────────────────────────────────────────
async def send_order_to_admins(order_id: str, user_id: int, product: dict, user_code: str, receipt_msg: types.Message, is_renew: bool = False):
    order = ORDERS.get(order_id)
    if not order:
        return
    
    user = await bot.get_chat(user_id)
    username = user.username or "ندارد"
    full_name = user.full_name or "کاربر"

    text = (
        f"🆕 **{('تمدید' if is_renew else 'سفارش جدید')} #{order_id}**\n\n"
        f"👤 **کاربر:** {full_name} (@{username})\n"
        f"🆔 **آیدی عددی:** {user_id}\n"
        f"🔑 **کد کاربری:** `{user_code}`\n\n"
        f"📦 **محصول:** {product['name']}\n"
        f"📊 **حجم:** {product['volume_gb']} GB\n"
        f"⏳ **مدت:** {product['duration_days']} روز\n"
        f"🚀 **سرعت:** {product['speed_mbps']} Mbps\n"
        f"💰 **قیمت:** {product['price']:,} تومان\n"
        f"🕒 **زمان سفارش:** {order['created_at']}\n\n"
        f"🖼 **رسید:**"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ تایید", callback_data=f"approve:{order_id}"),
         InlineKeyboardButton(text="❌ رد", callback_data=f"reject:{order_id}")]
    ])

    if ADMIN_GROUP_ID:
        try:
            await bot.send_photo(
                chat_id=ADMIN_GROUP_ID,
                photo=receipt_msg.photo[-1].file_id,
                caption=text,
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
            return
        except Exception as e:
            logger.warning(f"ارسال به گروه ناموفق: {e}")
    
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_photo(
                chat_id=admin_id,
                photo=receipt_msg.photo[-1].file_id,
                caption=text,
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
        except Exception:
            pass

# ── تایید سفارش ──────────────────────────────────────────────────────────────
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

    # بررسی سطح کاربری
    level = calculate_user_level(user_id)
    level_bonus = ""
    if level >= 10:
        # پاداش سطح ۱۰: ۵ گیگ رایگان یک هفته‌ای
        bonus_uuid, bonus_link = await make_link(
            label=f"پاداش سطح ۱۰ - {product['name']}",
            limit_bytes=5 * 1024 * 1024 * 1024,
            expires_at=(datetime.now() + timedelta(days=7)).isoformat(),
            note="پاداش سطح ۱۰",
            protocol=DEFAULT_PROTOCOL,
            fingerprint=DEFAULT_FINGERPRINT,
            alpn="",
            port=DEFAULT_PORT,
            ip_limit=0,
            speed_limit_bytes=0,
        )
        bonus_sub_password = generate_random_password(8)
        bonus_sub_id, bonus_sub = await create_sub_group(
            name=f"پاداش سطح ۱۰ - {product['name']}",
            desc="پاداش ۵ گیگ یک هفته‌ای",
            password=bonus_sub_password
        )
        await set_link_sub(bonus_uuid, bonus_sub_id)
        bonus_vless = vless_link_for_link(bonus_link, bonus_uuid, host)
        bonus_url = f"https://{host}/p/{bonus_sub['uuid_key']}"
        level_bonus = (
            f"\n\n🎁 **پاداش سطح ۱۰ شما!**\n"
            f"📦 ۵ گیگ کانفیگ رایگان به مدت ۱ هفته\n"
            f"🔗 لینک ساب پاداش: `{bonus_url}`\n"
            f"🔑 پسورد: `{bonus_sub_password}`\n"
            f"🔗 لینک VLESS پاداش:\n`{bonus_vless}`"
        )

    success_msg = (
        f"🎉 تبریک! خرید شما با موفقیت انجام شد.\n"
        f"امیدواریم از خریدتان راضی باشید.\n"
        f"از طرف Tk-Ui ❤️\n\n"
        f"📌 **لینک ساب (با پسورد):**\n"
        f"`{sub_url}`\n\n"
        f"🔑 **پسورد ساب:**\n"
        f"`{sub_password}`\n\n"
        f"📊 **مشخصات کانفیگ:**\n"
        f"حجم: {product['volume_gb']} GB\n"
        f"مدت: {product['duration_days']} روز\n"
        f"سرعت: {product['speed_mbps']} Mbps {'(نامحدود)' if product['speed_mbps'] == 0 else ''}\n\n"
        f"🔗 **لینک VLESS:**\n"
        f"`{vless_link}`"
        f"{level_bonus}"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📥 دریافت لینک ساب", url=sub_url)],
        [InlineKeyboardButton(text="📥 دریافت کانفیگ VLESS", callback_data=f"get_vless:{uuid}")]
    ])

    await bot.send_message(
        chat_id=user_id,
        text=success_msg,
        parse_mode="Markdown",
        reply_markup=keyboard
    )

    await callback.message.edit_text(f"✅ سفارش #{order_id} تأیید و کانفیگ ارسال شد.")
    await callback.answer()

# ── رد سفارش با دلیل ────────────────────────────────────────────────────────
@dp.callback_query(F.data.startswith("reject:"))
async def callback_reject_order(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ دسترسی ندارید.", show_alert=True)
        return
    
    order_id = callback.data.split(":")[1]
    order = ORDERS.get(order_id)
    if not order or order["status"] != "pending":
        await callback.answer("سفارش یافت نشد.", show_alert=True)
        return
    
    await state.update_data(reject_order_id=order_id)
    await state.set_state(AdminStates.waiting_reject_reason)
    
    await callback.message.edit_text(
        f"❌ لطفاً دلیل رد سفارش #{order_id} را انتخاب کنید:",
        reply_markup=get_reject_reason_keyboard()
    )
    await callback.answer()

@dp.callback_query(AdminStates.waiting_reject_reason, F.data.startswith("reject_reason:"))
async def callback_reject_reason(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ دسترسی ندارید.", show_alert=True)
        return
    
    reason_code = callback.data.split(":")[1]
    data = await state.get_data()
    order_id = data.get("reject_order_id")
    order = ORDERS.get(order_id)
    
    if not order:
        await callback.answer("❌ سفارش یافت نشد.", show_alert=True)
        await state.clear()
        return
    
    if reason_code == "other":
        await callback.message.edit_text(
            "✏️ لطفاً دلیل رد سفارش را به‌صورت یک پیام متنی ارسال کنید:"
        )
        await state.set_state(AdminStates.waiting_reject_reason_other)
        await callback.answer()
        return
    
    # دلایل از پیش تعیین شده
    reason_texts = {
        "fake": "رسید ارسالی شما نامعتبر یا فیک تشخیص داده شده است.",
        "late": "رسید شما دیرتر از زمان معین (۱ ساعت) ارسال شده است."
    }
    reason = reason_texts.get(reason_code, "به دلیل نامشخص")
    
    await process_reject_order(order_id, reason, callback.message)
    await state.clear()
    await callback.answer()

@dp.message(AdminStates.waiting_reject_reason_other)
async def handle_reject_reason_other(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ دسترسی ندارید.")
        return
    
    reason = message.text.strip()
    if not reason:
        await message.answer("❌ لطفاً یک متن معتبر ارسال کنید.")
        return
    
    data = await state.get_data()
    order_id = data.get("reject_order_id")
    
    if not order_id:
        await message.answer("❌ سفارش یافت نشد.")
        await state.clear()
        return
    
    await process_reject_order(order_id, reason, message)
    await state.clear()

async def process_reject_order(order_id: str, reason: str, msg: types.Message):
    order = ORDERS.get(order_id)
    if not order:
        await msg.answer("❌ سفارش یافت نشد.")
        return
    
    # به‌روزرسانی وضعیت
    async with ORDERS_LOCK:
        ORDERS[order_id]["status"] = "rejected"
        ORDERS[order_id]["reject_reason"] = reason
    asyncio.create_task(save_state())
    
    # ارسال پیام به کاربر
    user_id = order["user_id"]
    product = PRODUCTS.get(order["product_id"])
    
    try:
        await bot.send_message(
            chat_id=user_id,
            text=(
                f"❌ **درخواست خرید شما رد شد**\n\n"
                f"🆔 سفارش: #{order_id}\n"
                f"📦 محصول: {product['name'] if product else 'نامشخص'}\n"
                f"💰 مبلغ: {order['price']:,} تومان\n\n"
                f"📌 **دلیل رد:**\n{reason}\n\n"
                f"💡 در صورت اعتراض، لطفاً با پشتیبان تماس بگیرید:\n"
                f"📞 @ItzJustEren"
            ),
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.warning(f"ارسال پیام رد به کاربر ناموفق: {e}")
    
    await msg.edit_text(
        f"✅ سفارش #{order_id} با موفقیت رد شد.\n"
        f"📌 دلیل: {reason}\n"
        f"👤 کاربر مطلع شد."
    )

# ── دریافت مجدد لینک VLESS ──────────────────────────────────────────────────
@dp.callback_query(F.data.startswith("get_vless:"))
async def callback_get_vless(callback: CallbackQuery):
    uuid = callback.data.split(":")[1]
    link = LINKS.get(uuid)
    if not link or not is_link_allowed(link):
        await callback.answer("❌ کانفیگ یافت نشد یا غیرفعال است.", show_alert=True)
        return
    host = get_host()
    vless = vless_link_for_link(link, uuid, host)
    await callback.message.answer(f"🔗 کانفیگ VLESS:\n`{vless}`", parse_mode="Markdown")
    await callback.answer()

# ── اشتراک‌های من ──────────────────────────────────────────────────────────
@dp.callback_query(F.data == "my_subscriptions")
async def callback_my_subscriptions(callback: CallbackQuery):
    keyboard = get_subscription_menu_keyboard()
    await callback.message.edit_text(
        "📂 **مدیریت اشتراک‌های شما**\n\n"
        "لطفاً یکی از گزینه‌های زیر را انتخاب کنید:",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )
    await callback.answer()

@dp.callback_query(F.data == "get_sub_links")
async def callback_get_sub_links(callback: CallbackQuery):
    user_id = callback.from_user.id
    user_orders = [o for o in ORDERS.values() if o["user_id"] == user_id and o["status"] == "confirmed"]
    
    if not user_orders:
        await callback.message.edit_text(
            "❌ **شما هیچ اشتراک فعالی ندارید.**\n\n"
            "برای خرید اشتراک، از دکمه **🛍️ خرید اشتراک جدید** استفاده کنید.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 بازگشت", callback_data="my_subscriptions")]
            ]),
            parse_mode="Markdown"
        )
        await callback.answer()
        return
    
    text = "🔗 **لینک‌های اشتراک شما:**\n\n"
    for order in user_orders:
        sub_id = order.get("sub_id")
        if sub_id and sub_id in SUBS:
            sub = SUBS[sub_id]
            host = get_host()
            sub_url = f"https://{host}/p/{sub['uuid_key']}"
            product = PRODUCTS.get(order["product_id"])
            text += f"📦 **{product['name'] if product else 'اشتراک'}**\n"
            text += f"🔑 `{sub_url}`\n"
            text += f"📊 حجم: {order['volume']}GB | ⏳ مدت: {order['duration']} روز\n\n"
    
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 بازگشت", callback_data="my_subscriptions")]
        ]),
        parse_mode="Markdown"
    )
    await callback.answer()

@dp.callback_query(F.data == "renew_subscription")
async def callback_renew_subscription(callback: CallbackQuery):
    user_id = callback.from_user.id
    keyboard = get_renew_subscription_keyboard(user_id)
    await callback.message.edit_text(
        "🔄 **تمدید اشتراک**\n\n"
        "لطفاً اشتراک مورد نظر برای تمدید را انتخاب کنید:",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("renew:"))
async def callback_renew_confirm(callback: CallbackQuery, state: FSMContext):
    order_id = callback.data.split(":")[1]
    order = ORDERS.get(order_id)
    if not order:
        await callback.answer("❌ اشتراک یافت نشد.", show_alert=True)
        return
    
    product = PRODUCTS.get(order["product_id"])
    if not product:
        await callback.answer("❌ محصول یافت نشد.", show_alert=True)
        return
    
    user_code = generate_user_code()
    USER_CODES[callback.from_user.id] = {"code": user_code, "created_at": datetime.now()}
    
    new_order_id = secrets.token_hex(8).upper()
    new_order = {
        "order_id": new_order_id,
        "user_id": callback.from_user.id,
        "product_id": order["product_id"],
        "volume": product['volume_gb'],
        "duration": product['duration_days'],
        "speed": product['speed_mbps'],
        "price": product['price'],
        "status": "pending",
        "created_at": datetime.now().isoformat(),
        "config_uuid": None,
        "sub_id": None,
        "user_code": user_code,
        "renew_of": order_id,
    }
    async with ORDERS_LOCK:
        ORDERS[new_order_id] = new_order
    asyncio.create_task(save_state())

    reymit_link = REYMIT_LINKS[0] if REYMIT_LINKS else "https://reymit.ir/itzjusteren"
    text = (
        f"🔄 **تمدید اشتراک**\n\n"
        f"📦 **محصول:** {product['name']}\n"
        f"📊 **حجم:** {product['volume_gb']} GB\n"
        f"⏳ **مدت:** {product['duration_days']} روز\n"
        f"💰 **قیمت:** {product['price']:,} تومان\n\n"
        f"🔑 **کد کاربری شما:**\n"
        f"`{user_code}`\n\n"
        f"💳 **پرداخت از طریق ریمیت:**\n"
        f"`{reymit_link}`\n\n"
        f"⚠️ هنگام پرداخت، نام خود را **کد کاربری** وارد کنید.\n"
        f"پس از پرداخت، رسید را برای ربات ارسال کنید."
    )
    
    await callback.message.edit_text(text, parse_mode="Markdown")
    await state.set_state(BuyStates.waiting_receipt)
    await state.update_data(order_id=new_order_id, order_time=datetime.now(), user_code=user_code, is_renew=True)
    await callback.answer()

# ── آموزش‌ها ──────────────────────────────────────────────────────────────
@dp.callback_query(F.data == "tutorials")
async def callback_tutorials(callback: CallbackQuery):
    channel = TUTORIAL_CHANNEL or "@TaaKaaOrg"
    await callback.message.edit_text(
        f"💡 **آموزش‌های Tk-Ui**\n\n"
        f"📌 برای مشاهده آموزش‌ها، به کانال زیر مراجعه کنید:\n"
        f"👉 {channel}\n\n"
        f"📹 آموزش تصویری استفاده از ربات:\n"
        f"[لینک ویدیو]",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 بازگشت", callback_data="main_menu")]
        ]),
        parse_mode="Markdown"
    )
    await callback.answer()

# ── حساب کاربری ────────────────────────────────────────────────────────────
@dp.callback_query(F.data == "my_account")
async def callback_my_account(callback: CallbackQuery):
    user_id = callback.from_user.id
    user_orders = [o for o in ORDERS.values() if o["user_id"] == user_id]
    total_purchases = len([o for o in user_orders if o["status"] == "confirmed"])
    level = calculate_user_level(user_id)
    
    text = (
        f"👤 **حساب کاربری شما**\n\n"
        f"🆔 **آیدی:** {user_id}\n"
        f"📊 **تعداد خرید:** {total_purchases}\n"
        f"⭐ **سطح کاربری:** {level}\n\n"
        f"🔰 **مزایای سطح {level}:**\n"
        f"{'🎁 دریافت ۵ گیگ کانفیگ رایگان یک هفته‌ای!' if level >= 10 else 'به خرید ادامه دهید تا به سطح ۱۰ برسید!'}"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 بازگشت", callback_data="main_menu")]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")
    await callback.answer()

# ── تست رایگان ────────────────────────────────────────────────────────────
@dp.callback_query(F.data == "test_service")
async def callback_test_service(callback: CallbackQuery):
    user_id = callback.from_user.id
    now = datetime.now()
    
    test_data = TEST_USERS.get(user_id)
    if test_data and test_data.get("last_test"):
        days_passed = (now - test_data["last_test"]).days
        if days_passed < 7:
            remaining = 7 - days_passed
            await callback.answer(
                f"⛔ شما قبلاً کانفیگ تست خود را دریافت کرده‌اید.\n"
                f"لطفاً {remaining} روز دیگر تلاش کنید.",
                show_alert=True
            )
            return
    
    volume_bytes = 50 * 1024 * 1024
    expires_at = (now + timedelta(days=1)).isoformat()
    
    uuid, link = await make_link(
        label=f"تست - {callback.from_user.full_name}",
        limit_bytes=volume_bytes,
        expires_at=expires_at,
        note="کانفیگ تست رایگان",
        protocol=DEFAULT_PROTOCOL,
        fingerprint=DEFAULT_FINGERPRINT,
        alpn="",
        port=DEFAULT_PORT,
        ip_limit=0,
        speed_limit_bytes=0,
    )
    
    TEST_USERS[user_id] = {"last_test": now, "used": True}
    asyncio.create_task(save_state())
    
    host = get_host()
    vless_link = vless_link_for_link(link, uuid, host)
    sub_url = f"https://{host}/sub/{uuid}"
    qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={quote(vless_link)}"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📱 دریافت QR Code", callback_data=f"show_qr:{uuid}")],
        [InlineKeyboardButton(text="🔗 دریافت کانفیگ VLESS", callback_data=f"get_vless:{uuid}")],
        [InlineKeyboardButton(text="📥 دریافت لینک ساب", url=sub_url)]
    ])
    
    await callback.message.edit_text(
        f"🧪 **کانفیگ تست شما آماده شد!**\n\n"
        f"👤 کاربر: {callback.from_user.full_name} (ID: {user_id})\n"
        f"⏳ مدت زمان: ۱ روز\n"
        f"📊 حجم تست: ۵۰ مگابایت\n"
        f"🔰 سرویس: تست Tk-Ui\n\n"
        f"📌 این کانفیگ به‌صورت رایگان در اختیار شما قرار گرفته.\n"
        f"امیدواریم از خدمات ما راضی باشید! ❤️\n\n"
        f"⚠️ فقط هفته‌ای یک بار می‌توانید تست دریافت کنید.",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("show_qr:"))
async def callback_show_qr(callback: CallbackQuery):
    uuid = callback.data.split(":")[1]
    link = LINKS.get(uuid)
    if not link or not is_link_allowed(link):
        await callback.answer("❌ کانفیگ یافت نشد.", show_alert=True)
        return
    host = get_host()
    vless = vless_link_for_link(link, uuid, host)
    qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={quote(vless)}"
    
    await callback.message.answer_photo(
        photo=qr_url,
        caption=f"📱 **QR Code کانفیگ**\n\n🔗 لینک VLESS:\n`{vless}`",
        parse_mode="Markdown"
    )
    await callback.answer()

# ── پشتیبانی ──────────────────────────────────────────────────────────────
@dp.callback_query(F.data == "support")
async def callback_support(callback: CallbackQuery):
    keyboard = get_support_keyboard()
    await callback.message.edit_text(
        "📞 **پشتیبانی Tk-Ui**\n\n"
        "برای ارتباط با پشتیبان، روی دکمه زیر کلیک کنید:",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )
    await callback.answer()

# ── ارسال بازخورد ─────────────────────────────────────────────────────────
@dp.callback_query(F.data == "send_feedback")
async def callback_send_feedback(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "✍️ **ارسال بازخورد**\n\n"
        "لطفاً متن بازخورد خود را ارسال کنید.\n"
        "پس از تأیید توسط ادمین، در بخش بازخورد کاربران نمایش داده می‌شود.",
        parse_mode="Markdown"
    )
    await state.set_state(FeedbackStates.waiting_feedback)
    await callback.answer()

@dp.message(StateFilter(FeedbackStates.waiting_feedback))
async def handle_feedback(message: types.Message, state: FSMContext):
    feedback_text = message.text
    user_id = message.from_user.id
    username = message.from_user.username or "کاربر"
    
    feedback_data = {
        "id": secrets.token_hex(8),
        "user_id": user_id,
        "username": username,
        "text": feedback_text,
        "created_at": datetime.now().isoformat(),
        "approved": False
    }
    FEEDBACKS.append(feedback_data)
    asyncio.create_task(save_state())
    
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                chat_id=admin_id,
                text=f"📝 **بازخورد جدید**\n\n"
                     f"👤 کاربر: {message.from_user.full_name} (@{username}) [ID: {user_id}]\n"
                     f"📝 متن:\n{feedback_text}",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="✅ تایید", callback_data=f"approve_fb:{feedback_data['id']}"),
                     InlineKeyboardButton(text="❌ رد", callback_data=f"reject_fb:{feedback_data['id']}")]
                ]),
                parse_mode="Markdown"
            )
        except Exception:
            pass
    
    await message.answer(
        "✅ بازخورد شما با موفقیت ثبت شد.\n"
        "پس از تأیید توسط ادمین، در بخش بازخورد کاربران نمایش داده می‌شود.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 منوی اصلی", callback_data="main_menu")]
        ])
    )
    await state.clear()

@dp.callback_query(F.data.startswith("approve_fb:"))
async def callback_approve_feedback(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ دسترسی ندارید.", show_alert=True)
        return
    feedback_id = callback.data.split(":")[1]
    for fb in FEEDBACKS:
        if fb.get("id") == feedback_id:
            fb["approved"] = True
            asyncio.create_task(save_state())
            await callback.message.edit_text("✅ بازخورد تایید شد.")
            await callback.answer()
            return
    await callback.answer("❌ بازخورد یافت نشد.", show_alert=True)

@dp.callback_query(F.data.startswith("reject_fb:"))
async def callback_reject_feedback(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ دسترسی ندارید.", show_alert=True)
        return
    feedback_id = callback.data.split(":")[1]
    for i, fb in enumerate(FEEDBACKS):
        if fb.get("id") == feedback_id:
            FEEDBACKS.pop(i)
            asyncio.create_task(save_state())
            await callback.message.edit_text("❌ بازخورد رد شد.")
            await callback.answer()
            return
    await callback.answer("❌ بازخورد یافت نشد.", show_alert=True)

# ── بازخورد کاربران ──────────────────────────────────────────────────────
@dp.callback_query(F.data == "view_feedbacks")
async def callback_view_feedbacks(callback: CallbackQuery):
    approved = [fb for fb in FEEDBACKS if fb.get("approved", False)]
    if not approved:
        await callback.message.edit_text(
            "💬 **بازخورد کاربران**\n\n"
            "هنوز بازخوردی ثبت نشده است.\n"
            "اولین نفری باشید که بازخورد خود را ارسال می‌کند! ✍️",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 بازگشت", callback_data="main_menu")]
            ]),
            parse_mode="Markdown"
        )
        await callback.answer()
        return
    
    text = "💬 **بازخورد کاربران**\n\n"
    for fb in approved[-10:]:
        text += f"👤 {fb.get('username', 'کاربر')}:\n"
        text += f"📝 {fb.get('text')}\n"
        text += f"🕒 {fb.get('created_at')[:10]}\n\n"
    
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 بازگشت", callback_data="main_menu")]
        ]),
        parse_mode="Markdown"
    )
    await callback.answer()

# ── پنل ادمین ─────────────────────────────────────────────────────────────
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
    await callback.message.edit_text("⚙️ **پنل مدیریت ربات:**", reply_markup=keyboard, parse_mode="Markdown")
    await callback.answer()

# ── مدیریت محصولات ──────────────────────────────────────────────────────────
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
    await callback.message.edit_text("📦 **مدیریت محصولات:**", reply_markup=keyboard, parse_mode="Markdown")
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
        "⚠️ قیمت به‌صورت خودکار بر اساس قیمت هر گیگ محاسبه می‌شود.",
        parse_mode="Markdown"
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

# ── مدیریت ادمین‌ها ──────────────────────────────────────────────────────────
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
        f"👥 **لیست ادمین‌ها:**\n\n" + "\n".join(f"🆔 {uid}" for uid in ADMIN_IDS) +
        f"\n👑 اونر: {OWNER_ID}",
        reply_markup=keyboard,
        parse_mode="Markdown"
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

# ── تنظیمات ──────────────────────────────────────────────────────────────────
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
        f"⚙️ **تنظیمات**\n\n"
        f"💳 شماره کارت فعلی: `{CARD_NUMBER}`\n"
        f"👤 نام صاحب کارت: **{CARD_OWNER_NAME}**\n"
        f"💰 قیمت هر گیگ: **{PRICE_PER_GB} هزار تومان**",
        reply_markup=keyboard,
        parse_mode="Markdown"
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
        "مثال: `6037-9910-1234-5678 | علی محمدی`",
        parse_mode="Markdown"
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
        "💰 لطفاً قیمت جدید هر گیگ را به **هزار تومان** وارد کنید:\n\n"
        "مثال: برای قیمت ۶ هزار تومان به ازای هر گیگ، عدد `6` را ارسال کنید.",
        parse_mode="Markdown"
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
        await message.answer(f"✅ قیمت هر گیگ به **{price} هزار تومان** تغییر یافت.\n"
                             f"محصولات جدید با قیمت جدید محاسبه می‌شوند.")
    except Exception as e:
        await message.answer(f"❌ خطا: {e}\nلطفاً یک عدد معتبر وارد کنید.")
    await state.clear()

# ── آمار ──────────────────────────────────────────────────────────────────────
@dp.callback_query(F.data == "admin_stats")
async def callback_admin_stats(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ دسترسی ندارید.", show_alert=True)
        return
    total_orders = len(ORDERS)
    pending_orders = len([o for o in ORDERS.values() if o["status"] == "pending"])
    confirmed_orders = len([o for o in ORDERS.values() if o["status"] == "confirmed"])
    text = (
        f"📊 **آمار ربات:**\n\n"
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
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")
    await callback.answer()

# ── سفارشات ──────────────────────────────────────────────────────────────────
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
    await callback.message.edit_text("📋 **سفارشات در انتظار تایید:**", reply_markup=builder.as_markup(), parse_mode="Markdown")
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
        f"🧾 **سفارش #{order_id}**\n\n"
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
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")
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
