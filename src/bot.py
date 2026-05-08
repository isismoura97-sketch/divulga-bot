import os
import logging
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters, CallbackQueryHandler
from db import (
    get_or_create_user, 
    can_send_message, 
    increment_msg_count, 
    log_message,
    schedule_message,
    get_user_limits,
    get_pending_scheduled
)
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Menu fixo que aparece abaixo da caixa de texto
MENU_PRINCIPAL = ReplyKeyboardMarkup(
    [
        [KeyboardButton("/planos"), KeyboardButton("/status")],
        [KeyboardButton("/ajuda"), KeyboardButton("📢 Divulgar")]
    ],
    resize_keyboard=True,
    input_field_placeholder="Escolha uma opção ou digite sua mensagem..."
)

# Comandos
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db_user = get_or_create_user(user.id, user.username, user.full_name)
    limits = get_user_limits(db_user["plan"])
    
    await update.message.reply_text(
        f"🤖 *Olá, {user.first_name}!*\n\n"
        f"📊 *Seu Plano:* `{db_user['plan'].upper()}`\n"
        f"📤 *Envios hoje:* `{db_user['msgs_sent']}/{limits['daily_msgs']}`\n"
        f"🔗 *Canais:* `{limits['channels']}`\n"
        f"⏰ *Agendamento:* {'✅' if limits['schedule'] else '❌'}\n\n"
        f"💡 *Como usar:*\n"
        f"1. Envie qualquer texto para divulgar\n"
        f"2. Use /planos para ver upgrades\n"
        f"3. Use /ajuda para mais comandos\n\n"
        f"🚀 *DivulgaBot - Potencialize sua audiência!*",
        parse_mode="Markdown",
        reply_markup=MENU_PRINCIPAL
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📚 *Comandos Disponíveis:*\n\n"
        "/start - Iniciar o bot\n"
        "/planos - Ver planos e preços\n"
        "/status - Ver seu uso atual\n"
        "/agendar <texto> <HH:MM> - Agendar mensagem (planos pagos)\n"
        "/menu - Mostrar menu principal\n\n"
        "💬 *Dica:* Envie qualquer texto para divulgar instantaneamente!",
        parse_mode="Markdown",
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
        "• 5 msgs/dia • 1 canal • Sem agendamento\n\n"
        "🟡 *STARTER* - R$19,90/mês\n"
        "• 50 msgs/dia • 5 canais • Agendamento básico\n\n"
        "🔵 *PRO* - R$49,90/mês ⭐ Mais popular\n"
        "• 500 msgs/dia • 20 canais • Analytics + API\n\n"
        "🔴 *BUSINESS* - R$149,90/mês\n"
        "• Ilimitado • Canais ilimitados • Suporte 24/7\n\n"
        "Escolha um plano abaixo 👇",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle dos botões dos planos"""
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
            "⚠️ *Em desenvolvimento:* Integração automática com Mercado Pago em breve!",
            parse_mode="Markdown"
        )
    else:
        await query.edit_message_text(
            f"✅ *Plano {plan.upper()} selecionado!*\n\n"
            f"📩 Envie seu comprovante de pagamento para:\n"
            f"👤 @seu_suporte\n\n"
            f"⏱️ Liberação em até 15 minutos (horário comercial)\n\n"
            f"💡 Dica: Use PIX para liberação instantânea!",
            parse_mode="Markdown"
        )

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db_user = get_or_create_user(user.id, user.username, user.full_name)
    limits = get_user_limits(db_user["plan"])
    
    await update.message.reply_text(
        f"📊 *Seu Status:*\n\n"
        f"👤 ID: `{db_user['telegram_id']}`\n"
        f"📦 Plano: `{db_user['plan'].upper()}`\n"
        f"📤 Envios hoje: `{db_user['msgs_sent']}/{limits['daily_msgs']}`\n"
        f"🔗 Canais disponíveis: `{limits['channels']}`\n"
        f"⏰ Agendamento: {'✅ Ativado' if limits['schedule'] else '❌ Apenas planos pagos'}\n"
        f"📅 Última atualização: `{db_user.get('updated_at', 'N/A')[:10]}`",
        parse_mode="Markdown",
        reply_markup=MENU_PRINCIPAL
    )

async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mostra o menu principal"""
    await update.message.reply_text(
        "📱 *Menu Principal:*\n"
        "Escolha uma opção abaixo 👇",
        reply_markup=MENU_PRINCIPAL
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Processa mensagens de texto para divulgação"""
    user = update.effective_user
    message_text = update.message.text
    
    # Ignora comandos
    if message_text.startswith("/"):
        return
    
    # Verifica limite
    can_send, response_msg = can_send_message(user.id)
    if not can_send:
        await update.message.reply_text(
            response_msg,
            reply_markup=MENU_PRINCIPAL
        )
        return
    
    # Registra e "divulga" (simulação - aqui você integra com seus canais depois)
    increment_msg_count(user.id)
    log_message(user.id, message_text)
    
    await update.message.reply_text(
        "✅ *Mensagem registrada para divulgação!*\n\n"
        f"📝 Conteúdo: `{message_text[:100]}{'...' if len(message_text) > 100 else ''}`\n"
        f"📊 Seu uso: após este envio, você terá utilizado X/Y mensagens hoje.\n\n"
        f"💡 *Próximo:* Configure seus canais alvo no painel web (em breve)!",
        parse_mode="Markdown",
        reply_markup=MENU_PRINCIPAL
    )

async def schedule_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /agendar <texto> <HH:MM>"""
    user = update.effective_user
    db_user = get_or_create_user(user.id, user.username)
    limits = get_user_limits(db_user["plan"])
    
    if not limits["schedule"]:
        await update.message.reply_text(
            "⚠️ *Agendamento disponível apenas nos planos pagos.*\n\n"
            "Veja os planos: `/planos`",
            parse_mode="Markdown",
            reply_markup=MENU_PRINCIPAL
        )
        return
    
    # Parse simples: /agendar texto para divulgar 14:30
    args = " ".join(context.args)
    if not args or " " not in args:
        await update.message.reply_text(
            "📝 *Uso correto:*\n"
            "`/agendar Seu texto aqui HH:MM`\n\n"
            "Ex: `/agendar Promoção relâmpago! 18:30`",
            parse_mode="Markdown",
            reply_markup=MENU_PRINCIPAL
        )
        return
    
    # Separa texto e horário (último elemento é o horário)
    parts = args.rsplit(" ", 1)
    if len(parts) != 2 or ":" not in parts[1]:
        await update.message.reply_text("⚠️ Formato de horário inválido. Use HH:MM (ex: 14:30)")
        return
    
    content, time_str = parts
    try:
        # Monta datetime para hoje/amanhã
        today = datetime.now()
        send_time = datetime.strptime(f"{today.date()} {time_str}", "%Y-%m-%d %H:%M")
        if send_time < today:
            send_time += timedelta(days=1)  # Agenda para amanhã se horário já passou
        
        result = schedule_message(user.id, content, send_time.isoformat())
        if result:
            await update.message.reply_text(
                f"✅ *Mensagem agendada!*\n\n"
                f"📝 `{content[:100]}{'...' if len(content) > 100 else ''}`\n"
                f"⏰ Para: `{send_time.strftime('%d/%m %H:%M')}`\n\n"
                f"Use `/status` para ver seus agendamentos.",
                parse_mode="Markdown",
                reply_markup=MENU_PRINCIPAL
            )
        else:
            await update.message.reply_text("❌ Erro ao agendar. Tente novamente.")
    except Exception as e:
        logger.error(f"Erro ao agendar: {e}")
        await update.message.reply_text("❌ Erro interno. Tente novamente mais tarde.")

# Job para enviar mensagens agendadas (rodar em loop separado ou cron)
async def send_scheduled_jobs(context: ContextTypes.DEFAULT_TYPE):
    """Job periódico para processar mensagens agendadas"""
    from db import supabase
    
    pending = get_pending_scheduled()
    for msg in pending:
        try:
            # Aqui você enviaria via Telegram API para os canais configurados
            # Exemplo simulado:
            supabase.table("scheduled_messages").update({"status": "sent"}).eq("id", msg["id"]).execute()
            logger.info(f"✅ Mensagem {msg['id']} enviada")
        except Exception as e:
            supabase.table("scheduled_messages").update({"status": "failed"}).eq("id", msg["id"]).execute()
            logger.error(f"❌ Falha ao enviar mensagem {msg['id']}: {e}")

def main():
    """Inicializa e roda o bot"""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        print("❌ TELEGRAM_BOT_TOKEN não configurado no .env")
        return
    
    app = ApplicationBuilder().token(token).build()
    
    # Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ajuda", help_command))
    app.add_handler(CommandHandler("planos", planos))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("menu", show_menu))
    app.add_handler(CommandHandler("agendar", schedule_command))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Job para agendamentos (roda a cada 60 segundos)
    app.job_queue.run_repeating(send_scheduled_jobs, interval=60, first=10)
    
    print("🚀 DivulgaBot iniciado! Pressione Ctrl+C para parar.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()