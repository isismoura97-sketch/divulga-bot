import os
from dotenv import load_dotenv
import httpx

load_dotenv()

token = os.getenv("TELEGRAM_BOT_TOKEN")
print(f"Token carregado: {token}")

# Testa diretamente na API do Telegram
url = f"https://api.telegram.org/bot{token}/getMe"
response = httpx.get(url)

if response.status_code == 200:
    print("✅ Token VÁLIDO!")
    print(f"Bot: {response.json()['result']}")
else:
    print(f"❌ Token INVÁLIDO! Erro: {response.json()}")