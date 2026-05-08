import os
from datetime import date
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

supabase: Client = create_client(
    os.getenv("SUPABASE_URL"), 
    os.getenv("SUPABASE_KEY")
)

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
        print(f"❌ Erro no db.py: {e}")
        return {"telegram_id": telegram_id, "plan": "free", "msgs_sent": 0}

def get_user_limits(plan: str) -> dict:
    return {
        "free": {"daily_msgs": 5, "channels": 1, "schedule": False},
        "starter": {"daily_msgs": 50, "channels": 5, "schedule": True},
        "pro": {"daily_msgs": 500, "channels": 20, "schedule": True},
        "business": {"daily_msgs": 9999, "channels": 999, "schedule": True}
    }.get(plan, {"daily_msgs": 5, "channels": 1, "schedule": False})

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

def log_message(telegram_id: int, content: str, channel: str = None):
    try:
        supabase.table("send_logs").insert({
            "telegram_id": telegram_id,
            "message_content": content[:500],
            "channel_name": channel
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

def get_pending_scheduled() -> list:
    from datetime import datetime
    now = datetime.utcnow().isoformat()
    
    response = supabase.table("scheduled_messages").select("""
        *,
        users ( plan, username )
    """).eq("status", "pending").lte("send_at", now).execute()
    
    return response.data if response.data else []