"""Telegram notification service — fully async, never blocks the booking flow."""
import httpx

API_BASE = "https://api.telegram.org/bot{token}"


async def verify_bot_token(token: str) -> dict:
    """Validate token via getMe. Returns bot info or raises on failure."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(API_BASE.format(token=token) + "/getMe")
        data = resp.json()
        if not data.get("ok"):
            raise ValueError(data.get("description", "Invalid bot token"))
        return data["result"]


async def send_telegram_message(token: str, chat_id: str, text: str) -> bool:
    """Send an HTML-formatted message. Failures are swallowed — a broken
    Telegram config must never break the booking itself."""
    if not token or not chat_id:
        return False
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                API_BASE.format(token=token) + "/sendMessage",
                json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            )
            return resp.status_code == 200
    except Exception:
        return False


def format_booking_message(company: str, client_name: str, phone: str,
                           service_name: str, price: float, start, duration: int) -> str:
    return (
        f"💈 <b>New booking — {company}</b>\n\n"
        f"👤 Client: <b>{client_name}</b>\n"
        f"📞 Phone: <code>{phone}</code>\n"
        f"✂️ Service: {service_name} (${price:.0f}, {duration} min)\n"
        f"🗓 When: <b>{start.strftime('%d %b %Y, %H:%M')}</b>\n\n"
        f"Open the admin panel to confirm or cancel."
    )
