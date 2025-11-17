import telebot
import random
import string
import json
import os
import requests
from datetime import datetime, timedelta
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import threading
import time

# ===================== التوكن الجديد =====================
TOKEN = "8537451145:AAG-ZgzkCPh1rUsWCAzZ726Y_maPx7aSq_4"
OWNER_ID = 123456789  # غيّر هذا بـ ID بتاعك الرقمي

# NOWPayments API Key (سجل في https://nowpayments.io وخذ المفتاح)
NOWPAYMENTS_KEY = "A7K9F3M2N8P5Q1R6T9V4X0Z8B6C3D1E5F7G2H4J9K8L6M3N1P0Q5R8T2V7X4Z9B6C1D"

bot = telebot.TeleBot(TOKEN)
DB_FILE = "vip_final_db.json"

# قاعدة البيانات
if os.path.exists(DB_FILE):
    with open(DB_FILE, "r", encoding="utf-8") as f:
        db = json.load(f)
else:
    db = {"members": {}, "lang": {}, "referrals": {}, "pending": {}}

def save_db():
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=4)

# عناوينك
WALLETS = {
    "USDT_TRC20": "TN1DRFZ916prvTXTfZVwnrVcKBdbSNHQSe",
    "USDT_BEP20": "0x490b65f6c18c35c5c3f1fdc7999ecc5a9512dece",
    "USDT_ERC20": "0x490b65f6c18c35c5c3f1fdc7999ecc5a9512dece",
    "USDC_ERC20": "0x490b65f6c18c35c5c3f1fdc7999ecc5a9512dece",
    "BNB_BEP20": "0x490b65f6c18c35c5c3f1fdc7999ecc5a9512dece",
    "BTC_BEP20": "0x490b65f6c18c35c5c3f1fdc7999ecc5a9512dece",
    "ETH_BEP20": "0x490b65f6c18c35c5c3f1fdc7999ecc5a9512dece",
    "SOL_BEP20": "0x490b65f6c18c35c5c3f1fdc7999ecc5a9512dece"
}

PRICES = {"vip_only": 15, "ai_only": 75, "both": 65}
RENEW_PRICES = {"vip_only": 10, "ai_only": 65, "both": 55}

CHANNELS = {
    "vip": "https://t.me/+YOUR_VIP_CHANNEL",
    "ai": "https://t.me/+YOUR_AI_CHANNEL"
}

# النصوص
TEXT = {
    "ar": {
        "choose_lang": "اختر لغتك",
        "welcome": "مرحبًا بك في بوت الاشتراك VIP الأقوى!\nاختر باقتك:",
        "vip_only": "قناة التوصيات VIP فقط - 15$/شهر",
        "ai_only": "مساعد ذكي تعليمي فقط - 75$/شهر",
        "both": "التوصيات + المساعد الذكي - 65$/شهر",
        "renew": "تجديد الاشتراك (خصم خاص)",
        "activated": "تم تفعيل اشتراكك بنجاح!",
        "referral": "شارك رابطك وحصل على 7 أيام مجانًا لكل عضو:\n"
    },
    "en": {
        "choose_lang": "Choose your language",
        "welcome": "Welcome to the strongest VIP bot!\nChoose your plan:",
        "vip_only": "VIP Signals Only - 15$/month",
        "ai_only": "AI Assistant Only - 75$/month",
        "both": "Signals + AI Assistant - 65$/month",
        "renew": "Renew (Discount)",
        "activated": "Subscription activated successfully!",
        "referral": "Share your link & get 7 free days per referral:\n"
    }
}

def t(uid, key):
    return TEXT[db["lang"].get(str(uid), "ar")][key]

# /start
@bot.message_handler(commands=['start'])
def start(message):
    user_id = message.chat.id
    args = message.text.split()
    if len(args) > 1 and args[1].startswith("ref"):
        db["referrals"][str(user_id)] = args[1][3:]

    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton("العربية", callback_data="lang_ar"),
        InlineKeyboardButton("English", callback_data="lang_en")
    )
    bot.send_message(user_id, "اختر لغتك / Choose language", reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data in ["lang_ar", "lang_en"])
def lang_set(call):
    db["lang"][str(call.message.chat.id)] = call.data.split("_")[1]
    save_db()
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(
        InlineKeyboardButton(t(call.message.chat.id, "vip_only"), callback_data="plan_vip_only"),
        InlineKeyboardButton(t(call.message.chat.id, "ai_only"), callback_data="plan_ai_only"),
        InlineKeyboardButton(t(call.message.chat.id, "both"), callback_data="plan_both"),
        InlineKeyboardButton(t(call.message.chat.id, "renew"), callback_data="renew")
    )
    bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id,
                          text=t(call.message.chat.id, "welcome"), reply_markup=markup)

# إنشاء فاتورة
def create_payment(user_id, plan, renew=False):
    price = RENEW_PRICES.get(plan, PRICES[plan]) if renew else PRICES[plan]
    payload = {
        "price_amount": price,
        "price_currency": "usd",
        "pay_currency": "usdttrc20",
        "order_id": f"{user_id}_{int(time.time())}",
        "order_description": f"VIP {plan}",
        "success_url": f"https://t.me/{bot.get_me().username}"
    }
    try:
        r = requests.post("https://api.nowpayments.io/v1/invoice", json=payload,
                          headers={"x-api-key": NOWPAYMENTS_KEY})
        inv = r.json()
        url = inv["invoice_url"]
        inv_id = inv["id"]
        db["pending"][inv_id] = {"user_id": user_id, "plan": plan}
        save_db()

        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("ادفع الآن / Pay Now", url=url))
        bot.send_message(user_id, f"المبلغ: {price} USD\nاضغط للدفع الفوري:", reply_markup=markup)
    except:
        bot.send_message(user_id, "خطأ مؤقت، جرب لاحقًا")

@bot.callback_query_handler(func=lambda c: c.data.startswith("plan_") or c.data == "renew")
def plan_handler(call):
    plan = call.data.replace("plan_", "") if not call.data == "renew" else db["members"].get(str(call.message.chat.id), {}).get("plan")
    create_payment(call.message.chat.id, plan, call.data == "renew")

# تفعيل تلقائي
def check_payments():
    while True:
        for inv_id, data in list(db["pending"].items()):
            try:
                r = requests.get(f"https://api.nowpayments.io/v1/invoice/{inv_id}",
                                 headers={"x-api-key": NOWPAYMENTS_KEY})
                if r.json().get("invoice_status") == "paid":
                    activate(data["user_id"], data["plan"])
                    del db["pending"][inv_id]
                    save_db()
            except:
                pass
        time.sleep(15)

def activate(user_id, plan):
    membership = "VIP-" + ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
    expiry = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
    db["members"][str(user_id)] = {"membership": membership, "plan": plan, "expiry": expiry}
    save_db()

    # رفرال
    ref = db["referrals"].get(str(user_id))
    if ref and ref in db["members"]:
        old = datetime.strptime(db["members"][ref]["expiry"], "%Y-%m-%d")
        db["members"][ref]["expiry"] = (old + timedelta(days=7)).strftime("%Y-%m-%d")
        bot.send_message(int(ref), "حصلت على 7 أيام مجانًا بسبب رفرال جديد!")

    links = f"VIP: {CHANNELS['vip']}\n" if "vip" in plan or plan == "both" else ""
    links += f"AI: {CHANNELS['ai']}" if "ai" in plan or plan == "both" else ""

    bot.send_message(user_id, f"""
{t(user_id, "activated")}

رقم العضوية: `{membership}`
صلاحية حتى: {expiry}

{links}

{t(user_id, "referral")}t.me/{bot.get_me().username}?start=ref{user_id}
    """, parse_mode="Markdown")

# تشغيل الفحص
threading.Thread(target=check_payments, daemon=True).start()

print("البوت شغال الآن بالتوكن الجديد + دفع تلقائي + رفرال + لغتين!")
bot.infinity_polling()