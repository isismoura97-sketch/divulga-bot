import os
import logging
import asyncio
import json
import base64
import io
from datetime import datetime, timedelta
from typing import List, Dict, Any

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters, CallbackQueryHandler
from telegram.constants import ParseMode
from dotenv import load_dotenv

# Importação Segura: O bot inicia mesmo se a lib falhar
try:
    import mercadopago
    from PIL import Image
    HAS_MP = True
except ImportError:
    HAS_MP = False
    logging.warning("⚠️ Biblioteca 'mercadopago' ou 'pillow' não encontrada. Pagamentos desativados.")

from db import (
    get_or_create_user, can_send_message, increment_msg_count, log_message,
    schedule_message, get_user_limits, get_pending_scheduled,
    add_user_channel, remove_user_channel, get_user_channels, get_active_channels_count,
    add_to_send_queue, get_pending_queue, update_queue_status, activate_plan, PLANS_CONFIG
)

# ==================== CONFIGURAÇÃO ====================
load_dotenv()
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Mercado Pago
MP_TOKEN = os.getenv("MP_ACCESS_TOKEN")
mp_sdk = mercadopago.SDK(MP_TOKEN) if (MP_TOKEN and HAS_MP) else None
if not mp_sdk and HAS_MP:
    logger.warning("⚠️ MP_ACCESS_TOKEN não configurado. Comando /upgrade não gerará pagamentos.")

# Menus
MENU_PRINCIPAL = ReplyKeyboardMarkup([
    [KeyboardButton("/planos"), KeyboardButton("/status")],
    [KeyboardButton("/ajuda"), KeyboardButton("📢 Divulgar")],
    [KeyboardButton("/meus_canais"), KeyboardButton(" Fechar Menu")]
], resize_keyboard=True, input_field_placeholder="Escolha uma opção ou digite sua mensagem...")

MENU_FECHADO = ReplyKeyboardMarkup([[]], resize_keyboard=True, one_time_keyboard=True)

# ==================== COMANDOS ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    try:
        db_user = get_or_create_user(user.id, user.username, user.full_name)
        limits = get_user_limits(db_user.get("plan", "free"))
        channels_count = get_active_channels_count(user.id)
        
        expires = db_user.get("plan_expires_at")
        expire_msg = "♾️ Permanente"
        if expires:
            exp_date = datetime.fromisoformat(expires)
            expire_msg = f"⏳ Expira em {exp_date.strftime('%d/%m %H:%M')}"
            
    except Exception as e:
        logger.error(f"Erro no /start: {e}")
        await update.message.reply_text("❌ Erro interno ao carregar dados. Tente novamente.")
        return

    await update.message.reply_text(
        f"🤖 *Olá, {user.first_name}!*\n\n"
        f"📦 *Seu Plano:* `{PLANS_CONFIG.get(db_user.get('plan', 'free'), {}).get('name', 'Free')}`\n"
        f"📅 *Validade:* {expire_msg}\n"
        f"📤 *Envios hoje:* `{db_user.get('msgs_sent', 0)}/{limits['daily_msgs']}`\n"
        f"🔗 *Canais configurados:* `{channels_count}/{limits['channels']}`\n"
        f"🖼️ *Mídia:* {'✅' if limits['media'] else '❌'}\n"
        f"⏰ *Agendamento:* {'✅' if limits['schedule'] else '❌'}\n\n"
        f"💡 *Como usar:*\n"
        f"1. Adicione canais: `/add_canal @seucanal`\n"
        f"2. Envie texto ou mídia para divulgar\n"
        f"3. Use /planos para upgrades\n\n"
        f"🚀 *DivulgaBot - Potencialize sua audiência!*",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=MENU_PRINCIPAL
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        " *Comandos Disponíveis:*\n\n"
        "/start - Iniciar o bot\n"
        "/planos - Ver planos e preços\n"
        "/status - Ver seu uso atual\n"
        "/trial24h - Ativar teste grátis de 24h\n"
        "/add_canal @usuario_ou_id - Adicionar canal\n"
        "/meus_canais - Listar seus canais\n"
        "/remove_canal @usuario_ou_id - Remover canal\n"
        "/agendar <texto> <HH:MM> - Agendar mensagem\n"
        "/upgrade - Comprar plano pago\n"
        "/menu - Mostrar menu principal\n"
        "/fechar_menu - Esconder o menu",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=MENU_PRINCIPAL
    )

async def trial_24h(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ativa plano gratuito de 24 horas"""
    user = update.effective_user
    db_user = get_or_create_user(user.id, user.username)
    
    if db_user["plan"] != "free":
        await update.message.reply_text("⚠️ Você já possui um plano ativo. Use `/status` para verificar.", reply_markup=MENU_PRINCIPAL)
        return
        
    activate_plan(user.id, "free_24h", duration_days=1)
    await update.message.reply_text(
        "✅ *Teste 24h ativado!*\n\n"
        "Você agora tem acesso a:\n"
        "• 20 mensagens/dia\n"
        "• 2 canais\n"
        "• Envio de fotos/vídeos\n\n"
        "⏳ Válido por 24 horas a partir de agora.\n"
        "Use `/start` para ver seu novo status.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=MENU_PRINCIPAL
    )

async def planos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🟢 Teste 24h GRÁTIS", callback_data="trial_info")],
        [InlineKeyboardButton("🟡 Semanal - R$5,00", callback_data="pay_weekly")],
        [InlineKeyboardButton("🔵 Starter - R$19,90/mês", callback_data="pay_starter")],
        [InlineKeyboardButton("🔴 Pro - R$49,90/mês", callback_data="pay_pro")],
        [InlineKeyboardButton(" Ver métodos de pagamento", callback_data="payment_methods")]
    ]
    await update.message.reply_text(
        "📦 *Nossos Planos:*\n\n"
        "🟢 *Teste 24h* - R$0\n• 20 msgs/dia • 2 canais • Mídia • 24h de acesso\n\n"
        "🟡 *Semanal* - R$5,00\n• 50 msgs/dia • 5 canais • Agendamento • 7 dias\n\n"
        "🔵 *Starter* - R$19,90/mês\n• 50 msgs/dia • 5 canais • Fotos/Vídeos • Agendamento\n\n"
        "🔴 *Pro* - R$49,90/mês ⭐ Mais popular\n• 500 msgs/dia • 20 canais • Analytics\n\n"
        "Escolha uma opção abaixo 👇",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db_user = get_or_create_user(user.id, user.username, user.full_name)
    limits = get_user_limits(db_user.get("plan", "free"))
    channels = get_user_channels(user.id)
    
    expires = db_user.get("plan_expires_at")
    expire_str = "♾️ Permanente"
    if expires:
        expire_str = datetime.fromisoformat(expires).strftime("%d/%m/%Y %H:%M")
    
    channels_list = "\n".join([f"• `{ch.get('channel_name') or ch.get('channel_id')}`" for ch in channels[:5]])
    if len(channels) > 5:
        channels_list += f"\n• ... e mais {len(channels) - 5} canais"
    
    await update.message.reply_text(
        f" *Seu Status:*\n\n"
        f"👤 ID: `{db_user['telegram_id']}`\n"
        f"📦 Plano: `{PLANS_CONFIG.get(db_user['plan'], {}).get('name', 'Free')}`\n"
        f"📅 Expira em: `{expire_str}`\n"
        f"📤 Envios hoje: `{db_user['msgs_sent']}/{limits['daily_msgs']}`\n"
        f"🔗 Canais: `{len(channels)}/{limits['channels']}`\n"
        f"🖼️ Mídia: {'✅' if limits['media'] else '❌'}\n"
        f"⏰ Agendamento: {'✅' if limits['schedule'] else '❌'}\n\n"
        f"📋 *Seus Canais:*\n{channels_list if channels_list else 'Nenhum canal adicionado.'}",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=MENU_PRINCIPAL
    )

async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📱 *Menu Principal:*\nEscolha uma opção 👇", reply_markup=MENU_PRINCIPAL)

async def close_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ Menu fechado. Digite `/menu` para abrir novamente.", reply_markup=MENU_FECHADO)

# ==================== CANAIS ====================
async def add_channel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("📝 *Uso:* `/add_canal @seucanal` ou `/add_canal -100123456789`\n\n💡 Adicione @divulgaai_chefebot como administrador no canal antes.", parse_mode=ParseMode.MARKDOWN, reply_markup=MENU_PRINCIPAL)
        return
    
    channel_input = context.args[0]
    try:
        success, message = add_user_channel(update.effective_user.id, channel_input, None, "channel")
        await update.message.reply_text(str(message), reply_markup=MENU_PRINCIPAL)
    except Exception as e:
        logger.error(f"Erro add_canal: {e}")
        await update.message.reply_text(f"❌ Erro: {str(e)[:100]}", reply_markup=MENU_PRINCIPAL)

async def list_channels_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    channels = get_user_channels(update.effective_user.id)
    if not channels:
        await update.message.reply_text("📭 Nenhum canal configurado. Use `/add_canal @seucanal`", reply_markup=MENU_PRINCIPAL)
        return
    
    txt = "📋 *Seus Canais Ativos:*\n\n" + "\n".join([f"{i+1}. `{ch.get('channel_name') or ch.get('channel_id')}`" for i, ch in enumerate(channels)])
    txt += "\n\n💡 Use `/remove_canal @canal` para remover."
    await update.message.reply_text(txt, parse_mode=ParseMode.MARKDOWN, reply_markup=MENU_PRINCIPAL)

async def remove_channel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("📝 *Uso:* `/remove_canal @seucanal`", parse_mode=ParseMode.MARKDOWN, reply_markup=MENU_PRINCIPAL)
        return
    success = remove_user_channel(update.effective_user.id, context.args[0])
    await update.message.reply_text("✅ Canal removido!" if success else "❌ Canal não encontrado.", reply_markup=MENU_PRINCIPAL)

# ==================== AGENDAMENTOS ====================
async def schedule_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db_user = get_or_create_user(user.id, user.username)
    if not get_user_limits(db_user.get("plan", "free"))["schedule"]:
        await update.message.reply_text("⚠️ Agendamento disponível apenas nos planos pagos. Use `/planos`", reply_markup=MENU_PRINCIPAL)
        return
    
    args = " ".join(context.args)
    if " " not in args:
        await update.message.reply_text("📝 *Uso:* `/agendar Seu texto aqui HH:MM`\nEx: `/agendar Promoção! 18:30`", parse_mode=ParseMode.MARKDOWN, reply_markup=MENU_PRINCIPAL)
        return
    
    content, time_str = args.rsplit(" ", 1)
    if ":" not in time_str:
        await update.message.reply_text("⚠️ Horário inválido. Use HH:MM", reply_markup=MENU_PRINCIPAL)
        return
    
    try:
        today = datetime.now()
        send_time = datetime.strptime(f"{today.date()} {time_str}", "%Y-%m-%d %H:%M")
        if send_time < today:
            send_time += timedelta(days=1)
        
        result = schedule_message(user.id, content, send_time.isoformat())
        if result:
            await update.message.reply_text(f"✅ Agendado para `{send_time.strftime('%d/%m %H:%M')}`", parse_mode=ParseMode.MARKDOWN, reply_markup=MENU_PRINCIPAL)
        else:
            await update.message.reply_text("❌ Erro ao agendar.", reply_markup=MENU_PRINCIPAL)
    except Exception as e:
        logger.error(f"Erro agendar: {e}")
        await update.message.reply_text("❌ Erro interno.", reply_markup=MENU_PRINCIPAL)

# ==================== PAGAMENTOS (MERCADO PAGO) ====================
async def upgrade_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await planos(update, context)

async def payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "trial_info":
        await query.edit_message_text(
            " *Teste 24h GRÁTIS*\n\n"
            "• 20 mensagens/dia\n"
            "• 2 canais configuráveis\n"
            "• Envio de fotos e vídeos\n"
            "• Válido por 24 horas\n\n"
            "Para ativar, digite: `/trial24h`",
            parse_mode=ParseMode.MARKDOWN
        )
        return
        
    if query.data == "payment_methods":
        await query.edit_message_text(
            " *Métodos de Pagamento:*\n\n"
            "✅ PIX (Aprovação instantânea)\n"
            "✅ Cartão de Crédito\n"
            "✅ Boleto Bancário\n\n"
            "Após o pagamento, seu plano é ativado automaticamente em até 5 minutos.",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    plans = {
        "pay_weekly": {"price": 5.00, "name": "Semanal", "days": 7},
        "pay_starter": {"price": 19.90, "name": "Starter", "days": None},
        "pay_pro": {"price": 49.90, "name": "Pro", "days": None}
    }
    
    plan_key = query.data.replace("pay_", "")
    plan_info = plans.get(plan_key)
    
    if not plan_info or not mp_sdk:
        await query.message.reply_text("️ Pagamento não configurado no servidor.")
        return

    await query.edit_message_text("🔄 Gerando PIX... Aguarde.")

    try:
        preference_data = {
            "items": [{"title": f"Plano {plan_info['name']} - DivulgaBot", "quantity": 1, "unit_price": plan_info["price"], "currency_id": "BRL"}],
            "payment_methods": {"excluded_payment_types": [{"id": "ticket"}, {"id": "credit_card"}], "installments": 1},
            "external_reference": f"user_{query.from_user.id}_plan_{plan_key}",
            "back_urls": {"success": "https://t.me/divulgaai_chefebot", "failure": "https://t.me/divulgaai_chefebot", "pending": "https://t.me/divulgaai_chefebot"}
        }
        response = mp_sdk.preference().create(preference_data)
        
        if response["status"] == 201:
            body = response["response"]
            link = body.get("init_point", "")
            
            qr_b64 = None
            pix_code = ""
            try:
                poi = body.get("point_of_interaction", {})
                t_data = poi.get("transaction_data", {})
                qr_b64 = t_data.get("qr_code_base64")
                pix_code = t_data.get("qr_code", "")
            except Exception:
                pass

            if qr_b64:
                img_data = base64.b64decode(qr_b64)
                caption = (f"✅ *Plano {plan_info['name']}*\n"
                           f"💰 R${plan_info['price']:.2f}\n"
                           f"📱 Escaneie ou use o Copia e Cola:\n"
                           f"`{pix_code}`\n\n"
                           f"⚠️ A ativação é automática após confirmação.")
                await query.message.reply_photo(photo=io.BytesIO(img_data), caption=caption, parse_mode=ParseMode.MARKDOWN)
            else:
                caption = (f"✅ *Plano {plan_info['name']}*\n"
                           f"💰 R${plan_info['price']:.2f}\n"
                           f"🔗 [Pagar no Mercado Pago]({link})\n\n"
                           f"⚠️ A ativação é automática após confirmação.")
                await query.message.reply_text(caption, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)
        else:
            await query.message.reply_text("❌ Erro ao gerar preferência.")
    except Exception as e:
        logger.error(f"Erro MP: {e}")
        await query.message.reply_text("❌ Falha na conexão com Mercado Pago.")

async def plan_info_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()

# ==================== MANIPULADOR DE MENSAGENS ====================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg.text and not msg.photo and not msg.video and not msg.document:
        return

    user_id = update.effective_user.id
    can_send, limit_msg = can_send_message(user_id)
    if not can_send:
        await update.message.reply_text(limit_msg, parse_mode=ParseMode.MARKDOWN, reply_markup=MENU_PRINCIPAL)
        return

    channels = get_user_channels(user_id)
    if not channels:
        await update.message.reply_text("⚠️ Nenhum canal configurado! Use `/add_canal @seucanal`", reply_markup=MENU_PRINCIPAL)
        return

    content = msg.text or msg.caption or ""
    media_type, media_id = "none", None
    
    if msg.photo:
        media_type, media_id = "photo", msg.photo[-1].file_id
    elif msg.video:
        media_type, media_id = "video", msg.video.file_id
    elif msg.document:
        media_type, media_id = "document", msg.document.file_id

    limits = get_user_limits(get_or_create_user(user_id, "")["plan"])
    if media_type != "none" and not limits["media"]:
        await update.message.reply_text("️ Mídia apenas em planos pagos. Envie texto ou faça upgrade.", reply_markup=MENU_PRINCIPAL)
        return

    target_ids = [ch["channel_id"] for ch in channels]
    queue_item = add_to_send_queue(user_id, content, target_ids, media_id, media_type, msg.caption)
    
    if queue_item:
        increment_msg_count(user_id)
        await update.message.reply_text(f"✅ Enviado para {len(target_ids)} canal(is)!\n📊 Uso: `{get_or_create_user(user_id, '')['msgs_sent']}/{limits['daily_msgs']}`", reply_markup=MENU_PRINCIPAL)

# ==================== FILA & AGENDAMENTOS (BACKGROUND) ====================
async def process_send_queue(app):
    pending = get_pending_queue(limit=5)
    for item in pending:
        try:
            update_queue_status(item["id"], "sending")
            target_channels = item["target_channels"] if isinstance(item["target_channels"], list) else json.loads(item["target_channels"])
            for ch_id in target_channels:
                try:
                    if item["media_type"] == "photo" and item["media_url"]:
                        await app.bot.send_photo(ch_id, item["media_url"], caption=item["caption"] or item["content"])
                    elif item["media_type"] == "video" and item["media_url"]:
                        await app.bot.send_video(ch_id, item["media_url"], caption=item["caption"] or item["content"])
                    elif item["media_type"] == "document" and item["media_url"]:
                        await app.bot.send_document(ch_id, item["media_url"], caption=item["caption"] or item["content"])
                    elif item["content"]:
                        await app.bot.send_message(ch_id, item["content"])
                    log_message(item["telegram_id"], item["content"], ch_id, "sent")
                except Exception as e:
                    logger.error(f"Falha envio {ch_id}: {e}")
                    log_message(item["telegram_id"], item["content"], ch_id, f"failed: {e}")
            update_queue_status(item["id"], "sent")
        except Exception as e:
            logger.error(f"Erro fila {item['id']}: {e}")
            update_queue_status(item["id"], "failed")

async def process_scheduled(app):
    pending = get_pending_scheduled()
    for msg in pending:
        try:
            add_to_send_queue(msg["user_id"], msg["content"], get_user_channels(msg["user_id"]), None, "none", None)
            from db import supabase
            supabase.table("scheduled_messages").update({"status": "sent"}).eq("id", msg["id"]).execute()
        except Exception as e:
            logger.error(f"Erro agendamento {msg['id']}: {e}")

# ==================== MAIN ====================
def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        print("❌ TELEGRAM_BOT_TOKEN faltando no .env")
        return

    app = ApplicationBuilder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ajuda", help_command))
    app.add_handler(CommandHandler("planos", planos))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("trial24h", trial_24h))
    app.add_handler(CommandHandler("menu", show_menu))
    app.add_handler(CommandHandler("fechar_menu", close_menu))
    app.add_handler(CommandHandler("add_canal", add_channel_command))
    app.add_handler(CommandHandler("meus_canais", list_channels_command))
    app.add_handler(CommandHandler("remove_canal", remove_channel_command))
    app.add_handler(CommandHandler("agendar", schedule_command))
    app.add_handler(CommandHandler("upgrade", upgrade_command))

    app.add_handler(CallbackQueryHandler(payment_callback, pattern="^(pay_|trial_info|payment_methods)"))
    app.add_handler(CallbackQueryHandler(plan_info_callback, pattern="^(plan_)"))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO | filters.Document.ALL, handle_message))

    if app.job_queue:
        app.job_queue.run_repeating(lambda ctx: asyncio.create_task(process_send_queue(app)), interval=30, first=10)
        app.job_queue.run_repeating(lambda ctx: asyncio.create_task(process_scheduled(app)), interval=60, first=30)

    print("🚀 DivulgaBot online! Pressione Ctrl+C para parar.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()