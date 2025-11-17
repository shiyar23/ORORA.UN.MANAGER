import telebot
import requests
import json
import os
import time
import hmac
import hashlib
from datetime import datetime, timedelta
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv
from flask import Flask, request, abort

load_dotenv()

# === المتغيرات ===
TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID"))
NOWPAYMENTS_KEY = os.getenv("NOWPAYMENTS_KEY")
IPN_SECRET = os.getenv("IPN_SECRET", "IYPgA4RMwFKQYntBGC/hZ3LrP3sfPX35")  # تأكد أنك حاطط الـ Secret في .env

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

# === القنوات والأسعار ===
CHANNELS = {"vip": os.getenv("VIP_CHANNEL"), "ai": os.getenv("AI_CHANNEL")}
PRICES = {"vip_only": 16, "ai_only": 76, "both": 66}
RENEW_PRICES = {"vip_only": 10, "ai_only": 65, "both": 55}

# === النصوص (الإيميل أصبح إجباري) ===
TEXT = {
    "ar": {
        "welcome": "ORORA.UN \n\n🟢 مرحبًا بك في البوابة الرسمية للثراء الحقيقي ...\n\nاختر الباقة اللي تناسب طموحك الآن وابدأ رحلتك للحرية المالية خلال أيام قليلة فقط ⬇️",
        "vip_only": "📈 توصيات VIP فقط\n• أرباح يومية مضمونة\nالسعر: 16$",
        "ai_only": "🤖 المساعد الذكي فقط\nالسعر: 76$",
        "both": "💎 الباقة الكاملة\n• توصيات VIP + المساعد الذكي\nالسعر: 66$",
        "ask_name": "✍️ اكتب اسمك الكامل (الأول + الأخير):",
        "ask_email": "📧 ادخل إيميلك الصحيح (إجباري):",
        "invalid_email": "🚫 الإيميل غير صحيح! أعد إرساله بشكل صحيح (مثال: name@example.com)",
        "choose_coin": "💰 اختر العملة الدفع:",
        "pay_now": "💸 اضغط الزر تحت عشان تدفع الآن:",
        "success": "🎉 تم التفعيل بنجاح!\n\nرقم العضوية: {code}\nالصلاحية: حتى {date}\n\n{links}\n\nرابط الدعوة الخاص بك:\nt.me/{botname}?start=ref{uid}"
    }
}

def t(key): 
    return TEXT["ar"][key]

# === بداية الأوامر ===
@bot.message_handler(commands=['start'])
def start(m):
    uid = str(m.chat.id)
    args = m.text.split()

    # نظام الإحالة
    if len(args) > 1 and args[1].startswith("ref"):
        ref_id = args[1][3:]
        if ref_id.isdigit() and ref_id != uid:
            db["referrals"][uid] = ref_id
            save_db()

    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(
        InlineKeyboardButton("📈 VIP فقط - 16$", callback_data="plan_vip_only"),
        InlineKeyboardButton("🤖 مساعد ذكي فقط - 76$", callback_data="plan_ai_only"),
        InlineKeyboardButton("💎 الكل مع بعض - 66$", callback_data="plan_both")
    )

    if uid in db["members"]:
        markup.add(InlineKeyboardButton("🔄 تجديد بخصم", callback_data="renew"))

    bot.send_message(m.chat.id, t("welcome"), reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data.startswith("plan_") or c.data == "renew")
def plan_selected(c):
    uid = str(c.message.chat.id)
    bot.answer_callback_query(c.id)

    if c.data == "renew":
        if uid not in db["members"]:
            bot.answer_callback_query(c.id, "ليس لديك عضوية لتجديدها!", show_alert=True)
            return
        plan = db["members"][uid]["plan"]
        renew = True
    else:
        plan = c.data.replace("plan_", "")
        renew = False

    db["users"][uid] = {"step": "name", "plan": plan, "renew": renew}
    save_db()

    desc_map = {"vip_only": "vip_only", "ai_only": "ai_only", "both": "both"}
    bot.edit_message_text(
        chat_id=c.message.chat.id,
        message_id=c.message.message_id,
        text=t(desc_map[plan])
    )
    bot.send_message(c.message.chat.id, t("ask_name"))

# === الخطوات ===
@bot.message_handler(func=lambda m: str(m.chat.id) in db["users"] and db["users"][str(m.chat.id)]["step"] == "name")
def get_name(m):
    uid = str(m.chat.id)
    name = m.text.strip()
    if len(name.split()) < 2:
        bot.reply_to(m, "🚫 اكتب الاسم الكامل (اسم + كنية)")
        return

    db["users"][uid]["name"] = name
    db["users"][uid]["step"] = "email"
    save_db()
    bot.reply_to(m, t("ask_email"))

# التحقق من صحة الإيميل
def is_valid_email(email):
    import re
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email.strip()) is not None

@bot.message_handler(func=lambda m: str(m.chat.id) in db["users"] and db["users"][str(m.chat.id)]["step"] == "email")
def get_email(m):
    uid = str(m.chat.id)
    email = m.text.strip()

    if not is_valid_email(email):
        bot.reply_to(m, t("invalid_email"))
        return

    db["users"][uid]["email"] = email
    db["users"][uid]["step"] = "coin"
    save_db()

    markup = InlineKeyboardMarkup(row_width=2)
    for coin in ["USDT", "BTC", "ETH", "BNB"]:
        markup.add(InlineKeyboardButton(coin, callback_data=f"coin_{coin}"))
    bot.reply_to(m, t("choose_coin"), reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data.startswith("coin_"))
def coin_selected(c):
    uid = str(c.message.chat.id)
    coin = c.data.split("_")[1]
    db["users"][uid]["coin"] = coin
    save_db()
    bot.answer_callback_query(c.id)

    create_payment(uid, coin.lower())

# === إنشاء الفاتورة ===
def create_payment(uid, pay_currency):
    user = db["users"][uid]
    plan = user["plan"]
    price = RENEW_PRICES[plan] if user.get("renew") else PRICES[plan]

    payload = {
        "price_amount": price,
        "price_currency": "usd",
        "pay_currency": pay_currency,
        "order_id": f"{uid}_{int(time.time())}",
        "order_description": f"ORORA.UN - {plan}",
        "ipn_callback_url": f"https://exemplary-optimism-production.up.railway.app/webhook",
        "success_url": f"https://t.me/{bot.get_me().username}"
    }

    headers = {"x-api-key": NOWPAYMENTS_KEY, "Content-Type": "application/json"}
    r = requests.post("https://api.nowpayments.io/v1/invoice", json=payload, headers=headers)

    if r.status_code != 200:
        bot.send_message(uid, "⚠️ حدث خطأ في إنشاء الفاتورة، جرب لاحقًا.")
        return

    data = r.json()
    if "invoice_url" not in data:
        bot.send_message(uid, f"خطأ: {data.get('message', 'Unknown error')}")
        return

    url = data["invoice_url"]
    inv_id = data["id"]

    db["pending"][str(inv_id)] = {"user_id": uid, "plan": plan}
    save_db()

    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("💸 ادفع الآن", url=url))
    bot.send_message(uid, t("pay_now"), reply_markup=markup)

# === تفعيل العضوية ===
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
        links += f"المساعد الذكي:\n{CHANNELS['ai']}\n"

    bot.send_message(int(uid), t("success").format(
        code=code, date=expiry, links=links,
        botname=bot.get_me().username, uid=uid.lstrip('-') if uid.startswith('-') else uid
    ))

# === الـ Webhook الصحيح 100% (HMAC-SHA512) ===
@app.route("/webhook", methods=["POST"])
def webhook():
    signature = request.headers.get("x-nowpayments-signature")
    data = request.get_data()

    expected_sig = hmac.new(
        IPN_SECRET.encode('utf-8'),
        data,
        hashlib.sha512
    ).hexdigest()

    if not hmac.compare_digest(signature, expected_sig):
        abort(400)

    payload = request.get_json(force=True)
    inv_id = str(payload.get("invoice_id"))
    status = payload.get("payment_status")

    if status in ["finished", "confirmed", "partially_paid"] and inv_id in db["pending"]:
        info = db["pending"][inv_id]
        activate_user(info["user_id"], info["plan"])
        db["pending"].pop(inv_id, None)
        save_db()

    return "OK", 200

# === تشغيل البوت ===
if __name__ == "__main__":
    import threading
    threading.Thread(target=app.run, kwargs={"host": "0.0.0.0", "port": int(os.getenv("PORT", 8080))}, daemon=True).start()
    print("البوت شغال 100% - التفعيل الآلي مفعل!")
    bot.infinity_polling(none_stop=True, interval=0)
