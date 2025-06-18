import asyncio
import aiohttp
import random
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, BotCommand
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from datetime import datetime, timedelta
import logging
import re
from collections import defaultdict, deque

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = "7644803053:AAEbbHrYb551HXkIehfyW4en0zFpS0ThSs8"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

MONOBANK_API_URL = "https://api.monobank.ua/bank/currency"
PRIVATBANK_API_URL = "https://api.privatbank.ua/p24api/pubinfo?exchange&json&coursid=11"
NBU_API_URL = "https://bank.gov.ua/NBUStatService/v1/statdirectory/exchange?json"
COINGECKO_API_URL = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum,tether&vs_currencies=uah"

USD_CODE = 840
EUR_CODE = 978
UAH_CODE = 980

user_preferences = {}
subscriptions = defaultdict(dict)
support_passwords = {}
rate_history = defaultdict(lambda: deque(maxlen=100))
target_rates = defaultdict(dict)
unique_users = set()

class CalcState(StatesGroup):
    waiting_for_bank = State()
    waiting_for_currency_and_operation = State()
    waiting_for_amount = State()

class PreferenceState(StatesGroup):
    waiting_for_bank = State()

class SupportState(StatesGroup):
    waiting_for_password = State()

class TargetRateState(StatesGroup):
    waiting_for_currency = State()
    waiting_for_operation = State()
    waiting_for_rate = State()

async def fetch_exchange_rates(url, retries=1, delay=5):
    async with aiohttp.ClientSession() as session:
        for attempt in range(retries + 1):
            try:
                async with session.get(url) as response:
                    if response.status == 200:
                        return await response.json()
                    else:
                        logging.error(f"Помилка запиту до API {url}: статус {response.status}")
                        if attempt < retries:
                            logging.info(f"Повторна спроба запиту до {url} через {delay} секунд...")
                            await asyncio.sleep(delay)
            except Exception as e:
                logging.error(f"Виникла помилка під час запиту до API {url}: {e}")
                if attempt < retries:
                    logging.info(f"Повторна спроба запиту до {url} через {delay} секунд...")
                    await asyncio.sleep(delay)
        return None

async def get_coingecko_rates():
    rates = await fetch_exchange_rates(COINGECKO_API_URL)
    if not rates:
        return None
    try:
        btc_rate = float(rates.get("bitcoin", {}).get("uah", 0))
        eth_rate = float(rates.get("ethereum", {}).get("uah", 0))
        usdt_rate = float(rates.get("tether", {}).get("uah", 0))
        if not all(isinstance(r, (int, float)) and r > 0 for r in [btc_rate, eth_rate, usdt_rate]):
            logging.error("Отримано некоректні курси від (В розробці)")
            return None
        rates = {
            "btc_buy": btc_rate,
            "btc_sell": btc_rate,
            "eth_buy": eth_rate,
            "eth_sell": eth_rate,
            "usdt_buy": usdt_rate,
            "usdt_sell": usdt_rate
        }
        await save_rate_history("(В розробці)", rates)
        return rates
    except (ValueError, TypeError) as e:
        logging.error(f"Некоректний формат курсів від (В розробці): {e}")
        return None

async def get_monobank_rates():
    rates = await fetch_exchange_rates(MONOBANK_API_URL)
    if not rates:
        return None
    usd_buy, usd_sell, eur_buy, eur_sell = None, None, None, None
    for rate in rates:
        if rate["currencyCodeA"] == USD_CODE and rate["currencyCodeB"] == UAH_CODE:
            usd_buy = rate.get("rateBuy")
            usd_sell = rate.get("rateSell")
        if rate["currencyCodeA"] == EUR_CODE and rate["currencyCodeB"] == UAH_CODE:
            eur_buy = rate.get("rateBuy")
            eur_sell = rate.get("rateSell")
    if not all(isinstance(r, (int, float)) and r > 0 for r in [usd_buy, usd_sell, eur_buy, eur_sell] if r is not None):
        logging.error("Отримано некоректні курси від Monobank")
        return None
    rates = {"usd_buy": usd_buy, "usd_sell": usd_sell, "eur_buy": eur_buy, "eur_sell": eur_sell}
    await save_rate_history("Monobank", rates)
    return rates

async def get_privatbank_rates():
    rates = await fetch_exchange_rates(PRIVATBANK_API_URL)
    if not rates:
        return None
    usd_buy, usd_sell, eur_buy, eur_sell = None, None, None, None
    for rate in rates:
        if rate.get("ccy") == "USD" and rate.get("base_ccy") == "UAH":
            try:
                usd_buy = float(rate.get("buy", 0))
                usd_sell = float(rate.get("sale", 0))
            except (ValueError, TypeError):
                logging.error("Некоректний формат курсу USD від Приват24")
                return None
        if rate.get("ccy") == "EUR" and rate.get("base_ccy") == "UAH":
            try:
                eur_buy = float(rate.get("buy", 0))
                eur_sell = float(rate.get("sale", 0))
            except (ValueError, TypeError):
                logging.error("Некоректний формат курсу EUR від Приват24")
                return None
    if not all(isinstance(r, (int, float)) and r > 0 for r in [usd_buy, usd_sell, eur_buy, eur_sell] if r is not None):
        logging.error("Отримано некоректні курси від Приват24")
        return None
    rates = {"usd_buy": usd_buy, "usd_sell": usd_sell, "eur_buy": eur_buy, "eur_sell": eur_sell}
    await save_rate_history("Приват24", rates)
    return rates

async def get_nbu_rates():
    rates = await fetch_exchange_rates(NBU_API_URL)
    if not rates:
        return None
    usd_rate, eur_rate = None, None
    for rate in rates:
        if rate.get("cc") == "USD":
            try:
                usd_rate = float(rate.get("rate", 0))
            except (ValueError, TypeError):
                logging.error("Некоректний формат курсу USD від НБУ")
                return None
        if rate.get("cc") == "EUR":
            try:
                eur_rate = float(rate.get("rate", 0))
            except (ValueError, TypeError):
                logging.error("Некоректний формат курсу EUR від НБУ")
                return None
    if not all(isinstance(r, (int, float)) and r > 0 for r in [usd_rate, eur_rate] if r is not None):
        logging.error("Отримано некоректні курси від НБУ")
        return None
    rates = {"usd_buy": usd_rate, "usd_sell": usd_rate, "eur_buy": eur_rate, "eur_sell": eur_rate}
    await save_rate_history("НБУ", rates)
    return rates

async def save_rate_history(bank, rates):
    if rates:
        rate_history[bank].append({
            "timestamp": datetime.now(),
            "rates": rates
        })

async def get_rate_history(bank, period_hours=24):
    cutoff_time = datetime.now() - timedelta(hours=period_hours)
    history = [entry for entry in rate_history[bank] if entry["timestamp"] >= cutoff_time]
    return history

async def format_currency_message(bank, rates):
    if not rates:
        return (
            f"❌ <b>Помилка</b>\n"
            f"😕 Не вдалося отримати курси валют від {bank}.\n"
            f"🔄 Спробуйте ще раз пізніше!"
        )

    current_time = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    message = (
        f"💸 <b>Курси валют від {bank}</b>\n"
        f"🕒 <i>Оновлено: {current_time}</i>\n"
        f"┌───────────────\n"
        f"│ 🇺🇸 <b>USD/UAH</b>\n"
        f"│ Покупка: {rates['usd_buy']:.2f} ₴\n"
        f"│ Продаж: {rates['usd_sell']:.2f} ₴\n"
        f"├───────────────\n"
        f"│ 🇪🇺 <b>EUR/UAH</b>\n"
        f"│ Покупка: {rates['eur_buy']:.2f} ₴\n"
        f"│ Продаж: {rates['eur_sell']:.2f} ₴\n"
    )
    if bank == "(В розробці)":
        message += (
            f"├───────────────\n"
            f"│ ₿ <b>BTC/UAH</b>\n"
            f"│ Курс: {rates['btc_buy']:.2f} ₴\n"
            f"├───────────────\n"
            f"│ Ξ <b>ETH/UAH</b>\n"
            f"│ Курс: {rates['eth_buy']:.2f} ₴\n"
            f"├───────────────\n"
            f"│ ₮ <b>USDT/UAH</b>\n"
            f"│ Курс: {rates['usdt_buy']:.2f} ₴\n"
        )
    message += f"└───────────────\n📊 <i>Джерело: API {bank}</i>"
    return message

async def format_compare_message():
    mono_rates = await get_monobank_rates()
    privat_rates = await get_privatbank_rates()
    nbu_rates = await get_nbu_rates()
    coingecko_rates = await get_coingecko_rates()

    current_time = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    message = (
        f"⚖️ <b>Порівняння курсів валют</b>\n"
        f"🕒 <i>Оновлено: {current_time}</i>\n"
        f"┌───────────────────────────────────────────────\n"
        f"│ <b>Валюта</b> | <b>Monobank</b> | <b>Приват24</b> | <b>НБУ</b> | <b>(В розробці)</b>\n"
        f"├───────────────────────────────────────────────\n"
    )

    if not all([mono_rates, privat_rates, nbu_rates, coingecko_rates]):
        message += (
            f"│ 😕 Помилка отримання даних від одного або кількох джерел\n"
            f"└───────────────────────────────────────────────\n"
            f"🔄 Спробуйте ще раз пізніше!"
        )
        return message

    message += (
        f"│ 🇺🇸 <b>USD Покупка</b> | {mono_rates['usd_buy']:.2f} | {privat_rates['usd_buy']:.2f} | {nbu_rates['usd_buy']:.2f} | -\n"
        f"│ 🇺🇸 <b>USD Продаж</b>  | {mono_rates['usd_sell']:.2f} | {privat_rates['usd_sell']:.2f} | {nbu_rates['usd_sell']:.2f} | -\n"
        f"├───────────────────────────────────────────────\n"
        f"│ 🇪🇺 <b>EUR Покупка</b> | {mono_rates['eur_buy']:.2f} | {privat_rates['eur_buy']:.2f} | {nbu_rates['eur_buy']:.2f} | -\n"
        f"│ 🇪🇺 <b>EUR Продаж</b>  | {mono_rates['eur_sell']:.2f} | {privat_rates['eur_sell']:.2f} | {nbu_rates['eur_sell']:.2f} | -\n"
        f"├───────────────────────────────────────────────\n"
        f"│ ₿ <b>BTC Курс</b>     | - | - | - | {coingecko_rates['btc_buy']:.2f}\n"
        f"│ Ξ <b>ETH Курс</b>     | - | - | - | {coingecko_rates['eth_buy']:.2f}\n"
        f"│ ₮ <b>USDT Курс</b>    | - | - | - | {coingecko_rates['usdt_buy']:.2f}\n"
        f"└───────────────────────────────────────────────\n"
        f"📊 <i>Джерело: API Monobank, Приват24, НБУ, (В розробці)</i>"
    )
    return message

async def format_history_message(bank, period_hours=24):
    history = await get_rate_history(bank, period_hours)
    if not history:
        return f"📊 <b>Історія курсів {bank}</b>\n😕 Даних за останні {period_hours} годин немає."

    message = f"📊 <b>Історія курсів {bank} за останні {period_hours} годин</b>\n"
    message += "┌──────────────────────────────────────\n"
    for entry in history:
        timestamp = entry["timestamp"].strftime("%d.%m.%Y %H:%M:%S")
        rates = entry["rates"]
        message += (
            f"│ 🕒 {timestamp}\n"
            f"│ 🇺🇸 USD Покупка: {rates['usd_buy']:.2f} | Продаж: {rates['usd_sell']:.2f}\n"
            f"│ 🇪🇺 EUR Покупка: {rates['eur_buy']:.2f} | Продаж: {rates['eur_sell']:.2f}\n"
        )
        if bank == "(В розробці)":
            message += (
                f"│ ₿ BTC Курс: {rates['btc_buy']:.2f}\n"
                f"│ Ξ ETH Курс: {rates['eth_buy']:.2f}\n"
                f"│ ₮ USDT Курс: {rates['usdt_buy']:.2f}\n"
            )
        message += f"├──────────────────────────────────────\n"
    message += f"📊 <i>Джерело: API {bank}</i>"
    return message

def create_main_menu_keyboard():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📈 Курси валют", callback_data="currency_menu"),
            InlineKeyboardButton(text="🧮 Калькулятор", callback_data="calc")
        ],
        [
            InlineKeyboardButton(text="⚙️ Налаштування", callback_data="settings_menu")
        ]
    ])
    return keyboard

def create_currency_menu_keyboard():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🏦 Поточні курси", callback_data="rates"),
            InlineKeyboardButton(text="⚖️ Порівняння", callback_data="compare")
        ],
        [
            InlineKeyboardButton(text="📊 Історія курсів", callback_data="history"),
            InlineKeyboardButton(text="↩️ Назад до меню", callback_data="back_to_menu")
        ]
    ])
    return keyboard

def create_settings_menu_keyboard():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🏦 Встановити банк", callback_data="setbank"),
            InlineKeyboardButton(text="🔔 Сповіщення", callback_data="subscribe")
        ],
        [
            InlineKeyboardButton(text="📞 Підтримка", callback_data="support"),
            InlineKeyboardButton(text="↩️ Назад до меню", callback_data="back_to_menu")
        ]
    ])
    return keyboard

def create_bank_selection_keyboard():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🏦 Monobank", callback_data="monobank"),
            InlineKeyboardButton(text="🏦 Приват24", callback_data="privatbank")
        ],
        [
            InlineKeyboardButton(text="🏦 НБУ", callback_data="nbu"),
            InlineKeyboardButton(text="🏦 (В розробці)", callback_data="(В розробці)")
        ],
        [InlineKeyboardButton(text="↩️ Назад до меню", callback_data="back_to_menu")]
    ])
    return keyboard

def create_calc_options_keyboard():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🇺🇸 USD Покупка", callback_data="usd_buy"),
            InlineKeyboardButton(text="🇺🇸 USD Продаж", callback_data="usd_sell"),
            InlineKeyboardButton(text="🇪🇺 EUR Покупка", callback_data="eur_buy"),
            InlineKeyboardButton(text="🇪🇺 EUR Продаж", callback_data="eur_sell")
        ],
        [
            InlineKeyboardButton(text="₿ BTC Курс", callback_data="btc_buy"),
            InlineKeyboardButton(text="Ξ ETH Курс", callback_data="eth_buy"),
            InlineKeyboardButton(text="₮ USDT Курс", callback_data="usdt_buy")
        ],
        [
            InlineKeyboardButton(text="❌ Скасувати", callback_data="cancel"),
            InlineKeyboardButton(text="↩️ Назад до меню", callback_data="back_to_menu")
        ]
    ])
    return keyboard

def create_support_login_keyboard():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔐 Вхід", callback_data="support_login")],
        [InlineKeyboardButton(text="↩️ Назад до меню", callback_data="back_to_menu")]
    ])
    return keyboard

async def set_bot_commands():
    commands = [
        BotCommand(command="start", description="Розпочати роботу з ботом"),
        BotCommand(command="rates", description="Переглянути курси валют"),
        BotCommand(command="calc", description="Користуватися калькулятором валют"),
        BotCommand(command="setbank", description="Обрати банк за замовчуванням"),
        BotCommand(command="subscribe", description="Підписатися на сповіщення про курси"),
        BotCommand(command="unsubscribe", description="Відписатися від сповіщень"),
        BotCommand(command="compare", description="Порівняти курси банків"),
        BotCommand(command="target", description="Встановити цільовий курс"),
        BotCommand(command="support", description="Зв’язатися з підтримкою"),
        BotCommand(command="stats", description="Переглянути статистику відвідувачів")
    ]
    await bot.set_my_commands(commands)

async def monitor_rates():
    RATE_CHANGE_THRESHOLD = 0.5
    CRYPTO_RATE_CHANGE_THRESHOLD = 1000.0
    while True:
        for user_id, banks in subscriptions.items():
            for bank, last_rates in banks.items():
                current_rates = None
                if bank == "Monobank":
                    current_rates = await get_monobank_rates()
                elif bank == "Приват24":
                    current_rates = await get_privatbank_rates()
                elif bank == "НБУ":
                    current_rates = await get_nbu_rates()
                elif bank == "(В розробці)":
                    current_rates = await get_coingecko_rates()

                if not current_rates:
                    continue

                changes = []
                threshold = CRYPTO_RATE_CHANGE_THRESHOLD if bank == "(В розробці)" else RATE_CHANGE_THRESHOLD
                rate_keys = (
                    ["usd_buy", "usd_sell", "eur_buy", "eur_sell"]
                    if bank != "(В розробці)"
                    else ["usd_buy", "usd_sell", "eur_buy", "eur_sell", "btc_buy", "eth_buy", "usdt_buy"]
                )
                for key in rate_keys:
                    if last_rates.get(key) and current_rates.get(key):
                        diff = abs(current_rates[key] - last_rates[key])
                        if diff >= threshold:
                            currency = key.split("_")[0].upper()
                            action = "Покупка" if "buy" in key else "Продаж" if "sell" in key else "Курс"
                            changes.append(
                                f"│ {currency} {action}: {last_rates[key]:.2f} → {current_rates[key]:.2f} ({'+' if current_rates[key] > last_rates[key] else '-'}{diff:.2f} ₴"
                            )
                    last_rates[key] = current_rates[key]

                    if user_id in target_rates and bank in target_rates[user_id]:
                        target_rate = target_rates[user_id][bank].get(key)
                        if target_rate and abs(current_rates[key] - target_rate) <= (0.1 if bank != "(В розробці)" else 100.0):
                            currency = key.split("_")[0].upper()
                            action = "Покупка" if "buy" in key else "Продаж" if "sell" in key else "Курс"
                            await bot.send_message(
                                user_id,
                                f"🎯 <b>Досягнуто цільовий курс!</b>\n"
                                f"🏦 {bank}: {currency} {action} = {current_rates[key]:.2f} UAH (ціль: {target_rate:.2f} UAH)\n"
                                f"🕒 <i>{datetime.now().strftime('%d.%m.%Y %H:%M:%S')}</i>",
                                parse_mode="HTML"
                            )
                            del target_rates[user_id][bank][key]

                if changes:
                    message = (
                        f"📢 <b>Зміна курсів у {bank}</b>\n"
                        f"🕒 <i>{datetime.now().strftime('%d.%m.%Y %H:%M:%S')}</i>\n"
                        f"┌───────────────\n"
                        + "\n".join(changes) +
                        f"\n└───────────────\n"
                        f"📊 <i>Джерело: API {bank}</i>"
                    )
                    try:
                        await bot.send_message(user_id, message, parse_mode="HTML")
                    except Exception as e:
                        logging.error(f"Не вдалося надіслати сповіщення користувачу {user_id}: {e}")

        await asyncio.sleep(600)

@dp.message(Command("start"))
async def start_command(message: types.Message):
    user_id = message.from_user.id
    unique_users.add(user_id)  # Додаємо користувача до множини унікальних
    keyboard = create_main_menu_keyboard()
    default_bank = user_preferences.get(user_id, {}).get("default_bank", "немає")
    message_text = (
        f"👋 <b>Вітаємо в CurrencyBot!</b>\n"
        f"💸 Ваш помічник для роботи з курсами валют\n"
        f"┌───────────────\n"
        f"│ 📈 Перегляньте курси: /rates\n"
        f"│ 🧮 Калькулятор валют: /calc\n"
        f"│ 🏦 Банк за замовчуванням: <b>{default_bank}</b> (/setbank)\n"
        f"│ 🔔 Сповіщення про курси: /subscribe\n"
        f"│ ⚖️ Порівняння банків: /compare\n"
        f"│ 🎯 Цільовий курс: /target\n"
        f"│ 📞 Підтримка: /support\n"
        f"│ 📊 Статистика: /stats\n"
        f"└───────────────\n"
        f"👇 Оберіть дію:"
    )
    await message.answer(message_text, reply_markup=keyboard, parse_mode="HTML")

@dp.message(Command("rates"))
async def rates_command(message: types.Message):
    user_id = message.from_user.id
    default_bank = user_preferences.get(user_id, {}).get("default_bank")

    if default_bank:
        rates = None
        if default_bank == "Monobank":
            rates = await get_monobank_rates()
        elif default_bank == "Приват24":
            rates = await get_privatbank_rates()
        elif default_bank == "НБУ":
            rates = await get_nbu_rates()
        elif default_bank == "(В розробці)":
            rates = await get_coingecko_rates()
        message_text = await format_currency_message(default_bank, rates)
        keyboard = create_currency_menu_keyboard()
        await message.answer(message_text, reply_markup=keyboard, parse_mode="HTML")
    else:
        keyboard = create_bank_selection_keyboard()
        await message.answer(
            f"💸 <b>Оберіть банк для перегляду курсів:</b>",
            reply_markup=keyboard,
            parse_mode="HTML"
        )

@dp.message(Command("calc"))
async def calc_command(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    default_bank = user_preferences.get(user_id, {}).get("default_bank")

    if default_bank:
        await state.update_data(bank=default_bank)
        keyboard = create_calc_options_keyboard()
        await message.answer(
            f"🧮 <b>Калькулятор валют</b>\n"
            f"🏦 Вибрано <b>{default_bank}</b>\n"
            f"👇 Оберіть валюту та операцію:",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        await state.set_state(CalcState.waiting_for_currency_and_operation)
    else:
        keyboard = create_bank_selection_keyboard()
        await message.answer(
            f"🧮 <b>Калькулятор валют</b>\n"
            f"👇 Оберіть банк:",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        await state.set_state(CalcState.waiting_for_bank)

@dp.message(Command("setbank"))
async def setbank_command(message: types.Message, state: FSMContext):
    keyboard = create_bank_selection_keyboard()
    await message.answer(
        f"🏦 <b>Оберіть банк за замовчуванням:</b>",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await state.set_state(PreferenceState.waiting_for_bank)

@dp.message(Command("subscribe"))
async def subscribe_command(message: types.Message):
    keyboard = create_bank_selection_keyboard()
    await message.answer(
        f"🔔 <b>Підписка на сповіщення</b>\n"
        f"👇 Оберіть банк для сповіщень про зміну курсів:\n"
        f"ℹ️ Сповіщення надсилаються при зміні курсів USD або EUR більше ніж на 0.5 ₴, для криптовалют — більше ніж на 1000 ₴",
        reply_markup=keyboard,
        parse_mode="HTML"
    )

@dp.message(Command("unsubscribe"))
async def unsubscribe_command(message: types.Message):
    user_id = message.from_user.id
    keyboard = create_main_menu_keyboard()
    if user_id in subscriptions:
        del subscriptions[user_id]
        await message.answer(
            f"🛑 <b>Відписка успішна</b>\n"
            f"Ви більше не отримуватимете сповіщення.",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    else:
        await message.answer(
            f"ℹ️ <b>Ви не підписані</b>\n"
            f"Використовуйте /subscribe, щоб отримувати сповіщення.",
            reply_markup=keyboard,
            parse_mode="HTML"
        )

@dp.message(Command("compare"))
async def compare_command(message: types.Message):
    message_text = await format_compare_message()
    keyboard = create_currency_menu_keyboard()
    await message.answer(message_text, reply_markup=keyboard, parse_mode="HTML")

@dp.message(Command("target"))
async def target_command(message: types.Message, state: FSMContext):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🇺🇸 USD", callback_data="target_usd"),
            InlineKeyboardButton(text="🇪🇺 EUR", callback_data="target_eur")
        ],
        [
            InlineKeyboardButton(text="₿ BTC", callback_data="target_btc"),
            InlineKeyboardButton(text="Ξ ETH", callback_data="target_eth"),
            InlineKeyboardButton(text="₮ USDT", callback_data="target_usdt")
        ],
        [InlineKeyboardButton(text="↩️ Назад до меню", callback_data="back_to_menu")]
    ])
    await message.answer(
        f"🎯 <b>Встановити цільовий курс</b>\n"
        f"👇 Оберіть валюту:",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await state.set_state(TargetRateState.waiting_for_currency)

@dp.message(Command("support"))
async def support_command(message: types.Message):
    keyboard = create_support_login_keyboard()
    await message.answer(
        f"📞 <b>Панель підтримки</b>\n"
        f"👇 Натисніть 'Вхід', щоб отримати код доступу.",
        reply_markup=keyboard,
        parse_mode="HTML"
    )

@dp.message(Command("stats"))
async def stats_command(message: types.Message):
    keyboard = create_main_menu_keyboard()
    await message.answer(
        f"📊 <b>Статистика бота</b>\n"
        f"👥 <b>Кількість відвідувачів:</b> {len(unique_users)}\n"
        f"👇 Оберіть дію:",
        reply_markup=keyboard,
        parse_mode="HTML"
    )

@dp.callback_query(PreferenceState.waiting_for_bank, lambda c: c.data in ["monobank", "privatbank", "nbu", "(В розробці)"])
async def process_setbank_selection(callback_query: types.CallbackQuery, state: FSMContext):
    bank = callback_query.data.capitalize()
    if bank == "Nbu":
        bank = "НБУ"
    elif bank == "Privatbank":
        bank = "Приват24"
    elif bank == "(В розробці)":
        bank = "(В розробці)"
    user_id = callback_query.from_user.id
    user_preferences[user_id] = {"default_bank": bank}
    keyboard = create_settings_menu_keyboard()
    message_text = (
        f"✅ <b>Успіх!</b>\n"
        f"🏦 Встановлено <b>{bank}</b> як банк за замовчуванням."
    )
    await callback_query.message.answer(message_text, reply_markup=keyboard, parse_mode="HTML")
    await state.clear()
    await callback_query.answer()

@dp.callback_query(CalcState.waiting_for_bank, lambda c: c.data in ["monobank", "privatbank", "nbu", "(В розробці)", "back_to_menu"])
async def process_calc_bank_selection(callback_query: types.CallbackQuery, state: FSMContext):
    if callback_query.data == "back_to_menu":
        keyboard = create_main_menu_keyboard()
        message_text = f"👋 <b>Повернення до меню</b>\n👇 Оберіть дію:"
        await callback_query.message.answer(message_text, reply_markup=keyboard, parse_mode="HTML")
        await state.clear()
        await callback_query.answer()
        return

    bank = callback_query.data.capitalize()
    if bank == "Nbu":
        bank = "НБУ"
    elif bank == "Privatbank":
        bank = "Приват24"
    elif bank == "(В розробці)":
        bank = "(В розробці)"
    await state.update_data(bank=bank)
    keyboard = create_calc_options_keyboard()
    await callback_query.message.answer(
        f"🧮 <b>Калькулятор валют</b>\n"
        f"🏦 Вибрано <b>{bank}</b>\n"
        f"👇 Оберіть валюту та операцію:",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await state.set_state(CalcState.waiting_for_currency_and_operation)
    await callback_query.answer()

@dp.callback_query(CalcState.waiting_for_currency_and_operation, lambda c: c.data in ["usd_buy", "usd_sell", "eur_buy", "eur_sell", "btc_buy", "eth_buy", "usdt_buy", "cancel", "back_to_menu"])
async def process_calc_options(callback_query: types.CallbackQuery, state: FSMContext):
    if callback_query.data == "cancel":
        keyboard = create_main_menu_keyboard()
        message_text = f"🛑 <b>Операцію скасовано</b>\n👇 Оберіть дію:"
        await callback_query.message.answer(message_text, reply_markup=keyboard, parse_mode="HTML")
        await state.clear()
        await callback_query.answer()
        return

    if callback_query.data == "back_to_menu":
        keyboard = create_main_menu_keyboard()
        message_text = f"👋 <b>Повернення до меню</b>\n👇 Оберіть дію:"
        await callback_query.message.answer(message_text, reply_markup=keyboard, parse_mode="HTML")
        await state.clear()
        await callback_query.answer()
        return

    data = await state.get_data()
    bank = data.get("bank")
    operation = callback_query.data

    await state.update_data(operation=operation)
    await callback_query.message.answer(
        f"💱 <b>Введіть суму</b>\n"
        f"Операція: {operation.replace('_', ' ').upper()} у {bank}\n"
        f"👇 Введіть число (наприклад, 100 або 100.50):",
        parse_mode="HTML"
    )
    await state.set_state(CalcState.waiting_for_amount)
    await callback_query.answer()

@dp.message(CalcState.waiting_for_amount)
async def process_amount(message: types.Message, state: FSMContext):
    amount_text = message.text
    if not re.match(r"^\d+(\.\d+)?$", amount_text):
        keyboard = create_main_menu_keyboard()
        await message.answer(
            f"❌ <b>Помилка вводу</b>\n"
            f"😕 Введіть коректну числову суму (наприклад, 100 або 100.50).\n"
            f"👇 Оберіть дію або повторіть:",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        return

    amount = float(amount_text)
    if amount <= 0:
        keyboard = create_main_menu_keyboard()
        await message.answer(
            f"❌ <b>Помилка</b>\n"
            f"😕 Сума повинна бути більше 0.\n"
            f"👇 Оберіть дію або повторіть:",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        return

    data = await state.get_data()
    bank = data.get("bank")
    operation = data.get("operation")

    rates = None
    if bank == "Monobank":
        rates = await get_monobank_rates()
    elif bank == "Приват24":
        rates = await get_privatbank_rates()
    elif bank == "НБУ":
        rates = await get_nbu_rates()
    elif bank == "(В розробці)":
        rates = await get_coingecko_rates()

    if not rates:
        keyboard = create_main_menu_keyboard()
        await message.answer(
            f"❌ <b>Помилка</b>\n"
            f"😕 Не вдалося отримати курси валют від {bank}.\n"
            f"👇 Оберіть дію:",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        await state.clear()
        return

    rate_key = operation
    rate = rates.get(rate_key)

    if not rate:
        keyboard = create_main_menu_keyboard()
        await message.answer(
            f"❌ <b>Помилка</b>\n"
            f"😕 Не вдалося отримати курс для {operation.replace('_', ' ').upper()} від {bank}.\n"
            f"👇 Оберіть дію:",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        await state.clear()
        return

    currency = operation.split("_")[0].upper()
    action = "buy" if "buy" in operation else "sell" if "sell" in operation else "buy"
    result = amount * rate if action == "buy" else amount / rate
    input_currency = currency if action == "buy" else "UAH"
    output_currency = "UAH" if action == "buy" else currency

    current_time = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    message_text = (
        f"🧮 <b>Калькулятор валют {bank}</b>\n"
        f"🕒 <i>Оновлено: {current_time}</i>\n"
        f"┌───────────────\n"
        f"│ 💱 <b>Операція</b>: {operation.replace('_', ' ').upper()}\n"
        f"│ 💵 <b>Сума</b>: {amount:.2f} {input_currency}\n"
        f"│ ➡️ <b>Результат</b>: {result:.2f} {output_currency}\n"
        f"│ 📖 <b>Курс</b>: 1 {currency} = {rate:.2f} UAH\n"
        f"└───────────────\n"
        f"📖 <i>Джерело: API {bank}</i>\n"
        f"👇 Оберіть дію:"
        )
    keyboard = create_main_menu_keyboard()
    await message.answer(message_text, reply_markup=keyboard, parse_mode="HTML")
    await state.clear()

@dp.callback_query(lambda c: c.data in ["monobank", "privatbank", "nbu", "(В розробці)"])
async def process_bank_selection(callback_query: types.CallbackQuery):
    bank = callback_query.data.capitalize()
    if bank == "Nbu":
        bank = "НБУ"
    elif bank == "Privatbank":
        bank = "Приват24"
    elif bank == "(В розробці)":
        bank = "(В розробці)"
    user_id = callback_query.from_user.id

    if callback_query.message.text.startswith("🔔"):
        if user_id not in subscriptions:
            subscriptions[user_id] = {}
        rates = None
        if bank == "Monobank":
            rates = await get_monobank_rates()
        elif bank == "Приват24":
            rates = await get_privatbank_rates()
        elif bank == "НБУ":
            rates = await get_nbu_rates()
        elif bank == "(В розробці)":
            rates = await get_coingecko_rates()

        if rates:
            subscriptions[user_id][bank] = rates.copy()
            keyboard = create_settings_menu_keyboard()
            message_text = (
                f"✅ <b>Підписка успішна!</b>\n"
                f"🔔 Ви отримуватимете сповіщення про зміну курсів від <b>{bank}</b>."
            )
            await callback_query.message.answer(message_text, reply_markup=keyboard, parse_mode="HTML")
        else:
            keyboard = create_settings_menu_keyboard()
            message_text = (
                f"❌ <b>Помилка</b>\n"
                f"😕 Не вдалося підписатися на <b>{bank}</b>. Спробуйте пізніше.\n"
                f"👇 Оберіть дію:"
            )
            await callback_query.message.answer(message_text, reply_markup=keyboard, parse_mode="HTML")
        await callback_query.answer()
        return

    rates = None
    if bank == "Monobank":
        rates = await get_monobank_rates()
    elif bank == "Приват24":
        rates = await get_privatbank_rates()
    elif bank == "НБУ":
        rates = await get_nbu_rates()
    elif bank == "(В розробці)":
        rates = await get_coingecko_rates()

    message_text = await format_currency_message(bank, rates)
    keyboard = create_currency_menu_keyboard()
    await callback_query.message.answer(message_text, reply_markup=keyboard, parse_mode="HTML")
    await callback_query.answer()

@dp.callback_query(lambda c: c.data in ["currency_menu", "settings_menu", "rates", "calc", "setbank", "subscribe", "compare", "support", "support_login", "back_to_menu", "history"])
async def process_menu_selection(callback_query: types.CallbackQuery, state: FSMContext):
    action = callback_query.data
    user_id = callback_query.from_user.id

    message_text = ""
    keyboard = None
    if action == "currency_menu":
        message_text = f"📈 <b>Меню курсів валют</b>\n👇 Оберіть дію:"
        keyboard = create_currency_menu_keyboard()
    elif action == "settings_menu":
        message_text = f"⚙️ <b>Меню налаштувань</b>\n👇 Оберіть дію:"
        keyboard = create_settings_menu_keyboard()
    elif action == "history":
        default_bank = user_preferences.get(user_id, {}).get("default_bank", "Monobank")
        message_text = await format_history_message(default_bank)
        keyboard = create_currency_menu_keyboard()
    elif action == "rates":
        default_bank = user_preferences.get(user_id, {}).get("default_bank")
        if default_bank:
            rates = None
            if default_bank == "Monobank":
                rates = await get_monobank_rates()
            elif default_bank == "Приват24":
                rates = await get_privatbank_rates()
            elif default_bank == "НБУ":
                rates = await get_nbu_rates()
            elif default_bank == "(В розробці)":
                rates = await get_coingecko_rates()
            message_text = await format_currency_message(default_bank, rates)
            keyboard = create_currency_menu_keyboard()
        else:
            message_text = f"💸 <b>Оберіть банк для перегляду курсів:</b>"
            keyboard = create_bank_selection_keyboard()
    elif action == "calc":
        default_bank = user_preferences.get(user_id, {}).get("default_bank")
        if default_bank:
            await state.update_data(bank=default_bank)
            message_text = (
                f"🧮 <b>Калькулятор валют</b>\n"
                f"🏦 Вибрано <b>{default_bank}</b>\n"
                f"👇 Оберіть валюту та операцію:"
            )
            keyboard = create_calc_options_keyboard()
            await state.set_state(CalcState.waiting_for_currency_and_operation)
        else:
            message_text = f"🧮 <b>Калькулятор валют</b>\n👇 Оберіть банк:"
            keyboard = create_bank_selection_keyboard()
            await state.set_state(CalcState.waiting_for_bank)
    elif action == "setbank":
        message_text = f"🏦 <b>Оберіть банк за замовчуванням:</b>"
        keyboard = create_bank_selection_keyboard()
        await state.set_state(PreferenceState.waiting_for_bank)
    elif action == "subscribe":
        message_text = (
            f"🔔 <b>Підписка на сповіщення</b>\n"
            f"👇 Оберіть банк для сповіщень про зміну курсів:\n"
            f"ℹ️ Сповіщення надсилаються при зміні курсів USD або EUR більше ніж на 0.5 ₴, для криптовалют — більше ніж на 1000 ₴"
        )
        keyboard = create_bank_selection_keyboard()
    elif action == "compare":
        message_text = await format_compare_message()
        keyboard = create_currency_menu_keyboard()
    elif action == "support":
        message_text = f"📞 <b>Панель підтримки</b>\n👇 Натисніть 'Вхід', щоб отримати код доступу."
        keyboard = create_support_login_keyboard()
    elif action == "support_login":
        password = f"{random.randint(0, 9999):04d}"
        support_passwords[user_id] = {
            "password": password,
            "expires": datetime.now() + timedelta(minutes=5)
        }
        message_text = (
            f"🔐 <b>Вхід до панелі підтримки</b>\n"
            f"Ваш код доступу: <code>{password}</code>\n"
            f"👇 Введіть цей код (4 цифри) протягом 5 хвилин:"
        )
        keyboard = create_support_login_keyboard()
        await state.set_state(SupportState.waiting_for_password)
    elif action == "back_to_menu":
        message_text = f"👋 <b>Повернення до меню</b>\n👇 Оберіть дію:"
        keyboard = create_main_menu_keyboard()
        await state.clear()

    await callback_query.message.answer(message_text, reply_markup=keyboard, parse_mode="HTML")
    await callback_query.answer()

@dp.callback_query(TargetRateState.waiting_for_currency, lambda c: c.data in ["target_usd", "target_eur", "target_btc", "target_eth", "target_usdt"])
async def process_target_currency(callback_query: types.CallbackQuery, state: FSMContext):
    currency_map = {
        "target_usd": "USD",
        "target_eur": "EUR",
        "target_btc": "BTC",
        "target_eth": "ETH",
        "target_usdt": "USDT"
    }
    currency = currency_map[callback_query.data]
    await state.update_data(currency=currency)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Покупка", callback_data="target_buy"),
            InlineKeyboardButton(text="Продаж", callback_data="target_sell")
        ] if currency in ["USD", "EUR"] else [
            InlineKeyboardButton(text="Курс", callback_data="target_buy")
        ],
        [InlineKeyboardButton(text="↩️ Назад до меню", callback_data="back_to_menu")]
    ])
    await callback_query.message.answer(
        f"🎯 <b>Встановити цільовий курс для {currency}</b>\n"
        f"👇 Оберіть операцію:",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await state.set_state(TargetRateState.waiting_for_operation)
    await callback_query.answer()

@dp.callback_query(TargetRateState.waiting_for_operation, lambda c: c.data in ["target_buy", "target_sell"])
async def process_target_operation(callback_query: types.CallbackQuery, state: FSMContext):
    operation = callback_query.data.split("_")[1]
    data = await state.get_data()
    currency = data.get("currency")
    await state.update_data(operation=operation)
    await callback_query.message.answer(
        f"🎯 <b>Встановити цільовий курс для {currency} {operation}</b>\n"
        f"👇 Введіть бажаний курс (наприклад, 40.50):",
        parse_mode="HTML"
    )
    await state.set_state(TargetRateState.waiting_for_rate)
    await callback_query.answer()

@dp.message(TargetRateState.waiting_for_rate)
async def process_target_rate(message: types.Message, state: FSMContext):
    rate_text = message.text.strip()
    if not re.match(r"^\d+(\.\d+)?$", rate_text):
        keyboard = create_main_menu_keyboard()
        await message.answer(
            f"❌ <b>Помилка вводу</b>\n"
            f"😕 Введіть коректний курс (наприклад, 40.50).\n"
            f"👇 Оберіть дію:",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        return

    target_rate = float(rate_text)
    if target_rate <= 0:
        keyboard = create_main_menu_keyboard()
        await message.answer(
            f"❌ <b>Помилка</b>\n"
            f"😕 Курс повинен бути більше 0.\n"
            f"👇 Оберіть дію:",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        return

    data = await state.get_data()
    currency = data.get("currency")
    operation = data.get("operation")
    user_id = message.from_user.id
    bank = user_preferences.get(user_id, {}).get("default_bank", "Monobank")

    target_rates[user_id][bank] = target_rates[user_id].get(bank, {})
    target_rates[user_id][bank][f"{currency.lower()}_{operation}"] = target_rate

    keyboard = create_main_menu_keyboard()
    message_text = (
        f"✅ <b>Цільовий курс встановлено!</b>\n"
        f"🎯 Ви будете повідомлені, коли {currency} {operation} у {bank} досягне {target_rate:.2f} UAH.\n"
        f"👇 Оберіть дію:"
    )
    await message.answer(message_text, reply_markup=keyboard, parse_mode="HTML")
    await state.clear()

@dp.message(SupportState.waiting_for_password)
async def process_support_password(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    input_password = message.text.strip()

    if user_id not in support_passwords:
        keyboard = create_main_menu_keyboard()
        await message.answer(
            f"❌ <b>Помилка</b>\n"
            f"😕 Сесія авторизації закінчилась. Спробуйте ще раз через /support.\n"
            f"👇 Оберіть дію:",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        await state.clear()
        return

    stored = support_passwords[user_id]
    if datetime.now() > stored["expires"]:
        del support_passwords[user_id]
        keyboard = create_main_menu_keyboard()
        await message.answer(
            f"❌ <b>Помилка</b>\n"
            f"😕 Код доступу прострочений. Спробуйте ще раз через /support.\n"
            f"👇 Оберіть дію:",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        await state.clear()
        return

    if not re.match(r"^\d{4}$", input_password):
        keyboard = create_support_login_keyboard()
        await message.answer(
            f"❌ <b>Помилка</b>\n"
            f"😕 Введіть коректний 4-значний код.\n"
            f"👇 Спробуйте ще раз або поверніться до меню:",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        return

    if input_password == stored["password"]:
        del support_passwords[user_id]
        keyboard = create_main_menu_keyboard()
        message_text = (
            f"✅ <b>Успіх!</b>\n"
            f"📞 Ви увійшли до панелі підтримки.\n"
            f"ℹ️ Наразі це тестова версія. Зв’яжіться з нами через @Street_04 для реальної підтримки.\n"
            f"👇 Оберіть дію:"
        )
        await message.answer(message_text, reply_markup=keyboard, parse_mode="HTML")
        await state.clear()
    else:
        del support_passwords[user_id]
        keyboard = create_main_menu_keyboard()
        await message.answer(
            f"❌ <b>Помилка</b>\n"
            f"😕 Неправильний код. Спробуйте ще раз через /support.\n"
            f"👇 Оберіть дію:",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        await state.clear()

async def main():
    await set_bot_commands()
    asyncio.create_task(monitor_rates())
    await dp.start_polling(bot)

await main()
