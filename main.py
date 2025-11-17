import telebot
import requests
import json
import os
import time
import threading
from datetime import datetime, timedelta
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID"))
NOWPAYMENTS_KEY = os.getenv("NOWPAYMENTS_KEY")

bot = telebot.TeleBot(TOKEN)
DB_FILE = "db.json"

if os.path.exists(DB_FILE):
    with open(DB_FILE, "r", encoding="utf-8") as f:
        db = json.load(f)
else:
    db = {"members": {}, "pending": {}, "users": {}, "referrals": {}}

def save_db():
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=4)

CHANNELS = {
    "vip": os.getenv("VIP_CHANNEL"),
    "ai": os.getenv("AI_CHANNEL")
}

PRICES = {"vip_only": 15, "ai_only": 75, "both": 65}
RENEW_PRICES = {"vip_only": 10, "ai_only": 65, "both": 55}

TEXT = {
    "ar": {
        "welcome": "🔥ORORA.UN مرحبًا بك في VIP في 2025!\nاختر الباقة اللي تناسبك:",
        "vip_only": "📈 توصيات VIP فقط\n• أرباح يومية مضمونة\n• دخول فوري للقناة الخاصة\nالسعر: 15$",
        "ai_only": "🤖 المساعد الذكي فقط\n• إجابات فورية 24/7\n• تحليل السوق + تعليم اقوة استراتجيات التداول + بوت تداول الآلي\nالسعر: 75$",
        "both": "💎 الباقة الكاملة (الأكثر طلبًا)\n• توصيات VIP + المساعد الذكي\n• خصم 25$ عن الشراء منفصل\nالسعر: 65$",
        "ask_name": "✍️ اكتب اسمك الكامل (الأول + الأخير):",
        "ask_email": "📧 ادخل إيميلك (جيميل أو أي إيميل):",
        "choose_coin": "💰 اختر العملة الدفع:",
        "choose_network": "🌐 اختر الشبكة:",
        "pay_now": "💸 اضغط الزر تحت عشان تدفع الآن:",
        "success": "🎉 تم التفعيل بنجاح!\n\nرقم العضوية: `{code}`\nالصلاحية: حتى {date}\n\n{links}\n\nرابط الدعوة الخاص بك (كل واحد يدفع = خصم لك):\nt.me/{botname}?start=ref{uid}",
        "renew_only": "🔄 تجديد الباقة (خصم خاص للأعضاء القدامى)"
    }
}

def t(uid, key):
    return TEXT["ar"][key]

# قائمة العملات والشبكات (تعدّلها زي ما تحب)
COINS = {
    "USDT": ["TRC20", "ERC20", "BEP20", "Polygon", "Arbitrum", "Optimism"],
    "BTC": ["Bitcoin"],
    "ETH": ["Ethereum"],
    "BNB": ["BEP20"],
    "SOL": ["Solana"],
    "TON": ["TON"],
    "TRX": ["TRON"],
    "DOGE": ["Dogecoin"],
    "LTC": ["Litecoin"]
}

@bot.message_handler(commands=['start'])
def start(m):
    uid = str(m.chat.id)
    args = m.text.split()
    if len(args) > 1 and args[1].startswith("ref"):
        db["referrals"][uid] = args[1][3:]
        save_db()

    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(
        InlineKeyboardButton("📈 توصيات VIP فقط - 15$", callback_data="plan_vip_only"),
        InlineKeyboardButton("🤖 مساعد ذكي فقط - 75$", callback_data="plan_ai_only"),
        InlineKeyboardButton("💎 الكل مع بعض - 65$", callback_data="plan_both")
    )

    # إظهار التجديد فقط للأعضاء اللي عندهم رفرال ناجح
    if uid in db["members"] and any(ref in db["members"] for ref in db.get("referrals", {}).values() if db["referrals"][ref] == uid):
        markup.add(InlineKeyboardButton("🔄 تجديد بخصم", callback_data="renew"))

    bot.send_message(m.chat.id, t(uid, "welcome"), reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data.startswith("plan_") or c.data == "renew")
def plan_selected(c):
    uid = str(c.message.chat.id)
    plan = c.data.replace("plan_", "") if "plan_" in c.data else db["members"][uid]["plan"]
    renew = c.data == "renew"

    db["users"][uid] = {"step": "ask_name", "plan": plan, "renew": renew}
    save_db()

    desc = "vip_only" if plan == "vip_only" else "ai_only" if plan == "ai_only" else "both"
    bot.edit_message_text(chat_id=c.message.chat.id, message_id=c.message.message_id, text=t(uid, desc))
    bot.send_message(c.message.chat.id, t(uid, "ask_name"))

# جمع البيانات خطوة بخطوة
@bot.message_handler(func=lambda m: str(m.chat.id) in db["users"] and db["users"][str(m.chat.id)]["step"] == "ask_name")
def get_name(m):
    uid = str(m.chat.id)
    db["users"][uid]["full_name"] = m.text
    db["users"][uid]["step"] = "ask_email"
    save_db()
    bot.send_message(m.chat.id, t(uid, "ask_email"))

@bot.message_handler(func=lambda m: str(m.chat.id) in db["users"] and db["users"][str(m.chat.id)]["step"] == "ask_email")
def get_email(m):
    uid = str(m.chat.id)
    db["users"][uid]["email"] = m.text
    db["users"][uid]["username"] = m.from_user.username or "لا يوجد"
    db["users"][uid]["step"] = "choose_coin"
    save_db()

    markup = InlineKeyboardMarkup(row_width=3)
    for coin in COINS:
        markup.add(InlineKeyboardButton(coin, callback_data=f"coin_{coin}"))
    bot.send_message(m.chat.id, t(uid, "choose_coin"), reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data.startswith("coin_"))
def coin_selected(c):
    uid = str(c.message.chat.id)
    coin = c.data.split("_")[1]
    db["users"][uid]["coin"] = coin

    markup = InlineKeyboardMarkup(row_width=2)
    for net in COINS[coin]:
        markup.add(InlineKeyboardButton(net, callback_data=f"net_{coin}_{net}"))

    bot.edit_message_text(chat_id=c.message.chat.id, message_id=c.message.message_id,
                          text=f"اخترت {coin}\nالآن اختر الشبكة:", reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data.startswith("net_"))
def net_selected(c):
    uid = str(c.message.chat.id)
    _, coin, network = c.data.split("_")
    db["users"][uid]["network"] = network
    save_db()

    create_payment(uid, coin.lower() + network.lower() if network != coin else coin.lower())

def create_payment(uid, pay_currency):
    user = db["users"][uid]
    price = RENEW_PRICES.get(user["plan"], PRICES[user["plan"]]) if user.get("renew") else PRICES[user["plan"]]

    payload = {
        "price_amount": price,
        "price_currency": "usd",
        "pay_currency": pay_currency,
        "order_id": f"{uid}_{int(time.time())}",
        "order_description": f"VIP {user['plan']} - {user['full_name']}",
        "customer_email": user["email"]
    }

    try:
        r = requests.post("https://api.nowpayments.io/v1/invoice", json=payload, headers={"x-api-key": NOWPAYMENTS_KEY})
        data = r.json()
        url = data["invoice_url"]
        inv_id = data["id"]

        db["pending"][inv_id] = {
            "user_id": uid,
            "plan": user["plan"],
            "name": user["full_name"],
            "email": user["email"],
            "username": user["username"]
        }
        save_db()

        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("💸 ادفع الآن", url=url))
        bot.send_message(uid, t(uid, "pay_now"), reply_markup=markup)

    except Exception as e:
        bot.send_message(uid, f"خطأ مؤقت: {str(e)}\nجرب تاني بعد دقيقة")

# فحص الدفعات كل 10 ثواني
def check_payments():
    while True:
        for inv_id, info in list(db["pending"].items()):
            try:
                r = requests.get(f"https://api.nowpayments.io/v1/invoice/{inv_id}", headers={"x-api-key": NOWPAYMENTS_KEY})
                status = r.json().get("invoice_status")
                if status == "paid":
                    activate_user(info["user_id"], info["plan"])
                    del db["pending"][inv_id]
                    save_db()
            except: pass
        time.sleep(10)

def activate_user(uid, plan):
    uid = str(uid)
    code = "VIP-" + ''.join(__import__('random').choices("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", k=8))
    expiry = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")

    db["members"][uid] = {"code": code, "plan": plan, "expiry": expiry}
    save_db()

    links = ""
    if "vip" in plan or plan == "both":
        links += f"قناة التوصيات:\n{CHANNELS['vip']}\n\n"
    if "ai" in plan or plan == "both":
        links += f"المساعد الذكي:\n{CHANNELS['ai']}"

    bot.send_message(int(uid), t(uid, "success").format(
        code=code, date=expiry, links=links,
        botname=bot.get_me().username, uid=uid
    ), parse_mode="Markdown")

threading.Thread(target=check_payments, daemon=True).start()
print("البوت الجديد شغال 100% - كل التعديلات مطبقة!")
bot.infinity_polling()
