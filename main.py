# main.py - ORORA.UN Manager Bot - النسخة النهائية المدمجة 2025
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

# === المتغيرات الأساسية ===
TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
NOWPAYMENTS_KEY = os.getenv("NOWPAYMENTS_KEY")
IPN_SECRET = os.getenv("IPN_SECRET", "IYPgA4RMwFKQYntBGC/hZ3LrP3sfPX35")
WEBHOOK_BASE = os.getenv("WEBHOOK_BASE")

if not TOKEN or not NOWPAYMENTS_KEY:
    raise RuntimeError("يجب تعيين BOT_TOKEN و NOWPAYMENTS_KEY في ملف .env")

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)
DB_FILE = "db.json"

# === قاعدة البيانات ===
if os.path.exists(DB_FILE):
    with open(DB_FILE, "r", encoding="utf-8") as f:
        db = json.load(f)
else:
    db = {
        "members": {},
        "pending": {},
        "users": {},
        "referrals": {},
        "stats": {"total": 0, "today": 0}
    }

def save_db():
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=4)

# === الأسعار والقنوات ===
PRICES = {"vip_only": 16, "ai_only": 76, "both": 66}
RENEW_PRICES = {"vip_only": 10, "ai_only": 65, "both": 55}
CHANNELS = {
    "vip": os.getenv("VIP_CHANNEL", "t.me/your_vip_channel"),
    "ai": os.getenv("AI_CHANNEL", "t.me/your_ai_channel")
}

# === العملات والشبكات ===
SUPPORTED_COINS = {
    "USDT": {"name": "Tether USDT", "networks": {
        "trc20": "TRC20 (ترون - الأرخص)",
        "erc20": "ERC20 (إيثيريوم)",
        "bep20": "BEP20 (BSC)",
        "polygon": "Polygon",
        "sol": "Solana",
        "avax": "Avalanche C-Chain",
        "ton": "TON Network"
    }},
    "USDC": {"name": "USD Coin", "networks": {
        "trc20": "TRC20 (ترون)",
        "erc20": "ERC20",
        "bep20": "BEP20",
        "polygon": "Polygon",
        "sol": "Solana"
    }},
    "BTC": {"name": "Bitcoin", "networks": {"btc": "Bitcoin"}},
    "ETH": {"name": "Ethereum", "networks": {"erc20": "ERC20"}},
    "BNB": {"name": "Binance Coin", "networks": {"bep20": "BEP20 (BSC)"}},
    "TRX": {"name": "TRON", "networks": {"trx": "TRON"}},
    "SOL": {"name": "Solana", "networks": {"sol": "Solana"}},
    "MATIC": {"name": "Polygon", "networks": {"polygon": "Polygon"}},
    "AVAX": {"name": "Avalanche", "networks": {"avax": "Avalanche C-Chain"}},
    "TON": {"name": "Toncoin", "networks": {"ton": "TON"}}
}

# === خريطة NOWPayments محدثة 100% (نوفمبر 2025) ===
PAY_CURRENCY_MAPPING = {
    "USDT": {"trc20": "usdttrc20", "erc20": "usdteth", "bep20": "usdtbsc", "polygon": "usdtpolygon", "sol": "usdtsol", "avax": "usdtavaxc", "ton": "usdt_ton"},
    "USDC": {"trc20": "usdctrc20", "erc20": "usdceth", "bep20": "usdcbsc", "polygon": "usdcpolygon", "sol": "usdcsol"},
    "BTC": {"btc": "btc"},
    "ETH": {"erc20": "eth"},
    "BNB": {"bep20": "bnb.bsc"},
    "TRX": {"trx": "trx"},
    "SOL": {"sol": "sol"},
    "MATIC": {"polygon": "matic"},
    "AVAX": {"avax": "avaxc"},
    "TON": {"ton": "ton"}
}

# العملات التي تسمح بـ fixed_rate فقط
FIXED_RATE_ALLOWED = {"btc", "eth", "trx", "bnb.bsc", "sol", "ton", "matic", "avaxc", "doge", "ltc"}

# === النصوص متعددة اللغات ===
TEXT = {
    "ar": {
        "welcome": "ORORA.UN \n\nمرحبًا بك في البوابة الرسمية للثراء الحقيقي\nاختر الباقة التي تناسب طموحك",
        "vip_only": "توصيات VIP فقط\n• أرباح يومية مضمونة\nالسعر: 16$",
        "ai_only": "المساعد الذكي فقط\nالسعر: 76$",
        "both": "الباقة الكاملة\n• VIP + المساعد الذكي\nالسعر: 66$",
        "ask_name": "اكتب اسمك الكامل (الأول + الأخير):",
        "ask_email": "ادخل إيميلك الصحيح (إجباري):",
        "invalid_email": "الإيميل غير صحيح! أعد إرساله (مثال: name@example.com)",
        "choose_coin": "اختر العملة التي تريد الدفع بها:",
        "choose_network": "اختر الشبكة لـ {coin}:",
        "pay_now": "اضغط الزر تحت للدفع الآن:",
        "success": "تم التفعيل بنجاح!\n\nرقم العضوية: {code}\nالصلاحية: حتى {date}\n\n{links}\n\nرابط الدعوة الخاص بك:\nhttps://t.me/{botname}?start=ref{ref_id}",
        "admin_panel": "لوحة التحكم - الأدمن",
        "stats": "الإحصائيات:\nالكلي: {total}\nاليوم: {today}",
        "payment_created": "تم إنشاء الفاتورة بنجاح\n\nالعملة: {coin} {net}\nالمبلغ: {price}$\n\nادفع ثم اضغط تحديث",
        "checking": "جاري التحقق من الدفع..."
    }
}

def t(key, **kwargs):
    return TEXT["ar"][key].format(**kwargs)

# === البداية ===
@bot.message_handler(commands=['start'])
def start(m):
    uid = str(m.chat.id)
    args = m.text.split()

    # نظام الإحالة
    if len(args) > 1 and args[1].startswith("ref"):
        ref_id = args[1][3:]
        if ref_id.isdigit() and ref_id != uid.lstrip('-'):
            db["referrals"][uid] = ref_id
            save_db()

    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(
        InlineKeyboardButton("VIP فقط - 16$", callback_data="plan_vip_only"),
        InlineKeyboardButton("مساعد ذكي فقط - 76$", callback_data="plan_ai_only"),
        InlineKeyboardButton("الكل مع بعض - 66$", callback_data="plan_both")
    )
    if uid in db["members"]:
        markup.add(InlineKeyboardButton("تجديد بخصم", callback_data="renew"))
    if int(uid) == OWNER_ID:
        markup.add(InlineKeyboardButton("لوحة التحكم", callback_data="admin"))

    bot.send_message(m.chat.id, t("welcome"), reply_markup=markup)

# === اختيار الباقة أو لوحة الأدمن ===
@bot.callback_query_handler(func=lambda c: c.data in ["plan_vip_only", "plan_ai_only", "plan_both", "renew", "admin"])
def plan_selected(c):
    uid = str(c.message.chat.id)
    bot.answer_callback_query(c.id)

    if c.data == "admin":
        if int(uid) != OWNER_ID:
            bot.answer_callback_query(c.id, "غير مصرح لك!", show_alert=True)
            return
        total = len(db["members"])
        today = sum(1 for v in db["members"].values() if datetime.strptime(v["expiry"], "%Y-%m-%d") >= datetime.now())
        bot.edit_message_text(
            chat_id=c.message.chat.id,
            message_id=c.message.message_id,
            text=t("stats", total=total, today=today),
            reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("رجوع", callback_data="back_to_start"))
        )
        return

    if c.data == "back_to_start":
        start(c.message)
        return

    if c.data == "renew":
        if uid not in db["members"]:
            bot.answer_callback_query(c.id, "ليس لديك عضوية حالية!", show_alert=True)
            return
        plan = db["members"][uid]["plan"]
        renew = True
    else:
        plan = c.data.replace("plan_", "")
        renew = False

    db["users"][uid] = {"step": "name", "plan": plan, "renew": renew}
    save_db()
    bot.edit_message_text(chat_id=c.message.chat.id, message_id=c.message.message_id, text=t(plan))
    bot.send_message(c.message.chat.id, t("ask_name"))

# === الخطوات ===
@bot.message_handler(func=lambda m: str(m.chat.id) in db["users"] and db["users"][str(m.chat.id)]["step"] == "name")
def get_name(m):
    uid = str(m.chat.id)
    if len(m.text.strip().split()) < 2:
        bot.reply_to(m, "اكتب اسمك الكامل (مثل: أحمد محمد)")
        return
    db["users"][uid]["name"] = m.text.strip()
    db["users"][uid]["step"] = "email"
    save_db()
    bot.reply_to(m, t("ask_email"))

def is_valid_email(email):
    return re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email.strip())

@bot.message_handler(func=lambda m: str(m.chat.id) in db["users"] and db["users"][str(m.chat.id)]["step"] == "email")
def get_email(m):
    uid = str(m.chat.id)
    if not is_valid_email(m.text):
        bot.reply_to(m, t("invalid_email"))
        return
    db["users"][uid]["email"] = m.text.strip()
    db["users"][uid]["step"] = "choose_coin"
    save_db()

    markup = InlineKeyboardMarkup(row_width=2)
    for coin in SUPPORTED_COINS.keys():
        markup.add(InlineKeyboardButton(coin, callback_data=f"coin_{coin}"))
    bot.send_message(uid, t("choose_coin"), reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data.startswith("coin_"))
def coin_selected(c):
    uid = str(c.message.chat.id)
    coin = c.data.split("_")[1]
    db["users"][uid]["coin"] = coin
    db["users"][uid]["step"] = "choose_network"
    save_db()

    networks = SUPPORTED_COINS[coin]["networks"]
    markup = InlineKeyboardMarkup(row_width=1)
    for code, name in networks.items():
        markup.add(InlineKeyboardButton(name, callback_data=f"net_{coin}_{code}"))
    bot.edit_message_text(
        chat_id=c.message.chat.id,
        message_id=c.message.message_id,
        text=t("choose_network", coin=SUPPORTED_COINS[coin]["name"]),
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda c: c.data.startswith("net_"))
def network_selected(c):
    uid = str(c.message.chat.id)
    parts = c.data.split("_", 2)
    if len(parts) != 3:
        bot.answer_callback_query(c.id, "خطأ", show_alert=True)
        return
    _, coin, network = parts
    network = network.lower()
    bot.answer_callback_query(c.id, f"تم اختيار {coin} - {network.upper()}")

    pay_currency = PAY_CURRENCY_MAPPING.get(coin, {}).get(network)
    if not pay_currency:
        pay_currency = coin.lower()
        if coin == "BNB": pay_currency = "bnb.bsc"
        if coin == "AVAX": pay_currency = "avaxc"

    db["users"][uid]["network"] = network
    save_db()

    bot.edit_message_text(chat_id=c.message.chat.id, message_id=c.message.message_id, text="جاري إنشاء الفاتورة...")
    create_payment(uid, pay_currency, network)

# === إنشاء الفاتورة ===
def create_payment(uid, pay_currency, network=None):
    user = db["users"].get(uid)
    if not user:
        bot.send_message(uid, "حدث خطأ، ابدأ من جديد /start")
        return

    plan = user["plan"]
    price = RENEW_PRICES[plan] if user.get("renew") else PRICES[plan]
    order_id = f"{uid}_{int(time.time())}_{random.randint(1000,9999)}"

    payload = {
        "price_amount": price,
        "price_currency": "usd",
        "pay_currency": pay_currency,
        "order_id": order_id,
        "order_description": f"ORORA.UN - {plan.upper()} - {price}$",
        "success_url": f"https://t.me/{bot.get_me().username}",
    }

    # فقط للعملات المسموحة
    if pay_currency.lower() in FIXED_RATE_ALLOWED:
        payload["fixed_rate"] = True

    if WEBHOOK_BASE:
        payload["ipn_callback_url"] = f"{WEBHOOK_BASE.rstrip('/')}/webhook"

    headers = {"x-api-key": NOWPAYMENTS_KEY, "Content-Type": "application/json"}
    try:
        r = requests.post("https://api.nowpayments.io/v1/invoice", json=payload, headers=headers, timeout=20)
        data = r.json()
        print(f"[NOWPayments] {r.status_code} - {data}")
    except Exception as e:
        bot.send_message(uid, "خطأ في بوابة الدفع، حاول لاحقًا")
        return

    if r.status_code not in (200, 201):
        msg = data.get("message", "فشل إنشاء الفاتورة")
        bot.send_message(uid, f"خطأ: {msg}")
        return

    invoice_url = data.get("invoice_url")
    invoice_id = str(data.get("invoice_id"))

    if not invoice_url or not invoice_id:
        bot.send_message(uid, "فشل في إنشاء رابط الدفع")
        return

    db["pending"][invoice_id] = {
        "user_id": uid,
        "plan": plan,
        "price": price,
        "pay_currency": pay_currency,
        "network": network.upper() if network else None
    }
    save_db()

    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("ادفع الآن", url=invoic_url))
    markup.add(InlineKeyboardButton("تحديث حالة الدفع", callback_data=f"check_{invoice_id}"))

    net = f"({network.upper()})" if network else ""
    bot.send_message(uid, t("payment_created", coin=pay_currency.upper(), net=net, price=price), reply_markup=markup)

# === تحديث حالة الدفع ===
@bot.callback_query_handler(func=lambda c: c.data.startswith("check_"))
def check_payment_status(c):
    bot.answer_callback_query(c.id)
    invoice_id = c.data.split("_", 1)[1]

    if invoice_id not in db["pending"]:
        bot.send_message(c.message.chat.id, "تم تفعيل العضوية مسبقًا أو الفاتورة منتهية")
        return

    try:
        r = requests.get(f"https://api.nowpayments.io/v1/invoice/{invoice_id}", headers={"x-api-key": NOWPAYMENTS_KEY})
        status = r.json().get("payment_status", "waiting")
    except:
        status = "waiting"

    if status in ["paid", "finished", "confirmed"]:
        info = db["pending"].pop(invoice_id)
        save_db()
        activate_user(info["user_id"], info["plan"])
        bot.send_message(c.message.chat.id, "تم الدفع بنجاح! تم تفعيل عضويتك بنجاح")
    else:
        bot.send_message(c.message.chat.id, f"الدفع ما زال قيد الانتظار...\nالحالة: {status}\n\nاضغط تحديث مرة أخرى بعد دقيقة")

# === تفعيل العضوية ===
def activate_user(uid, plan):
    uid = str(uid)
    code = "VIP-" + ''.join(random.choices("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", k=8))
    expiry = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
    db["members"][uid] = {"code": code, "plan": plan, "expiry": expiry}
    db["stats"]["total"] = db["stats"].get("total", 0) + 1
    save_db()

    links = ""
    if "vip" in plan or plan == "both":
        links += f"قناة VIP:\n{CHANNELS['vip']}\n\n"
    if "ai" in plan or plan == "both":
        links += f"المساعد الذكي:\n{CHANNELS['ai']}\n"

    clean_uid = uid.replace('-', '')[-8:] if uid.startswith('-') else uid[-8:]
    ref_id = db["referrals"].get(uid, clean_uid)
    botname = bot.get_me().username

    bot.send_message(int(uid), t("success").format(
        code=code, date=expiry, links=links, botname=botname, ref_id=ref_id
    ))

# === Webhook ===
@app.route("/webhook", methods=["POST"])
def webhook():
    signature = request.headers.get("x-nowpayments-signature")
    if not signature:
        abort(400)

    data = request.get_data()
    expected = hmac.new(IPN_SECRET.encode(), data, hashlib.sha512).hexdigest()
    if not hmac.compare_digest(signature, expected):
        abort(400)

    payload = request.get_json(force=True)
    invoice_id = str(payload.get("invoice_id"))
    status = payload.get("payment_status")

    if status in ["finished", "confirmed", "paid"] and invoice_id in db["pending"]:
        info = db["pending"].pop(invoice_id)
        save_db()
        activate_user(info["user_id"], info["plan"])

    return "OK", 200

# === التشغيل ===
if __name__ == "__main__":
    import threading
    port = int(os.getenv("PORT", 8080))
    threading.Thread(target=app.run, kwargs={"host": "0.0.0.0", "port": port}, daemon=True).start()
    print("ORORA.UN Bot يعمل الآن بنجاح 100% - نوفمبر 2025")
    bot.infinity_polling(none_stop=True)
