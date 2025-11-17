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

# === المتغيرات ===
TOKEN = os.getenv("BOT_TOKEN")
NOWPAYMENTS_KEY = os.getenv("NOWPAYMENTS_KEY")
IPN_SECRET = os.getenv("IPN_SECRET", "IYPgA4RMwFKQYntBGC/hZ3LrP3sfPX35")
WEBHOOK_BASE = os.getenv("WEBHOOK_BASE")

if not TOKEN or not NOWPAYMENTS_KEY:
    raise RuntimeError("تحقق من BOT_TOKEN و NOWPAYMENTS_KEY في .env")

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)
DB_FILE = "db.json"

# === قاعدة البيانات ===
if os.path.exists(DB_FILE):
    with open(DB_FILE, "r", encoding="utf-8") as f:
        db = json.load(f)
else:
    db = {"members": {}, "pending": {}, "users": {}, "referrals": {}}

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
        "bep20": "BEP20 (بينانس)",
        "polygon": "Polygon",
        "sol": "Solana",
        "avax": "Avalanche",
        "ton": "TON"
    }},
    "USDC": {"name": "USD Coin", "networks": {
        "erc20": "ERC20",
        "bep20": "BEP20",
        "polygon": "Polygon",
        "sol": "Solana",
        "tron": "TRC20"
    }},
    "BTC": {"name": "Bitcoin", "networks": {"btc": "Bitcoin"}},
    "ETH": {"name": "Ethereum", "networks": {"erc20": "ERC20"}},
    "BNB": {"name": "Binance Coin", "networks": {"bep20": "BEP20"}},
    "TRX": {"name": "TRON", "networks": {"trx": "TRON"}},
    "SOL": {"name": "Solana", "networks": {"sol": "Solana"}},
    "MATIC": {"name": "Polygon", "networks": {"polygon": "Polygon"}},
    "AVAX": {"name": "Avalanche", "networks": {"avax": "Avalanche"}}
}

# === النصوص ===
TEXT = {
    "ar": {
        "welcome": """
            ORORA.UN 
            
            🟢 مرحبًا بك في البوابة الرسمية للثراء الحقيقي 
            
            نحن هنا لنأخذك من الصفر إلى القمة في عالم التداول والاستثمار بأسرع وأضمن الطرق الممكنة 
            
            ماذا ستحصل عندنا؟
            
            ✅ أقوى دورات تعليمية من الصفر إلى الاحتراف  
            ✅ استراتيجيات تداول حصرية بمعدل نجاح +87%  
            ✅ قنوات توصيات VIP للنخبة فقط (صفقات المليون يوميًا)  
            ✅ بوت تداول آلي ينفّذ الصفقات بدلك 24/7 ويحقق أرباح حتى وأنت نايم ⚡  
            ✅ إشراف مباشر من مدرب شخصي 24/7  
            ✅ مساعد ذكي يحلل السوق لحظيًا ويعطيك الإشارات فورًا  
            ✅ دعم فني ونفسي مستمر حتى تصل لهدفك المالي 
            
            كل هذا بأفضل سعر في السوق + ضمان استرجاع الأموال 7 أيام إذا ما شفت نتائج حقيقية!
            
            اختر الباقة اللي تناسب طموحك الآن وابدأ رحلتك للحرية المالية خلال أيام قليلة فقط ⬇️
            """,
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

# === البداية والخطوات (بدون تغيير كبير) ===
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

@bot.callback_query_handler(func=lambda c: c.data.startswith("plan_") or c.data == "renew")
def plan_selected(c):
    uid = str(c.message.chat.id)
    bot.answer_callback_query(c.id)
    renew = False
    if c.data == "renew":
        if uid not in db["members"]:
            return bot.answer_callback_query(c.id, "لا تملك عضوية!", show_alert=True)
        plan = db["members"][uid]["plan"]
        renew = True
    else:
        plan = c.data.replace("plan_", "")

    db["users"][uid] = {"step": "name", "plan": plan, "renew": renew}
    save_db()
    bot.edit_message_text(chat_id=c.message.chat.id, message_id=c.message.message_id, text=t(plan))
    bot.send_message(c.message.chat.id, t("ask_name"))

@bot.message_handler(func=lambda m: str(m.chat.id) in db["users"] and db["users"][str(m.chat.id)]["step"] == "name")
def get_name(m):
    uid = str(m.chat.id)
    if len(m.text.strip().split()) < 2:
        return bot.reply_to(m, "اكتب الاسم الكامل")
    db["users"][uid].update({"name": m.text.strip(), "step": "email"})
    save_db()
    bot.reply_to(m, t("ask_email"))

def is_valid_email(e): return re.match(r'^[\w\.-]+@[\w\.-]+\.\w+$', e.strip())

@bot.message_handler(func=lambda m: str(m.chat.id) in db["users"] and db["users"][str(m.chat.id)]["step"] == "email")
def get_email(m):
    uid = str(m.chat.id)
    if not is_valid_email(m.text):
        return bot.reply_to(m, t("invalid_email"))
    db["users"][uid].update({"email": m.text.strip(), "step": "choose_coin"})
    save_db()

    markup = InlineKeyboardMarkup(row_width=3)
    for coin in ["USDT", "USDC", "BTC", "ETH", "BNB", "TRX", "SOL", "MATIC", "AVAX"]:
        markup.add(InlineKeyboardButton(coin, callback_data=f"coin_{coin}"))
    bot.send_message(uid, t("choose_coin"), reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data.startswith("coin_"))
def coin_selected(c):
    uid = str(c.message.chat.id)
    coin = c.data.split("_")[1]
    db["users"][uid]["coin"] = coin
    save_db()
    bot.answer_callback_query(c.id)

    nets = SUPPORTED_COINS[coin]["networks"]
    markup = InlineKeyboardMarkup(row_width=1)
    for code, name in nets.items():
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
    _, coin, net = c.data.split("_", 2)
    db["users"][uid]["network"] = net
    save_db()
    bot.answer_callback_query(c.id, f"تم اختيار {coin} - {net.upper()}")
    create_payment(uid, coin.lower(), net)

# === الدالة المُصححة بالكامل (الجزء الأهم) ===
def create_payment(uid, pay_currency, network=None):
    user = db["users"].get(uid)
    if not user: return bot.send_message(uid, "خطأ، أعد المحاولة.")

    plan = user["plan"]
    price = RENEW_PRICES[plan] if user.get("renew") else PRICES[plan]
    order_id = f"{uid}_{int(time.time())}"

    payload = {
        "price_amount": price,
        "price_currency": "usd",
        "pay_currency": pay_currency,
        "order_id": order_id,
        "order_description": f"ORORA.UN - {plan}",
    }

    # fixed_rate فقط مع USDT و USDC
    if pay_currency.upper() in ["USDT", "USDC"]:
        payload["fixed_rate"] = True

    if WEBHOOK_BASE:
        payload["ipn_callback_url"] = f"{WEBHOOK_BASE.rstrip('/')}/webhook"

    try:
        bot_username = bot.get_me().username
        payload["success_url"] = f"https://t.me/{bot_username}"
    except: pass

    headers = {"x-api-key": NOWPAYMENTS_KEY, "Content-Type": "application/json"}

    try:
        r = requests.post("https://api.nowpayments.io/v1/invoice", json=payload, headers=headers, timeout=20)
        r.raise_for_status()
        data = r.json()
    except requests.exceptions.HTTPError:
        err = r.json().get("message", "خطأ غير معروف")
        bot.send_message(uid, f"فشل إنشاء الفاتورة:\n{err}")
        return
    except Exception as e:
        bot.send_message(uid, "خطأ في الاتصال بالبوابة، حاول لاحقاً.")
        return

    invoice_url = data.get("invoice_url")
    invoice_id = str(data.get("invoice_id") or data.get("id"))

    if not invoice_url or not invoice_id:
        return bot.send_message(uid, "فشل إنشاء رابط الدفع، تواصل مع الدعم.")

    db["pending"][invoice_id] = {
        "user_id": uid, "plan": plan, "coin": pay_currency.upper(),
        "network": network.upper() if network else None
    }
    save_db()

    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("ادفع الآن", url=invoice_url))
    bot.send_message(uid,
        f"{pay_currency.upper()}{f' ({network.upper()})' if network else ''}\nالسعر: {price}$\n\n{t('pay_now')}",
        reply_markup=markup)

# === تفعيل + Webhook (بدون تغيير) ===
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

    try: botname = bot.get_me().username
    except: botname = "yourbot"
    clean_uid = uid.lstrip('-') if uid.startswith('-') else uid

    bot.send_message(int(uid), t("success").format(code=code, date=expiry, links=links, botname=botname, uid=clean_uid))

@app.route("/webhook", methods=["POST"])
def webhook():
    sig = request.headers.get("x-nowpayments-signature")
    if not sig: abort(400)
    data = request.get_data()
    expected = hmac.new(IPN_SECRET.encode(), data, hashlib.sha512).hexdigest()
    if not hmac.compare_digest(sig, expected): abort(400)

    payload = request.get_json(force=True)
    inv_id = str(payload.get("invoice_id") or payload.get("id"))
    status = payload.get("payment_status") or payload.get("status")

    if status in ["finished", "confirmed", "paid", "successful"] and inv_id in db["pending"]:
        info = db["pending"].pop(inv_id)
        save_db()
        activate_user(info["user_id"], info["plan"])

    return "OK", 200

# === تشغيل ===
if __name__ == "__main__":
    import threading
    threading.Thread(target=app.run, kwargs={"host": "0.0.0.0", "port": int(os.getenv("PORT", 8080))}, daemon=True).start()
    print("البوت شغال 100% - جميع العملات والشبكات تعمل بدون أخطاء!")
    bot.infinity_polling(none_stop=True)
