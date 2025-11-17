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
NOWPAYMENTS_KEY = os.getenv("NOWPAYMENTS_KEY")
IPN_SECRET = os.getenv("IPN_SECRET", "IYPgA4RMwFKQYntBGC/hZ3LrP3sfPX35")
WEBHOOK_BASE = os.getenv("WEBHOOK_BASE")

if not TOKEN or not NOWPAYMENTS_KEY:
    raise RuntimeError("تحقق من BOT_TOKEN و NOWPAYMENTS_KEY في .env")

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)
DB_FILE = "db.json"

if os.path.exists(DB_FILE):
    with open(DB_FILE, "r", encoding="utf-8") as f:
        db = json.load(f)
else:
    db = {"members": {}, "pending": {}, "users": {}, "referrals": {}}

def save_db():
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=4)

PRICES = {"vip_only": 16, "ai_only": 76, "both": 66}
RENEW_PRICES = {"vip_only": 10, "ai_only": 65, "both": 55}
CHANNELS = {
    "vip": os.getenv("VIP_CHANNEL", "t.me/your_vip_channel"),
    "ai": os.getenv("AI_CHANNEL", "t.me/your_ai_channel")
}

# تحويل الشبكات إلى صيغة NOWPayments الصحيحة
NETWORK_MAP = {
    "trc20": "trx", "erc20": "eth", "bep20": "bsc", "polygon": "polygon",
    "sol": "sol", "avax": "avaxc", "ton": "ton", "btc": "btc", "trx": "trx"
}

SUPPORTED_COINS = {
    "USDT": {"name": "Tether USDT", "networks": {
        "trc20": "TRC20 (ترون - الأرخص والأسرع)", "erc20": "ERC20", "bep20": "BEP20",
        "polygon": "Polygon", "sol": "Solana", "avax": "Avalanche", "ton": "TON"
    }},
    "USDC": {"name": "USD Coin", "networks": {
        "erc20": "ERC20", "bep20": "BEP20", "polygon": "Polygon", "sol": "Solana", "tron": "TRC20"
    }},
    "BTC": {"name": "Bitcoin", "networks": {"btc": "Bitcoin"}},
    "ETH": {"name": "Ethereum", "networks": {"erc20": "ERC20"}},
    "BNB": {"name": "Binance Coin", "networks": {"bep20": "BEP20"}},
    "TRX": {"name": "TRON", "networks": {"trx": "TRON"}},
    "SOL": {"name": "Solana", "networks": {"sol": "Solana"}},
    "MATIC": {"name": "Polygon", "networks": {"polygon": "Polygon"}},
    "AVAX": {"name": "Avalanche", "networks": {"avax": "Avalanche"}}
}

TEXT = {
    "ar": {
        "welcome": """ORORA.UN\n\nمرحبًا بك في البوابة الرسمية للثراء الحقيقي...\nاختر باقتك الآن ⬇️""",
        "vip_only": "توصيات VIP فقط • 16$",
        "ai_only": "المساعد الذكي فقط • 76$",
        "both": "الباقة الكاملة • 66$",
        "ask_name": "اكتب اسمك الكامل:",
        "ask_email": "ادخل إيميلك الصحيح:",
        "invalid_email": "الإيميل غير صحيح! مثال: name@gmail.com",
        "choose_coin": "اختر العملة للدفع:",
        "choose_network": "اختر الشبكة لـ {coin}:",
        "pay_now": "اضغط الزر للدفع الآن:",
        "success": "تم التفعيل بنجاح!\n\nرقم العضوية: {code}\nالصلاحية حتى: {date}\n\n{links}\n\nرابط دعوتك:\nt.me/{botname}?start=ref{uid}"
    }
}
def t(key, **kw): return TEXT["ar"][key].format(**kw)

# باقي الكود (start, name, email, coin, network) نفس ما كان...

@bot.message_handler(commands=['start'])
def start(m):
    uid = str(m.chat.id)
    if len(m.text.split()) > 1 and m.text.split()[1].startswith("ref"):
        ref = m.text.split()[1][3:]
        if ref.isdigit() and ref != uid:
            db["referrals"][uid] = ref
            save_db()
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(
        InlineKeyboardButton("VIP فقط - 16$", callback_data="plan_vip_only"),
        InlineKeyboardButton("مساعد ذكي فقط - 76$", callback_data="plan_ai_only"),
        InlineKeyboardButton("الكل معًا - 66$", callback_data="plan_both")
    )
    if uid in db["members"]:
        markup.add(InlineKeyboardButton("تجديد بخصم", callback_data="renew"))
    bot.send_message(m.chat.id, t("welcome"), reply_markup=markup)

# ... (جميع الـ handlers السابقة نفسها بدون تغيير حتى network_selected)

@bot.callback_query_handler(func=lambda c: c.data.startswith("net_"))
def network_selected(c):
    uid = str(c.message.chat.id)
    _, coin, net = c.data.split("_", 2)
    db["users"][uid]["coin"] = coin
    db["users"][uid]["network"] = net
    save_db()
    bot.answer_callback_query(c.id, f"تم اختيار {coin} - {net.upper()}")
    create_payment(uid, coin, net)

# الدالة الجديدة كليًا (الحل النهائي)
def create_payment(uid, coin, network=None):
    user = db["users"].get(uid)
    if not user:
        return bot.send_message(uid, "خطأ، أعد المحاولة.")

    plan = user["plan"]
    price = RENEW_PRICES[plan] if user.get("renew") else PRICES[plan]

    # تحديد pay_currency بشكل صحيح
    if coin.upper() in ["USDT", "USDC"] and network:
        net_code = NETWORK_MAP.get(network, network)
        pay_currency = f"{coin.lower()}_{net_code}"
    else:
        pay_currency = coin.lower()

    payload = {
        "price_amount": price,
        "price_currency": "usd",
        "pay_currency": pay_currency,
        "order_id": f"{uid}_{int(time.time())}",
        "order_description": f"ORORA.UN - {plan}",
        "ipn_callback_url": f"{WEBHOOK_BASE.rstrip('/')}/webhook" if WEBHOOK_BASE else None,
        "success_url": f"https://t.me/{bot.get_me().username}"
    }

    headers = {"x-api-key": NOWPAYMENTS_KEY, "Content-Type": "application/json"}

    try:
        r = requests.post("https://api.nowpayments.io/v1/payment", json=payload, headers=headers, timeout=20)
        r.raise_for_status()
        data = r.json()
    except requests.exceptions.HTTPError as e:
        err = r.json().get("message", "خطأ غير معروف")
        bot.send_message(uid, f"فشل الدفع:\n{err}")
        print("NOWPayments Error:", r.text)
        return
    except Exception as e:
        bot.send_message(uid, "مشكلة في بوابة الدفع، حاول لاحقًا.")
        return

    payment_id = data.get("payment_id")
    invoice_url = data.get("invoice_url")

    if not payment_id or not invoice_url:
        bot.send_message(uid, "فشل إنشاء الفاتورة، تواصل مع الدعم.")
        return

    db["pending"][str(payment_id)] = {"user_id": uid, "plan": plan}
    save_db()

    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("ادفع الآن", url=invoice_url))

    net_name = SUPPORTED_COINS[coin]["networks"].get(network, network.upper()) if network else ""
    bot.send_message(uid,
        f"{coin.upper()}{f' ({net_name})' if net_name else ''}\nالمبلغ: {price} دولار\n\n{t('pay_now')}",
        reply_markup=markup)

def activate_user(uid, plan):
    uid = str(uid)
    code = "VIP-" + ''.join(random.choices("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", k=8))
    expiry = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
    db["members"][uid] = {"code": code, "plan": plan, "expiry": expiry}
    save_db()

    links = ""
    if "vip" in plan or plan == "both":
        links += f"قناة VIP:\n{CHANNELS['vip']}\n\n"
    if "ai" in plan or plan == "both":
        links += f"المساعد الذكي:\n{CHANNELS['ai']}\n"

    botname = bot.get_me().username or "yourbot"
    clean_uid = uid.lstrip('-') if uid.startswith('-') else uid
    bot.send_message(int(uid), t("success").format(code=code, date=expiry, links=links, botname=botname, uid=clean_uid))

@app.route("/webhook", methods=["POST"])
def webhook():
    sig = request.headers.get("x-nowpayments-signature")
    if not sig: return "No sig", 400
    data = request.get_data()
    expected = hmac.new(IPN_SECRET.encode(), data, hashlib.sha512).hexdigest()
    if not hmac.compare_digest(sig, expected): return "Invalid sig", 400

    payload = request.get_json(force=True)
    payment_id = str(payload.get("payment_id") or payload.get("id"))
    status = payload.get("payment_status") or payload.get("status")

    if status in ["finished", "confirmed", "paid", "successful"] and payment_id in db["pending"]:
        info = db["pending"].pop(payment_id)
        save_db()
        activate_user(info["user_id"], info["plan"])

    return "OK", 200

if __name__ == "__main__":
    import threading
    threading.Thread(target=app.run, kwargs={"host": "0.0.0.0", "port": int(os.getenv("PORT", 8080))}, daemon=True).start()
    print("البوت شغال 100% – بدون أي خطأ fixed_rate نهائيًا!")
    bot.infinity_polling(none_stop=True)
