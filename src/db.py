import os
import json
from datetime import date, datetime
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

supabase: Client = create_client(
    os.getenv("SUPABASE_URL"), 
    os.getenv("SUPABASE_KEY")
)

# ==================== USUÁRIOS ====================
def get_or_create_user(telegram_id: int, username: str, full_name: str = None):
    try:
        response = supabase.table("users").select("*").eq("telegram_id", telegram_id).execute()
        
        if response.data and len(response.data) > 0:
            user = response.data[0]
            if user.get("last_reset") != date.today().isoformat():
                supabase.table("users").update({
                    "msgs_sent": 0,
                    "last_reset": date.today().isoformat()
                }).eq("telegram_id", telegram_id).execute()
                user["msgs_sent"] = 0
            return user
        
        new_user = {
            "telegram_id": telegram_id,
            "username": username,
            "full_name": full_name,
            "plan": "free",
            "msgs_sent": 0,
            "last_reset": date.today().isoformat()
        }
        result = supabase.table("users").insert(new_user).execute()
        return result.data[0] if result.data else new_user
        
    except Exception as e:
        print(f"❌ Erro no db.py (get_or_create_user): {e}")
        return {"telegram_id": telegram_id, "plan": "free", "msgs_sent": 0}

def get_user_limits(plan: str) -> dict:
    return {
        "free": {"daily_msgs": 5, "channels": 1, "schedule": False, "media": False},
        "starter": {"daily_msgs": 50, "channels": 5, "schedule": True, "media": True},
        "pro": {"daily_msgs": 500, "channels": 20, "schedule": True, "media": True},
        "business": {"daily_msgs": 9999, "channels": 999, "schedule": True, "media": True}
    }.get(plan, {"daily_msgs": 5, "channels": 1, "schedule": False, "media": False})

def can_send_message(telegram_id: int) -> tuple:
    user = get_or_create_user(telegram_id, "", "")
    limits = get_user_limits(user["plan"])
    
    if user["msgs_sent"] >= limits["daily_msgs"]:
        return False, f"⚠️ Limite diário atingido ({user['msgs_sent']}/{limits['daily_msgs']}).\nFaça upgrade: `/planos`"
    return True, "OK"

def increment_msg_count(telegram_id: int):
    try:
        user = get_or_create_user(telegram_id, "", "")
        supabase.table("users").update({"msgs_sent": user["msgs_sent"] + 1}).eq("telegram_id", telegram_id).execute()
    except Exception as e:
        print(f"Erro ao incrementar: {e}")

# ==================== CANAIS ====================
def add_user_channel(telegram_id: int, channel_id: str, channel_name: str = None, channel_type: str = "channel"):
    """Adiciona um canal para o usuário divulgar"""
    try:
        # 1. Garante que o usuário existe no banco
        user = get_or_create_user(telegram_id, "", "")
        
        # 2. Verifica limite de canais por plano
        limits = get_user_limits(user.get("plan", "free"))
        active_count = get_active_channels_count(telegram_id)
        
        if active_count >= limits["channels"]:
            return False, f"⚠️ Limite de canais atingido ({active_count}/{limits['channels']}).\nFaça upgrade para adicionar mais!"
        
        # 3. Verifica se já existe
        existing = supabase.table("user_channels").select("id").eq("telegram_id", telegram_id).eq("channel_id", channel_id).execute()
        if existing.data and len(existing.data) > 0:
            supabase.table("user_channels").update({"is_active": True}).eq("id", existing.data[0]["id"]).execute()
            return True, "✅ Canal reativado!"
        
        # 4. Insere novo canal
        result = supabase.table("user_channels").insert({
            "telegram_id": telegram_id,
            "channel_id": channel_id,
            "channel_name": channel_name,
            "channel_type": channel_type
        }).execute()
        
        return True, "✅ Canal adicionado com sucesso!" if result.data else (False, "❌ Erro ao adicionar canal")
        
    except Exception as e:
        err_str = str(e)
        # Captura especificamente o erro de chave estrangeira (23503)
        if "23503" in err_str or "foreign key" in err_str.lower():
            return False, "⚠️ Usuário não encontrado no banco.\nPor favor, envie /start primeiro!"
        print(f"❌ Erro ao adicionar canal: {e}")
        return False, f"❌ Erro interno: {str(e)[:50]}..."

def remove_user_channel(telegram_id: int, channel_id: str):
    """Remove/desativa um canal do usuário"""
    try:
        result = supabase.table("user_channels").update({"is_active": False}).eq("telegram_id", telegram_id).eq("channel_id", channel_id).execute()
        return result.data is not None
    except Exception as e:
        print(f"❌ Erro ao remover canal: {e}")
        return False

def get_user_channels(telegram_id: int):
    """Lista canais ativos do usuário"""
    try:
        response = supabase.table("user_channels").select("*").eq("telegram_id", telegram_id).eq("is_active", True).execute()
        return response.data if response.data else []
    except Exception as e:
        print(f"❌ Erro ao listar canais: {e}")
        return []

def get_active_channels_count(telegram_id: int) -> int:
    """Conta canais ativos do usuário"""
    try:
        response = supabase.table("user_channels").select("id", count="exact").eq("telegram_id", telegram_id).eq("is_active", True).execute()
        return response.count if hasattr(response, 'count') and response.count else 0
    except:
        return len(get_user_channels(telegram_id))

# ==================== FILA DE ENVIO ====================
def add_to_send_queue(telegram_id: int, content: str, target_channels: list, media_url: str = None, media_type: str = "none", caption: str = None):
    """Adiciona mensagem na fila de envio"""
    try:
        result = supabase.table("send_queue").insert({
            "telegram_id": telegram_id,
            "content": content,
            "media_url": media_url,
            "media_type": media_type,
            "caption": caption,
            "target_channels": json.dumps(target_channels),
            "status": "pending"
        }).execute()
        return result.data[0] if result.data else None
    except Exception as e:
        print(f"❌ Erro ao adicionar na fila: {e}")
        return None

def get_pending_queue(limit: int = 10):
    """Busca mensagens pendentes na fila"""
    try:
        response = supabase.table("send_queue").select("""
            *,
            users ( plan, username, telegram_id )
        """).eq("status", "pending").order("created_at", desc=False).limit(limit).execute()
        return response.data if response.data else []
    except Exception as e:
        print(f"❌ Erro ao buscar fila: {e}")
        return []

def update_queue_status(queue_id: int, status: str, error: str = None):
    """Atualiza status da mensagem na fila"""
    try:
        update_data = {"status": status, "processed_at": datetime.utcnow().isoformat()}
        if error:
            queue_data = supabase.table("send_queue").select("retry_count").eq("id", queue_id).execute()
            if queue_data.data:
                update_data["retry_count"] = queue_data.data[0]["retry_count"] + 1
        supabase.table("send_queue").update(update_data).eq("id", queue_id).execute()
    except Exception as e:
        print(f"❌ Erro ao atualizar fila: {e}")

# ==================== LOGS ====================
def log_message(telegram_id: int, content: str, channel: str = None, status: str = "sent"):
    try:
        supabase.table("send_logs").insert({
            "telegram_id": telegram_id,
            "message_content": content[:500],
            "channel_name": channel,
            "status": status
        }).execute()
    except Exception as e:
        print(f"⚠️ Erro ao logar mensagem: {e}")

# ==================== AGENDAMENTOS ====================
def schedule_message(telegram_id: int, content: str, send_at: str, media_url: str = None):
    try:
        result = supabase.table("scheduled_messages").insert({
            "user_id": telegram_id,
            "content": content,
            "media_url": media_url,
            "send_at": send_at,
            "status": "pending"
        }).execute()
        return result.data[0] if result.data else None
    except Exception as e:
        print(f"❌ Erro ao agendar: {e}")
        return None

def get_pending_scheduled() -> list:
    from datetime import datetime
    now = datetime.utcnow().isoformat()
    
    response = supabase.table("scheduled_messages").select("""
        *,
        users ( plan, username )
    """).eq("status", "pending").lte("send_at", now).execute()
    
    return response.data if response.data else []