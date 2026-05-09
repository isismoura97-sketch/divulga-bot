import os
import json
from datetime import date, datetime, timedelta
from typing import Tuple
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

supabase: Client = create_client(
    os.getenv("SUPABASE_URL"), 
    os.getenv("SUPABASE_KEY")
)

# ==================== CONFIGURAÇÃO DE PLANOS ====================
PLANS_CONFIG = {
    "free":          {"daily_msgs": 5,   "channels": 1,  "schedule": False, "media": False, "name": "Free"},
    "free_24h":      {"daily_msgs": 20,  "channels": 2,  "schedule": False, "media": True,  "name": "Teste 24h"},
    "weekly_5":      {"daily_msgs": 50,  "channels": 5,  "schedule": True,  "media": True,  "name": "Semanal R$5"},
    "starter":       {"daily_msgs": 50,  "channels": 5,  "schedule": True,  "media": True,  "name": "Starter"},
    "pro":           {"daily_msgs": 500, "channels": 20, "schedule": True,  "media": True,  "name": "Pro"},
    "business":      {"daily_msgs": 9999,"channels": 999,"schedule": True,  "media": True,  "name": "Business"}
}

def get_user_limits(plan: str) -> dict:
    return PLANS_CONFIG.get(plan, PLANS_CONFIG["free"])

# ==================== GERENCIAMENTO DE USUÁRIOS ====================
def check_and_downgrade_expired(telegram_id: int) -> str:
    """Verifica expiração e faz downgrade automático se necessário"""
    try:
        response = supabase.table("users").select("plan, plan_expires_at").eq("telegram_id", telegram_id).execute()
        if not response.data:
            return "free"
        
        user = response.data[0]
        expires = user.get("plan_expires_at")
        
        if expires and datetime.fromisoformat(expires) < datetime.utcnow():
            # Plano expirou: volta para free e limpa expiração
            supabase.table("users").update({
                "plan": "free",
                "plan_expires_at": None,
                "msgs_sent": 0,
                "last_reset": date.today().isoformat()
            }).eq("telegram_id", telegram_id).execute()
            return "free"
        
        return user["plan"]
    except Exception as e:
        print(f"⚠️ Erro ao verificar expiração: {e}")
        return "free"

def get_or_create_user(telegram_id: int, username: str, full_name: str = None):
    # Garante que plano expirado seja downgraded antes de retornar
    current_plan = check_and_downgrade_expired(telegram_id)
    
    try:
        response = supabase.table("users").select("*").eq("telegram_id", telegram_id).execute()
        
        if response.data and len(response.data) > 0:
            user = response.data[0]
            # Atualiza plano se foi downgraded
            if user["plan"] != current_plan:
                user["plan"] = current_plan
            
            # Reseta contagem diária
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
            "plan": current_plan,
            "msgs_sent": 0,
            "last_reset": date.today().isoformat(),
            "plan_expires_at": None
        }
        result = supabase.table("users").insert(new_user).execute()
        return result.data[0] if result.data else new_user
        
    except Exception as e:
        print(f"❌ Erro no db.py (get_or_create_user): {e}")
        return {"telegram_id": telegram_id, "plan": current_plan, "msgs_sent": 0}

def activate_plan(telegram_id: int, plan_key: str, duration_days: int = None):
    """Ativa um plano temporário ou permanente"""
    try:
        expires_at = None
        if duration_days:
            expires_at = (datetime.utcnow() + timedelta(days=duration_days)).isoformat()
            
        supabase.table("users").update({
            "plan": plan_key,
            "plan_expires_at": expires_at,
            "msgs_sent": 0,
            "last_reset": date.today().isoformat()
        }).eq("telegram_id", telegram_id).execute()
        return True
    except Exception as e:
        print(f"❌ Erro ao ativar plano: {e}")
        return False

def can_send_message(telegram_id: int) -> Tuple[bool, str]:
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
    try:
        user = get_or_create_user(telegram_id, "", "")
        limits = get_user_limits(user["plan"])
        active_count = get_active_channels_count(telegram_id)
        
        if active_count >= limits["channels"]:
            return False, f"⚠️ Limite de canais atingido ({active_count}/{limits['channels']}).\nFaça upgrade para adicionar mais!"
        
        existing = supabase.table("user_channels").select("id").eq("telegram_id", telegram_id).eq("channel_id", channel_id).execute()
        if existing.data and len(existing.data) > 0:
            supabase.table("user_channels").update({"is_active": True}).eq("id", existing.data[0]["id"]).execute()
            return True, "✅ Canal reativado!"
        
        result = supabase.table("user_channels").insert({
            "telegram_id": telegram_id,
            "channel_id": channel_id,
            "channel_name": channel_name,
            "channel_type": channel_type
        }).execute()
        return True, "✅ Canal adicionado com sucesso!" if result.data else (False, " Erro ao adicionar canal")
    except Exception as e:
        print(f"❌ Erro ao adicionar canal: {e}")
        return False, f"❌ Erro: {str(e)}"

def remove_user_channel(telegram_id: int, channel_id: str):
    try:
        result = supabase.table("user_channels").update({"is_active": False}).eq("telegram_id", telegram_id).eq("channel_id", channel_id).execute()
        return result.data is not None
    except Exception as e:
        print(f"❌ Erro ao remover canal: {e}")
        return False

def get_user_channels(telegram_id: int):
    try:
        response = supabase.table("user_channels").select("*").eq("telegram_id", telegram_id).eq("is_active", True).execute()
        return response.data if response.data else []
    except Exception as e:
        print(f"❌ Erro ao listar canais: {e}")
        return []

def get_active_channels_count(telegram_id: int) -> int:
    try:
        channels = get_user_channels(telegram_id)
        return len(channels)
    except:
        return 0

# ==================== FILA & AGENDAMENTOS ====================
def add_to_send_queue(telegram_id: int, content: str, target_channels: list, media_url: str = None, media_type: str = "none", caption: str = None):
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
    try:
        response = supabase.table("send_queue").select("*").eq("status", "pending").order("created_at", desc=False).limit(limit).execute()
        return response.data if response.data else []
    except Exception as e:
        print(f"❌ Erro ao buscar fila: {e}")
        return []

def update_queue_status(queue_id: int, status: str, error: str = None):
    try:
        update_data = {"status": status, "processed_at": datetime.utcnow().isoformat()}
        if error:
            queue_data = supabase.table("send_queue").select("retry_count").eq("id", queue_id).execute()
            if queue_data.data and len(queue_data.data) > 0:
                update_data["retry_count"] = queue_data.data[0].get("retry_count", 0) + 1
        supabase.table("send_queue").update(update_data).eq("id", queue_id).execute()
    except Exception as e:
        print(f"❌ Erro ao atualizar fila: {e}")

def log_message(telegram_id: int, content: str, channel: str = None, status: str = "sent"):
    try:
        supabase.table("send_logs").insert({
            "telegram_id": telegram_id,
            "message_content": content[:500] if content else "",
            "channel_name": channel,
            "status": status
        }).execute()
    except Exception as e:
        print(f"⚠️ Erro ao logar mensagem: {e}")

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

def get_pending_scheduled():
    try:
        now = datetime.utcnow().isoformat()
        response = supabase.table("scheduled_messages").select("*").eq("status", "pending").lte("send_at", now).execute()
        return response.data if response.data else []
    except Exception as e:
        print(f"❌ Erro ao buscar agendamentos: {e}")
        return []