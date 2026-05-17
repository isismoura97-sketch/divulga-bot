import os
import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters, CallbackQueryHandler
from telegram.constants import ParseMode
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

# CONEXÃO SUPABASE
supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))

# MENUS
MENU = ReplyKeyboardMarkup([[KeyboardButton("/planos"), KeyboardButton("/status")]], resize_keyboard=True)

# MARCADOR DE VERSÃO (PARA SABER O QUE ESTÁ RODANDO)
BOT_VERSION = "v2.0-PIX-SUPABASE"

# ==================== FUNÇÕES ====================
def get_plan_from_db(key):
    try:
        res = supabase.table("plan_payments").select("*").eq("chave_plano", key).eq("tem_pix", True).execute()
        return res.data[0] if res.data else None
    except Exception as e:
        logger.error(f"DB Error: {e}")
        return None

# ==================== COMANDOS ====================
async def start(u: Update, c: ContextTypes.DEFAULT_TYPE):
    await u.message.reply_text(f"🤖 *Bot Online*\n🔖 Versão: `{BOT_VERSION}`\nUse /planos para pagar.", parse_mode="Markdown", reply_markup=MENU)

async def planos(u: Update, c: ContextTypes.DEFAULT_TYPE):
    kb = [
        [InlineKeyboardButton("🟡 Semanal", callback_data="qr_semanal_5")],
        [InlineKeyboardButton("🔵 Iniciante", callback_data="qr_iniciante")],
        [InlineKeyboardButton("🔴 Pró", callback_data="qr_pró")]
    ]
    await u.message.reply_text("Escolha um plano:", reply_markup=InlineKeyboardMarkup(kb))

async def status(u: Update, c: ContextTypes.DEFAULT_TYPE):
    await u.message.reply_text(f"📊 Status\nVersão rodando: {BOT_VERSION}", reply_markup=MENU)

# ==================== CALLBACK PIX ====================
async def pay_handler(u: Update, c: ContextTypes.DEFAULT_TYPE):
    q = u.callback_query
    await q.answer()
    
    map_keys = {"qr_semanal_5": "semanal_5", "qr_iniciante": "iniciante", "qr_pró": "pró"}
    key = map_keys.get(q.data)
    if not key: return

    plan = get_plan_from_db(key)
    if not plan:
        await q.message.reply_text(f"❌ Plano '{key}' não encontrado no banco.")
        return

    nome = plan.get("nome_do_plano", "Plano")
    # Tenta pegar o código PIX de qualquer coluna provável
    pix = plan.get("pix_copy_paste") or plan.get("pix_code") or plan.get("description") or "N/A"
    
    await q.message.reply_text(
        f"✅ *{nome}*\n\n📱 Copie e pague:\n`{pix}`",
        parse_mode="Markdown"
    )

# ==================== MAIN ====================
def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        print("❌ FALTA TOKEN NO .ENV")
        return

    print(f"🚀 INICIANDO BOT | VERSÃO: {BOT_VERSION}")
    app = ApplicationBuilder().token(token).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("planos", planos))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CallbackQueryHandler(pay_handler, pattern="^qr_"))
    
    print("✅ POLLING INICIADO. AGUARDANDO MENSAGENS...")
    app.run_polling()

if __name__ == "__main__":
    main()