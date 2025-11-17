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
OWNER_ID = int(os.getenv("OWNER_ID", "0") or 0)
NOWPAYMENTS_KEY = os.getenv("NOWPAYMENTS_KEY")
IPN_SECRET = os.getenv("IPN_SECRET", "IYPgA4RMwFKQYntBGC/hZ3LrP3sfPX35")
WEBHOOK_BASE = os.getenv("WEBHOOK_BASE")

if not TOKEN:
    raise RuntimeError("BOT_TOKEN غير معرّف في .env")
if not NOWPAYMENTS_KEY:
    raise RuntimeError("NOWPAYMENTS_KEY غير معرّف في .env")

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
CHANNELS = {"vip": os.getenv("VIP_CHANNEL", "t.me/your_vip_channel"), "ai": os.getenv("AI_CHANNEL", "t.me/your_ai_channel")}

# === العملات والشبكات المدعومة (عرض للمستخدم) ===
SUPPORTED_COINS = {
    "USDT": {
        "name": "Tether USDT",
        "networks": {
            "trc20": "TRC20 (ترون - الأرخص والأسرع)",
            "erc20": "ERC20 (إيثيريوم)",
            "bep20": "BEP20 (BSC)",
            "polygon": "Polygon",
            "sol": "Solana",
            "avax": "Avalanche C-Chain",
            "ton": "TON Network"
        }
    },
    "USDC": {
        "name": "USD Coin",
        "networks": {
            "erc20": "ERC20 (إيثيريوم)",
            "bep20": "BEP20 (BSC)",
            "polygon": "Polygon",
            "sol": "Solana",
            "trc20": "TRC20 (Tron)"
        }
    },
    "BTC": {"name": "Bitcoin", "networks": {"btc": "Bitcoin Network"}},
    "ETH": {"name": "Ethereum", "networks": {"erc20": "ERC20"}},
    "BNB": {"name": "Binance Coin", "networks": {"bep20": "BEP20 (BSC)"}},
    "TRX": {"name": "TRON", "networks": {"trx": "TRON Network"}},
    "SOL": {"name": "Solana", "networks": {"sol": "Solana"}},
    "MATIC": {"name": "Polygon", "networks": {"polygon": "Polygon"}},
    "AVAX": {"name": "Avalanche", "networks": {"avax": "Avalanche C-Chain"}}
}

# === خريطة تحويل (عملة + شبكة) -> رمز NOWPayments الصحيح ===
# هذه الخرائط تحوّل اختيار المستخدم إلى قيمة pay_currency التي يتوقعها NOWPayments
PAY_CURRENCY_MAPPING = {
    "USDT": {
        "trc20": "usdttrc20",
        "erc20": "usdteth",   # أحيانًا 'usdt' يقبلها أيضا؛ 'usdteth' أكثر تحديدًا
        "bep20": "usdtbsc",
        "polygon": "usdtpolygon",
        "sol": "usdtsol",
        "avax": "usdtavax",
        "ton": "usdton"
    },
    "USDC": {
        "trc20": "usdctrc20",
        "erc20": "usdceth",
        "bep20": "usdcbsc",
        "polygon": "usdcpolygon",
        "sol": "usdcsol"
    },
    # العملات الأخرى عادةً تستخدم اسم العملة نفسه
    "BTC": {"btc": "btc"},
    "ETH": {"erc20": "eth"},
    "BNB": {"bep20": "bnb"},
    "TRX": {"trx": "trx"},
    "SOL": {"sol": "sol"},
    "MATIC": {"polygon": "matic"},
    "AVAX": {"avax": "avax"}
}

# === النصوص ===
TEXT = {
    "ar": {
        "welcome": "ORORA.UN \n\nمرحبًا بك في البوابة الرسمية للثراء الحقيقي\nاختر الباقة التي تناسب طموحك ⬇️",
        "vip_only": "توصيات VIP فقط\n• أرباح يومية مضمونة\nالسعر: 16$",
        "ai_only": "المساعد الذكي فقط\nالسعر: 76$",
        "both": "الباقة الكاملة\n• VIP + المساعد الذكي\nالسعر: 66$",
        "ask_name": "اكتب اسمك الكامل (الأول + الأخير):",
        "ask_email": "ادخل إيميلك الصحيح (إجباري):",
        "invalid_email": "الإيميل غير صحيح! أعد إرساله بشكل صحيح (مثال: name@example.com)",
        "choose_coin": "اختر العملة التي تريد الدفع بها:",
        "choose_network": "اختر الشبكة المناسبة لـ {coin}:",
        "pay_now": "اضغط الزر تحت للدفع الآن:",
        "success": "تم التفعيل بنجاح!\n\nرقم العضوية: {code}\nالصلاحية: حتى {date}\n\n{links}\n\nرابط الدعوة الخاص بك:\nt.me/{botname}?start=ref{uid}"
    }
}

def t(key, **kwargs):
    return TEXT["ar"][key].format(**kwargs)

# === البداية ===
@bot.message_handler(commands=['start'])
def start(m):
    uid = str(m.chat.id)
    args = m.text.split()
    if len(args) > 1 and args[1].startswith("ref"):
        ref_id = args[1][3:]
        if ref_id.isdigit() and ref_id != uid:
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

    bot.edit_message_text(
        chat_id=c.message.chat.id,
        message_id=c.message.message_id,
        text=t(plan)
    )
    bot.send_message(c.message.chat.id, t("ask_name"))

# === الخطوات ===
@bot.message_handler(func=lambda m: str(m.chat.id) in db["users"] and db["users"][str(m.chat.id)]["step"] == "name")
def get_name(m):
    uid = str(m.chat.id)
    name = m.text.strip()
    if len(name.split()) < 2:
        bot.reply_to(m, "اكتب الاسم الكامل (اسم + كنية)")
        return
    db["users"][uid]["name"] = name
    db["users"][uid]["step"] = "email"
    save_db()
    bot.reply_to(m, t("ask_email"))

def is_valid_email(email):
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
    db["users"][uid]["step"] = "choose_coin"
    save_db()

    markup = InlineKeyboardMarkup(row_width=2)
    coins = list(SUPPORTED_COINS.keys())
    for coin in coins:
        markup.add(InlineKeyboardButton(f"{coin}", callback_data=f"coin_{coin}"))
    bot.send_message(uid, t("choose_coin"), reply_markup=markup)

# === اختيار العملة ===
@bot.callback_query_handler(func=lambda c: c.data.startswith("coin_"))
def coin_selected(c):
    uid = str(c.message.chat.id)
    coin = c.data.split("_")[1]
    bot.answer_callback_query(c.id)

    db["users"][uid]["coin"] = coin
    db["users"][uid]["step"] = "choose_network"
    save_db()

    # جلب الشبكات المتاحة للعرض
    networks = SUPPORTED_COINS.get(coin, {}).get("networks", {})
    markup = InlineKeyboardMarkup(row_width=1)
    for net_code, net_name in networks.items():
        # callback_data: net_<COIN>_<NETWORK_CODE>
        markup.add(InlineKeyboardButton(net_name, callback_data=f"net_{coin}_{net_code}"))

    bot.edit_message_text(
        chat_id=c.message.chat.id,
        message_id=c.message.message_id,
        text=t("choose_network", coin=SUPPORTED_COINS[coin]["name"]),
        reply_markup=markup
    )

# === اختيار الشبكة وإنشاء الفاتورة ===
@bot.callback_query_handler(func=lambda c: c.data.startswith("net_"))
def network_selected(c):
    uid = str(c.message.chat.id)
    parts = c.data.split("_", 2)
    if len(parts) != 3:
        bot.answer_callback_query(c.id, "اختيار غير صالح", show_alert=True)
        return

    _, coin, network = parts
    network = network.lower()
    bot.answer_callback_query(c.id, f"تم اختيار {coin} على شبكة {network.upper()}")

    db["users"][uid]["network"] = network
    save_db()

    # قم بتحويل (عملة + شبكة) إلى رمز NOWPayments
    mapped = None
    if coin in PAY_CURRENCY_MAPPING:
        mapped = PAY_CURRENCY_MAPPING[coin].get(network)
    # إذا لم يوجد mapping، استخدم coin.lower() كقيمة افتراضية
    pay_currency = mapped or coin.lower()

    # سجل لتصحيح الأخطاء
    print(f"[create_payment] uid={uid} coin={coin} network={network} -> pay_currency={pay_currency}")

    create_payment(uid, pay_currency, network)

# === إنشاء الفاتورة ===
def create_payment(uid, coin, network):
    user = db["users"].get(uid)
    if not user:
        bot.send_message(uid, "حدث خطأ. أعد المحاولة.")
        return

    plan = user["plan"]
    price = RENEW_PRICES[plan] if user.get("renew") else PRICES[plan]
    order_id = f"{uid}_{int(time.time())}"

    # تحديد pay_currency
    NETWORK_MAP = {
        "USDT": {
            "trc20": "usdttrc20",
            "erc20": "usdterc20",
            "bep20": "usdtbsc",
            "polygon": "usdtpolygon",
            "sol": "usdtsol",
            "avax": "usdtavax",
            "ton": "usdttn"
        },
        "USDC": {
            "trc20": "usdctrc20",
            "erc20": "usdcer20",
            "bep20": "usdcbsc",
            "polygon": "usdcpolygon",
            "sol": "usdcspl"
        }
    }

    if coin not in NETWORK_MAP or network not in NETWORK_MAP[coin]:
        bot.send_message(uid, "العملة أو الشبكة غير مدعومة.")
        return

    pay_currency = NETWORK_MAP[coin][network]

    # إنشاء طلب الدفع (مثال باستخدام API وهمي)
    payment_link = create_payment_link(amount=price, currency=pay_currency, order_id=order_id)

    bot.send_message(uid, f"لإتمام الدفع، استخدم الرابط التالي:\n{payment_link}")
    db["payments"][order_id] = {
        "uid": uid,
        "coin": coin,
        "network": network,
        "price": price,
        "status": "pending"
    }

    # العملات العادية بدون شبكات
    SIMPLE_COINS = ["BTC", "ETH", "BNB", "SOL", "TRX", "AVAX", "MATIC"]

    if coin.upper() in SIMPLE_COINS:
        pay_currency = coin.lower()

    else:
        # USDT / USDC
        try:
            pay_currency = NETWORK_MAP[coin.upper()][network]
        except:
            bot.send_message(uid, "هذه الشبكة غير مدعومة حالياً.")
            return

    # ===== بناء بيانات الفاتورة =====
    payload = {
        "price_amount": price,
        "price_currency": "usd",
        "pay_currency": pay_currency,
        "order_id": order_id,
        "order_description": f"ORORA.UN - {plan} - {pay_currency}",
    }

    # ===== URL Webhook =====
    if WEBHOOK_BASE:
        payload["ipn_callback_url"] = f"{WEBHOOK_BASE.rstrip('/')}/webhook"

    try:
        bot_username = bot.get_me().username
        payload["success_url"] = f"https://t.me/{bot_username}"
    except:
        pass

    headers = {"x-api-key": NOWPAYMENTS_KEY, "Content-Type": "application/json"}

    # ===== إرسال طلب إنشاء الفاتورة =====
    r = requests.post(
        "https://api.nowpayments.io/v1/invoice",
        json=payload,
        headers=headers,
        timeout=20
    )

    data = r.json()
    print("NOWPayments response:", r.status_code, data)

    if r.status_code not in (200, 201):
        msg = data.get("message", "خطأ غير معروف")
        bot.send_message(uid, f"فشل إنشاء الفاتورة: {msg}")
        return

    invoice_url = data.get("invoice_url")
    invoice_id = str(data.get("invoice_id") or data.get("id"))

    db["pending"][invoice_id] = {
        "user_id": uid,
        "plan": plan,
        "order_id": order_id,
        "coin": coin.upper(),
        "network": network.upper()
    }
    save_db()

    # زر الدفع
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("ادفع الآن", url=invoice_url))

    bot.send_message(
        uid,
        f"{coin.upper()} ({network.upper()})\nالسعر: {price}$\n\nاضغط أدناه للدفع:",
        reply_markup=markup
    )
# === تفعيل العضوية ===
def activate_user(uid, plan):
    uid = str(uid)
    code = "VIP-" + ''.join(random.choices("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", k=8))
    expiry = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
    db["members"][uid] = {"code": code, "plan": plan, "expiry": expiry}
    save_db()

    links = ""
    if "vip" in plan or plan == "both":
        links += f"قناة التوصيات VIP:\n{CHANNELS['vip']}\n\n"
    if "ai" in plan or plan == "both":
        links += f"المساعد الذكي:\n{CHANNELS['ai']}\n"

    try:
        botname = bot.get_me().username
    except:
        botname = "yourbot"

    clean_uid = uid.lstrip('-') if uid.startswith('-') else uid
    bot.send_message(int(uid), t("success").format(
        code=code, date=expiry, links=links, botname=botname, uid=clean_uid
    ))

# === Webhook ===
@app.route("/webhook", methods=["POST"])
def webhook():
    signature = request.headers.get("x-nowpayments-signature") or request.headers.get("X-NowPayments-Signature")
    if not signature:
        print("Webhook: no signature header present")
        abort(400)

    data = request.get_data()
    expected = hmac.new(IPN_SECRET.encode(), data, hashlib.sha512).hexdigest()
    if not hmac.compare_digest(signature, expected):
        print("Webhook: invalid signature", signature, expected)
        abort(400)

    payload = request.get_json(force=True)
    invoice_id = str(payload.get("invoice_id") or payload.get("id") or payload.get("invoiceId"))
    status = payload.get("payment_status") or payload.get("status")

    print("Webhook payload:", invoice_id, status)

    if status in ["finished", "confirmed", "paid", "successful"] and invoice_id in db["pending"]:
        info = db["pending"].pop(invoice_id)
        save_db()
        activate_user(info["user_id"], info["plan"])

    return "OK", 200

# === التشغيل ===
if __name__ == "__main__":
    import threading
    port = int(os.getenv("PORT", 8080))
    threading.Thread(target=app.run, kwargs={"host": "0.0.0.0", "port": port}, daemon=True).start()
    print("البوت يعمل الآن مع دعم العملات والشبكات المختارة!")
    bot.infinity_polling(none_stop=True)
