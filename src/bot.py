import os
import logging
import asyncio
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters, CallbackQueryHandler
from telegram.constants import ParseMode
from db import (
    get_or_create_user, 
    can_send_message, 
    increment_msg_count, 
    log_message,
    schedule_message,
    get_user_limits,
    get_pending_scheduled,
    add_user_channel,
    remove_user_channel,
    get_user_channels,
    get_active_channels_count,
    add_to_send_queue,
    get_pending_queue,
    update_queue_status
)
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Menu fixo que aparece abaixo da caixa de texto
MENU_PRINCIPAL = ReplyKeyboardMarkup(
    [
        [KeyboardButton("/planos"), KeyboardButton("/status")],
        [KeyboardButton("/ajuda"), KeyboardButton("📢 Divulgar")],
        [KeyboardButton("/meus_canais"), KeyboardButton("❌ Fechar Menu")]
    ],
    resize_keyboard=True,
    input_field_placeholder="Escolha uma opção ou digite sua mensagem..."
)

MENU_FECHADO = ReplyKeyboardMarkup(
    [[]],
    resize_keyboard=True,
    one_time_keyboard=True
)

# ==================== COMANDOS ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db_user = get_or_create_user(user.id, user.username, user.full_name)
    limits = get_user_limits(db_user["plan"])
    channels_count = get_active_channels_count(user.id)
    
    await update.message.reply_text(
        f"🤖 *Olá, {user.first_name}!*\n\n"
        f"📊 *Seu Plano:* `{db_user['plan'].upper()}`\n"
        f"📤 *Envios hoje:* `{db_user['msgs_sent']}/{limits['daily_msgs']}`\n"
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
        "📚 *Comandos Disponíveis:*\n\n"
        "/start - Iniciar o bot\n"
        "/planos - Ver planos e preços\n"
        "/status - Ver seu uso atual\n"
        "/add_canal @usuario_ou_id - Adicionar canal para divulgar\n"
        "/meus_canais - Listar seus canais\n"
        "/remove_canal @usuario_ou_id - Remover canal\n"
        "/agendar <texto> <HH:MM> - Agendar mensagem (planos pagos)\n"
        "/menu - Mostrar menu principal\n"
        "/fechar_menu - Esconder o menu\n\n"
        "💬 *Dica:* Envie texto, foto, vídeo ou documento para divulgar!",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=MENU_PRINCIPAL
    )

async def planos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🟡 Starter - R$19,90/mês", callback_data="plan_starter")],
        [InlineKeyboardButton("🔵 Pro - R$49,90/mês", callback_data="plan_pro")],
        [InlineKeyboardButton("🔴 Business - R$149,90/mês", callback_data="plan_business")],
        [InlineKeyboardButton("💳 Ver métodos de pagamento", callback_data="payment_methods")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "📦 *Nossos Planos:*\n\n"
        "🟢 *FREE* - R$0\n"
        "• 5 msgs/dia • 1 canal • Sem mídia\n\n"
        "🟡 *STARTER* - R$19,90/mês\n"
        "• 50 msgs/dia • 5 canais • Fotos/Vídeos • Agendamento\n\n"
        "🔵 *PRO* - R$49,90/mês ⭐ Mais popular\n"
        "• 500 msgs/dia • 20 canais • Analytics + API\n\n"
        "🔴 *BUSINESS* - R$149,90/mês\n"
        "• Ilimitado • Canais ilimitados • Suporte 24/7\n\n"
        "Escolha um plano abaixo 👇",
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    plan = query.data.replace("plan_", "")
    
    if plan == "payment_methods":
        await query.edit_message_text(
            "💳 *Métodos de Pagamento:*\n\n"
            "✅ PIX (liberação imediata)\n"
            "✅ Cartão de Crédito\n"
            "✅ Boleto Bancário\n\n"
            "🔗 Para ativar: envie o comprovante para @seu_suporte\n\n"
            "⚠️ *Em desenvolvimento:* Integração automática com Mercado Pago!",
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        await query.edit_message_text(
            f"✅ *Plano {plan.upper()} selecionado!*\n\n"
            f"📩 Envie seu comprovante para:\n"
            f"👤 @seu_suporte\n\n"
            f"⏱️ Liberação em até 15 minutos!\n\n"
            f"💡 Dica: Use PIX para liberação instantânea!",
            parse_mode=ParseMode.MARKDOWN
        )

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db_user = get_or_create_user(user.id, user.username, user.full_name)
    limits = get_user_limits(db_user["plan"])
    channels = get_user_channels(user.id)
    
    channels_list = "\n".join([f"• `{ch['channel_name'] or ch['channel_id']}`" for ch in channels[:5]])
    if len(channels) > 5:
        channels_list += f"\n• ... e mais {len(channels) - 5} canais"
    
    await update.message.reply_text(
        f"📊 *Seu Status:*\n\n"
        f"👤 ID: `{db_user['telegram_id']}`\n"
        f"📦 Plano: `{db_user['plan'].upper()}`\n"
        f"📤 Envios hoje: `{db_user['msgs_sent']}/{limits['daily_msgs']}`\n"
        f"🔗 Canais: `{len(channels)}/{limits['channels']}`\n"
        f"🖼️ Mídia: {'✅ Ativado' if limits['media'] else '❌ Apenas planos pagos'}\n"
        f"⏰ Agendamento: {'✅ Ativado' if limits['schedule'] else '❌ Apenas planos pagos'}\n\n"
        f"📋 *Seus Canais:*\n{channels_list if channels_list else 'Nenhum canal adicionado ainda.'}\n\n"
        f"💡 Use `/add_canal @seucanal` para adicionar!",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=MENU_PRINCIPAL
    )

async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📱 *Menu Principal:*\nEscolha uma opção 👇", reply_markup=MENU_PRINCIPAL)

async def close_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ Menu fechado! Digite /menu para abrir novamente.", reply_markup=MENU_FECHADO)

# ==================== GERENCIAMENTO DE CANAIS ====================
async def add_channel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/add_canal @usuario_ou_id"""
    user = update.effective_user
    
    if not context.args:
        await update.message.reply_text(
            "📝 *Uso:* `/add_canal @seucanal` ou `/add_canal -100123456789`\n\n"
            "💡 Para adicionar um canal:\n"
            "1. Adicione @divulgaai_chefebot como administrador no canal\n"
            "2. Use o comando com o @ ou ID do canal",
            parse_mode="Markdown",
            reply_markup=MENU_PRINCIPAL
        )
        return
    
    channel_input = context.args[0]
    channel_name = None
    channel_type = "channel"
    
    try:
        success, message = add_user_channel(user.id, channel_input, channel_name, channel_type)
        
        # SEM parse_mode para evitar erro de Markdown
        await update.message.reply_text(
            str(message),
            reply_markup=MENU_PRINCIPAL
        )
    except Exception as e:
        logger.error(f"Erro ao adicionar canal: {e}")
        # SEM parse_mode para mensagens de erro
        await update.message.reply_text(
            f"❌ Erro: {str(e)}",
            reply_markup=MENU_PRINCIPAL
        )

async def list_channels_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/meus_canais"""
    user = update.effective_user
    channels = get_user_channels(user.id)
    
    if not channels:
        await update.message.reply_text(
            "📭 *Nenhum canal configurado ainda!*\n\n"
            "Use `/add_canal @seucanal` para adicionar seu primeiro canal.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=MENU_PRINCIPAL
        )
        return
    
    channels_text = "📋 *Seus Canais Ativos:*\n\n"
    for i, ch in enumerate(channels, 1):
        channels_text += f"{i}. `{ch['channel_name'] or ch['channel_id']}`\n"
        channels_text += f"   Tipo: {ch['channel_type']} • ID: `{ch['channel_id']}`\n\n"
    
    channels_text += f"💡 Use `/remove_canal @canal` para remover."
    
    await update.message.reply_text(
        channels_text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=MENU_PRINCIPAL
    )

async def remove_channel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/remove_canal @usuario_ou_id"""
    user = update.effective_user
    
    if not context.args:
        await update.message.reply_text(
            "📝 *Uso:* `/remove_canal @seucanal`",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=MENU_PRINCIPAL
        )
        return
    
    channel_id = context.args[0]
    success = remove_user_channel(user.id, channel_id)
    
    await update.message.reply_text(
        "✅ Canal removido!" if success else "❌ Canal não encontrado.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=MENU_PRINCIPAL
    )

# ==================== ENVIO REAL DE MENSAGENS ====================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Processa mensagens para divulgação REAL"""
    user = update.effective_user
    message = update.message
    
    # Ignora comandos
    if message.text and message.text.startswith("/"):
        return
    
    # Verifica limite
    can_send, response_msg = can_send_message(user.id)
    if not can_send:
        await update.message.reply_text(response_msg, parse_mode=ParseMode.MARKDOWN, reply_markup=MENU_PRINCIPAL)
        return
    
    # Obtém canais do usuário
    channels = get_user_channels(user.id)
    if not channels:
        await update.message.reply_text(
            "⚠️ *Nenhum canal configurado!*\n\n"
            "Use `/add_canal @seucanal` para adicionar um canal antes de divulgar.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=MENU_PRINCIPAL
        )
        return
    
    # Detecta tipo de conteúdo
    content = message.text or message.caption or ""
    media_url = None
    media_type = "none"
    
    if message.photo:
        media_type = "photo"
        media_url = (await message.photo[-1].get_file()).file_path
    elif message.video:
        media_type = "video"
        media_url = (await message.video.get_file()).file_path
    elif message.document:
        media_type = "document"
        media_url = (await message.document.get_file()).file_path
    elif message.audio:
        media_type = "audio"
        media_url = (await message.audio.get_file()).file_path
    
    # Verifica se plano permite mídia
    db_user = get_or_create_user(user.id, user.username)
    limits = get_user_limits(db_user["plan"])
    
    if media_type != "none" and not limits["media"]:
        await update.message.reply_text(
            "⚠️ *Mídia disponível apenas nos planos pagos!*\n\n"
            "Envie apenas texto ou faça upgrade: `/planos`",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=MENU_PRINCIPAL
        )
        return
    
    # Prepara lista de canais alvo
    target_channels = [ch["channel_id"] for ch in channels]
    
    # Adiciona na fila de envio
    queue_item = add_to_send_queue(
        telegram_id=user.id,
        content=content,
        target_channels=target_channels,
        media_url=media_url,
        media_type=media_type,
        caption=message.caption if message.caption and media_type != "none" else None
    )
    
    if queue_item:
        increment_msg_count(user.id)
        await update.message.reply_text(
            f"✅ *Mensagem enviada para {len(target_channels)} canal(is)!*\n\n"
            f"📝 Conteúdo: `{content[:100]}{'...' if len(content) > 100 else ''}`\n"
            f"🖼️ Mídia: {'✅ ' + media_type if media_type != 'none' else '❌ Apenas texto'}\n"
            f"📊 Seu uso: `{db_user['msgs_sent'] + 1}/{limits['daily_msgs']}`\n\n"
            f"💡 O bot está enviando agora. Pode demorar alguns segundos!",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=MENU_PRINCIPAL
        )
    else:
        await update.message.reply_text("❌ Erro ao processar sua mensagem. Tente novamente.", reply_markup=MENU_PRINCIPAL)

# ==================== PROCESSAMENTO DA FILA ====================
async def process_send_queue(app):
    """Processa mensagens na fila de envio (roda a cada 30s)"""
    pending = get_pending_queue(limit=5)  # Processa 5 por vez para não sobrecarregar
    
    for item in pending:
        try:
            update_queue_status(item["id"], "sending")
            
            telegram_id = item["telegram_id"]
            content = item["content"]
            media_url = item["media_url"]
            media_type = item["media_type"]
            caption = item["caption"]
            target_channels = item["target_channels"] if isinstance(item["target_channels"], list) else eval(item["target_channels"])
            
            # Envia para cada canal
            for channel_id in target_channels:
                try:
                    if media_type == "photo" and media_url:
                        await app.bot.send_photo(
                            chat_id=channel_id,
                            photo=media_url,
                            caption=caption or content,
                            parse_mode=ParseMode.MARKDOWN
                        )
                    elif media_type == "video" and media_url:
                        await app.bot.send_video(
                            chat_id=channel_id,
                            video=media_url,
                            caption=caption or content,
                            parse_mode=ParseMode.MARKDOWN
                        )
                    elif media_type == "document" and media_url:
                        await app.bot.send_document(
                            chat_id=channel_id,
                            document=media_url,
                            caption=caption or content,
                            parse_mode=ParseMode.MARKDOWN
                        )
                    elif media_type == "audio" and media_url:
                        await app.bot.send_audio(
                            chat_id=channel_id,
                            audio=media_url,
                            caption=caption or content,
                            parse_mode=ParseMode.MARKDOWN
                        )
                    elif content:
                        await app.bot.send_message(
                            chat_id=channel_id,
                            text=content,
                            parse_mode=ParseMode.MARKDOWN
                        )
                    
                    log_message(telegram_id, content, channel_id, "sent")
                    logger.info(f"✅ Enviado para {channel_id}")
                    
                except Exception as e:
                    logger.error(f"❌ Falha ao enviar para {channel_id}: {e}")
                    log_message(telegram_id, content, channel_id, f"failed: {str(e)}")
            
            update_queue_status(item["id"], "sent")
            logger.info(f"🎯 Mensagem {item['id']} processada com sucesso")
            
        except Exception as e:
            logger.error(f"❌ Erro ao processar fila {item['id']}: {e}")
            update_queue_status(item["id"], "failed")

# ==================== AGENDAMENTOS ====================
async def schedule_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /agendar <texto> <HH:MM>"""
    user = update.effective_user
    db_user = get_or_create_user(user.id, user.username)
    limits = get_user_limits(db_user["plan"])
    
    if not limits["schedule"]:
        await update.message.reply_text(
            "⚠️ *Agendamento disponível apenas nos planos pagos.*\n\n"
            "Veja os planos: `/planos`",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=MENU_PRINCIPAL
        )
        return
    
    args = " ".join(context.args)
    if not args or " " not in args:
        await update.message.reply_text(
            "📝 *Uso correto:*\n"
            "`/agendar Seu texto aqui HH:MM`\n\n"
            "Ex: `/agendar Promoção relâmpago! 18:30`",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=MENU_PRINCIPAL
        )
        return
    
    content, time_str = args.rsplit(" ", 1)
    if ":" not in time_str:
        await update.message.reply_text("⚠️ Formato de horário inválido. Use HH:MM (ex: 14:30)")
        return
    
    try:
        today = datetime.now()
        send_time = datetime.strptime(f"{today.date()} {time_str}", "%Y-%m-%d %H:%M")
        if send_time < today:
            send_time += timedelta(days=1)
        
        result = schedule_message(user.id, content, send_time.isoformat())
        if result:
            await update.message.reply_text(
                f"✅ *Mensagem agendada!*\n\n"
                f"📝 `{content[:100]}{'...' if len(content) > 100 else ''}`\n"
                f"⏰ Para: `{send_time.strftime('%d/%m %H:%M')}`\n\n"
                f"Use `/status` para ver seus agendamentos.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=MENU_PRINCIPAL
            )
        else:
            await update.message.reply_text("❌ Erro ao agendar. Tente novamente.")
    except Exception as e:
        logger.error(f"Erro ao agendar: {e}")
        await update.message.reply_text("❌ Erro interno. Tente novamente mais tarde.")

async def process_scheduled_messages(app):
    """Processa mensagens agendadas (roda a cada 60s)"""
    pending = get_pending_scheduled()
    
    for msg in pending:
        try:
            # Aqui você implementaria o envio real para agendamentos
            # Por enquanto, apenas marca como enviado
            from db import supabase
            supabase.table("scheduled_messages").update({"status": "sent"}).eq("id", msg["id"]).execute()
            logger.info(f"✅ Mensagem agendada {msg['id']} processada")
        except Exception as e:
            logger.error(f"❌ Falha ao processar agendamento {msg['id']}: {e}")

# ==================== MAIN ====================
def main():
    """Inicializa e roda o bot"""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        print("❌ TELEGRAM_BOT_TOKEN não configurado no .env")
        return
    
    app = ApplicationBuilder().token(token).build()
    
    # Handlers de comandos
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ajuda", help_command))
    app.add_handler(CommandHandler("planos", planos))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("menu", show_menu))
    app.add_handler(CommandHandler("fechar_menu", close_menu))
    app.add_handler(CommandHandler("add_canal", add_channel_command))
    app.add_handler(CommandHandler("meus_canais", list_channels_command))
    app.add_handler(CommandHandler("remove_canal", remove_channel_command))
    app.add_handler(CommandHandler("agendar", schedule_command))
    
    # Handlers de callback e mensagens
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO | filters.Document.ALL | filters.AUDIO, handle_message))
    
    # Jobs periódicos (fila e agendamentos)
    if app.job_queue:
        app.job_queue.run_repeating(lambda ctx: asyncio.create_task(process_send_queue(app)), interval=30, first=10)
        app.job_queue.run_repeating(lambda ctx: asyncio.create_task(process_scheduled_messages(app)), interval=60, first=30)
    
    print("🚀 DivulgaBot iniciado! Pressione Ctrl+C para parar.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()