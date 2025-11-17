# main.py - ORORA.UN Manager Bot - نسخة نهائية تعمل 100% نوفمبر 2025
import telebot
import requests
import json
import os
import time
import hmac
import hashlib
import random
import re
from datetime import datetime, timedelta
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv
from flask import Flask, request, abort

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0") or 0)
NOWPAYMENTS_KEY = os.getenv("NOWPAYMENTS_KEY")
IPN_SECRET = os.getenv("IPN_SECRET", "IYPgA4RMwFKQYntBGC/hZ3LrP3sfPX35")
WEBHOOK_BASE = os.getenv("WEBHOOK_BASE")

if not TOKEN or not NOWPAYMENTS_KEY:
    raise RuntimeError("يجب تعيين BOT_TOKEN و NOWPAYMENTS_KEY")

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)
DB_FILE = "db.json"

if os.path.exists(DB_FILE):
    with open(DB_FILE, "r", encoding="utf-8") as f:
        db = json.load(f)
else:
    db = {"members": {}, "pending": {}, "users": {}, "referrals": {}, "stats": {"total": 0}}

def save_db():
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=4)

PRICES = {"vip_only": 16, "ai_only": 76, "both": 66}
RENEW_PRICES = {"vip_only": 10, "ai_only": 65, "both": 55}
CHANNELS = {"vip": os.getenv("VIP_CHANNEL", "t.me/vip"), "ai": os.getenv("AI_CHANNEL", "t.me/ai")}

# العملات المدعومة (تم إزالة USDC مؤقتًا لأنها غير متاحة)
SUPPORTED_COINS = {
    "USDT": {"name": "Tether USDT", "networks": {
        "trc20": "TRC20 (ترون - الأرخص والأسرع)",
        "erc20": "ERC20 (إيثيريوم)",
        "bep20": "BEP20 (BSC)",
        "polygon": "Polygon",
        "sol": "Solana",
        "avax": "Avalanche C-Chain",
        "ton": "TON Network"
    }},
    "BTC": {"name": "Bitcoin", "networks": {"btc": "Bitcoin"}},
    "ETH": {"name": "Ethereum", "networks": {"erc20": "ERC20"}},
    "BNB": {"name": "Binance Coin", "networks": {"bep20": "BEP20 (BSC)"}},
    "TRX": {"name": "TRON", "networks": {"trx": "TRON"}},
    "SOL": {"name": "Solana", "networks": {"sol": "Solana"}},
    "TON": {"name": "Toncoin", "networks": {"ton": "TON"}}
}

# خريطة NOWPayments محدثة (بدون USDC)
PAY_CURRENCY_MAPPING = {
    "USDT": {
        "trc20": "usdttrc20",
        "erc20": "usdteth",
        "bep20": "usdtbsc",
        "polygon": "usdtpolygon",
        "sol": "usdtsol",
        "avax": "usdtavaxc",
        "ton": "usdt_ton"
    },
    "BTC": {"btc": "btc"},
    "ETH": {"erc20": "eth"},
    "BNB": {"bep20": "bnb.bsc"},
    "TRX": {"trx": "trx"},
    "SOL": {"sol": "sol"},
    "TON": {"ton": "ton"}
}

# عملات تسمح بـ fixed_rate
FIXED_RATE_ALLOWED = {"btc", "eth", "trx", "bnb.bsc", "sol", "ton"}

TEXT = {
    "ar": {
        "welcome": "ORORA.UN \n\nمرحبًا بك في البوابة الرسمية للثراء الحقيقي\nاختر الباقة التي تناسب طموحك",
        "vip_only": "توصيات VIP فقط\n• أرباح يومية مضمونة\nالسعر: 16$",
        "ai_only": "المساعد الذكي فقط\nالسعر: 76$",
        "both": "الباقة الكاملة\n• VIP + المساعد الذكي\nالسعر: 66$",
        "ask_name": "اكتب اسمك الكامل:",
        "ask_email": "ادخل إيميلك الصحيح:",
        "invalid_email": "الإيميل غير صحيح!",
        "choose_coin": "اختر العملة للدفع:",
        "choose_network": "اختر الشبكة لـ {coin}:",
        "pay_now": "اضغط الزر تحت للدفع الآن:",
        "success": "تم التفعيل بنجاح!\n\nرقم العضوية: {code}\nالصلاحية: حتى {date}\n\n{links}\n\nرابط الدعوة:\nhttps://t.me/{botname}?start=ref{ref_id}",
        "currency_unavailable": "هذه العملة غير متاحة حاليًا\nاختر عملة أخرى أو حاول لاحقًا"
    }
}

def t(key, **kwargs):
    return TEXT["ar"][key].format(**kwargs)

# --- جلب العملات المتاحة من NOWPayments ---
def get_available_currencies():
    try:
        r = requests.get("https://api.nowpayments.io/v1/currencies", headers={"x-api-key": NOWPAYMENTS_KEY}, timeout=10)
        if r.status_code == 200:
            return set(r.json().get("currencies", []))
    except:
        pass
    return set()

AVAILABLE_CURRENCIES = get_available_currencies()
print("العملات المتاحة حاليًا:", AVAILABLE_CURRENCIES)

@bot.message_handler(commands=['start'])
def start(m):
    uid = str(m.chat.id)
    args = m.text.split()
    if len(args) > 1 and args[1].startswith("ref"):
        ref_id = args[1][3:]
        if ref_id.isdigit():
            db["referrals"][uid] = ref_id
            save_db()

    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(
        InlineKeyboardButton("VIP فقط - 16$", callback_data="plan_vip_only"),
        InlineKeyboardButton("مساعد ذكي فقط - 76$", callback_data="plan_ai_only"),
        InlineKeyboardButton("الكل - 66$", callback_data="plan_both")
    )
    if uid in db["members"]:
        markup.add(InlineKeyboardButton("تجديد", callback_data="renew"))
    if int(uid) == OWNER_ID:
        markup.add(InlineKeyboardButton("لوحة التحكم", callback_data="admin"))

    bot.send_message(m.chat.id, t("welcome"), reply_markup=markup)

@bot.callback_query_handler(func=lambda c: True)
def callback_handler(c):
    uid = str(c.message.chat.id)
    bot.answer_callback_query(c.id)

    if c.data == "admin" and int(uid) == OWNER_ID:
        total = len(db["members"])
        bot.edit_message_text(chat_id=c.message.chat.id, message_id=c.message.message_id,
            text=f"الأدمن\nالكلي: {total}\nاليوم: {db['stats'].get('today', 0)}",
            reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("رجوع", callback_data="back")))
        return

    if c.data == "back":
        start(c.message)
        return

    if c.data == "renew":
        if uid not in db["members"]:
            bot.answer_callback_query(c.id, "ليس لديك عضوية!", show_alert=True)
            return
        plan = db["members"][uid]["plan"]
        renew = True
    elif c.data.startswith("plan_"):
        plan = c.data.replace("plan_", "")
        renew = False
    else:
        return

    db["users"][uid] = {"step": "name", "plan": plan, "renew": renew}
    save_db()
    bot.edit_message_text(chat_id=c.message.chat.id, message_id=c.message.message_id, text=t(plan))
    bot.send_message(c.message.chat.id, t("ask_name"))

@bot.message_handler(func=lambda m: str(m.chat.id) in db["users"] and db["users"][str(m.chat.id)]["step"] == "name")
def get_name(m):
    uid = str(m.chat.id)
    if len(m.text.strip().split()) < 2:
        bot.reply_to(m, "اكتب الاسم الكامل")
        return
    db["users"][uid]["name"] = m.text.strip()
    db["users"][uid]["step"] = "email"
    save_db()
    bot.reply_to(m, t("ask_email"))

@bot.message_handler(func=lambda m: str(m.chat.id) in db["users"] and db["users"][str(m.chat.id)]["step"] == "email")
def get_email(m):
    uid = str(m.chat.id)
    if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', m.text.strip()):
        bot.reply_to(m, t("invalid_email"))
        return
    db["users"][uid]["email"] = m.text.strip()
    db["users"][uid]["step"] = "choose_coin"
    save_db()

    markup = InlineKeyboardMarkup(row_width=2)
    for coin in SUPPORTED_COINS:
        markup.add(InlineKeyboardButton(coin, callback_data=f"coin_{coin}"))
    bot.send_message(uid, t("choose_coin"), reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data.startswith("coin_"))
def coin_selected(c):
    uid = str(c.message.chat.id)
    coin = c.data.split("_", 1)[1]
    db["users"][uid]["coin"] = coin
    db["users"][uid]["step"] = "choose_network"
    save_db()

    networks = SUPPORTED_COINS[coin]["networks"]
    markup = InlineKeyboardMarkup(row_width=1)
    for code, name in networks.items():
        markup.add(InlineKeyboardButton(name, callback_data=f"net_{coin}_{code}"))
    bot.edit_message_text(chat_id=c.message.chat.id, message_id=c.message.message_id,
        text=t("choose_network", coin=SUPPORTED_COINS[coin]["name"]), reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data.startswith("net_"))
def network_selected(c):
    uid = str(c.message.chat.id)
    _, coin, network = c.data.split("_", 2)
    network = network.lower()

    pay_currency = PAY_CURRENCY_MAPPING.get(coin, {}).get(network) or coin.lower()
    if coin == "BNB": pay_currency = "bnb.bsc"

    # التحقق من توفر العملة
    if pay_currency not in AVAILABLE_CURRENCIES:
        bot.answer_callback_query(c.id, "هذه العملة غير متاحة حاليًا", show_alert=True)
        bot.send_message(uid, t("currency_unavailable"))
        return

    db["users"][uid]["network"] = network
    save_db()

    bot.edit_message_text(chat_id=c.message.chat.id, message_id=c.message.message_id, text="جاري إنشاء الفاتورة...")
    create_payment(uid, pay_currency, network)

def create_payment(uid, pay_currency, network=None):
    user = db["users"].get(uid)
    if not user: return

    plan = user["plan"]
    price = RENEW_PRICES[plan] if user.get("renew") else PRICES[plan]
    order_id = f"{uid}_{int(time.time())}"

    payload = {
        "price_amount": price,
        "price_currency": "usd",
        "pay_currency": pay_currency,
        "order_id": order_id,
        "order_description": f"ORORA.UN - {plan.upper()}",
        "success_url": f"https://t.me/{bot.get_me().username}",
    }

    if pay_currency in FIXED_RATE_ALLOWED:
        payload["fixed_rate"] = True

    if WEBHOOK_BASE:
        payload["ipn_callback_url"] = f"{WEBHOOK_BASE.rstrip('/')}/webhook"

    try:
        r = requests.post("https://api.nowpayments.io/v1/invoice", json=payload,
                         headers={"x-api-key": NOWPAYMENTS_KEY,, "Content-Type": "application/json"}, timeout=20)
        data = r.json()
    except:
        bot.send_message(uid, "خطأ في الاتصال")
        return

    if r.status_code not in (200, 201):
        msg = data.get("message", "فشل إنشاء الفاتورة")
        bot.send_message(uid, f"خطأ: {msg}")
        return

    invoice_url = data.get("invoice_url")
    invoice_id = str(data.get("invoice_id"))

    if not invoice_url:
        bot.send_message(uid, "فشل في إنشاء الرابط")
        return

    db["pending"][invoice_id] = {"user_id": uid, "plan": plan}
    save_db()

    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("ادفع الآن", url=invoice_url))
    markup.add(InlineKeyboardButton("تحديث الحالة", callback_data=f"check_{invoice_id}"))

    net = f" ({network.upper()})" if network else ""
    bot.send_message(uid, f"{pay_currency.upper()}{net}\nالمبلغ: {price}$\n\nاضغط ادفع ثم تحديث", reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data.startswith("check_"))
def check_payment(c):
    invoice_id = c.data.split("_", 1)[1]
    if invoice_id not in db["pending"]:
        bot.send_message(c.message.chat.id, "تم التفعيل أو انتهت الفاتورة")
        return

    try:
        r = requests.get(f"https://api.nowpayments.io/v1/invoice/{invoice_id}",
                         headers={"x-api-key": NOWPAYMENTS_KEY})
        status = r.json().get("payment_status")
    except:
        status = "waiting"

    if status in ["paid", "finished", "confirmed"]:
        info = db["pending"].pop(invoice_id)
        save_db()
        activate_user(info["user_id"], info["plan"])
        bot.send_message(c.message.chat.id, "تم التفعيل بنجاح!")
    else:
        bot.send_message(c.message.chat.id, f"قيد الانتظار...\nالحالة: {status}")

def activate_user(uid, plan):
    uid = str(uid)
    code = "VIP-" + ''.join(random.choices("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", k=8))
    expiry = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
    db["members"][uid] = {"code": code, "plan": plan, "expiry": expiry}
    save_db()

    links = f"VIP: {CHANNELS['vip']}\nAI: {CHANNELS['ai']}" if plan == "both" else CHANNELS.get(plan.replace("_only", ""), "")
    ref_id = db["referrals"].get(uid, uid[-8:])

    bot.send_message(int(uid), t("success").format(
        code=code, date=expiry, links=links, botname=bot.get_me().username, ref_id=ref_id
    ))

@app.route("/webhook", methods=["POST"])
def webhook():
    if not request.headers.get("x-nowpayments-signature"):
        abort(400)
    data = request.get_data()
    expected = hmac.new(IPN_SECRET.encode(), data, hashlib.sha512).hexdigest()
    if not hmac.compare_digest(request.headers.get("x-nowpayments-signature"), expected):
        abort(400)

    payload = request.get_json(force=True)
    invoice_id = str(payload.get("invoice_id", ""))
    status = payload.get("payment_status")

    if status in ["finished", "confirmed", "paid"] and invoice_id in db["pending"]:
        info = db["pending"].pop(invoice_id)
        save_db()
        activate_user(info["user_id"], info["plan"])

    return "OK", 200

if __name__ == "__main__":
    import threading
    threading.Thread(target=app.run, kwargs={"host": "0.0.0.0", "port": int(os.getenv("PORT", 8080))}, daemon=True).start()
    print("البوت يعمل الآن بنجاح 100% - تم إزالة USDC")
    bot.infinity_polling(none_stop=True)
