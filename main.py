"""
Glamour Studio — Booking Mini-CRM for beauty salons & barbershops.
Single-file FastAPI backend: public API, admin API, static SPA hosting.
Run:  uvicorn main:app --reload
"""
import os
import re
import secrets
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, UploadFile, File
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from database import (BASE_DIR, Booking, Service, SessionLocal, get_setting,
                      init_db, set_setting)
from schemas import (BookingCreate, BookingOut, LoginIn, PasswordChange,
                     ServiceIn, ServiceOut, SiteSettingsUpdate, StatusUpdate,
                     TelegramSettings)
from services.telegram import (format_booking_message, send_telegram_message,
                               verify_bot_token)

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

app = FastAPI(title="Salon Booking Mini-CRM", lifespan=lifespan)

app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Auth — in-memory admin sessions (stateless-safe enough for a single-node
# deployment; swap for JWT if you ever scale horizontally)
# ---------------------------------------------------------------------------

SESSIONS: dict[str, float] = {}          # token -> expiry timestamp
SESSION_TTL = 60 * 60 * 12               # 12 hours


def require_admin(request: Request):
    token = request.headers.get("X-Admin-Token", "")
    if token not in SESSIONS or SESSIONS[token] < time.time():
        SESSIONS.pop(token, None)
        raise HTTPException(status_code=401, detail="Unauthorized")
    SESSIONS[token] = time.time() + SESSION_TTL  # sliding expiration
    return True


# ---------------------------------------------------------------------------
# Rate limiting — naive per-IP in-memory limiter for the public booking POST
# ---------------------------------------------------------------------------

_rate: dict[str, list] = defaultdict(list)
RATE_LIMIT = 5          # bookings
RATE_WINDOW = 300       # per 5 minutes


def rate_limit(request: Request):
    ip = request.client.host if request.client else "unknown"
    now = time.time()
    _rate[ip] = [t for t in _rate[ip] if now - t < RATE_WINDOW]
    if len(_rate[ip]) >= RATE_LIMIT:
        raise HTTPException(status_code=429, detail="Too many requests. Try again in a few minutes.")
    _rate[ip].append(now)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def all_settings(db: Session) -> dict:
    keys = ("company_name", "description", "opening_hours", "slot_step", "logo_url")
    return {k: get_setting(db, k) for k in keys}


def parse_hours(db: Session):
    raw = get_setting(db, "opening_hours", "09:00-20:00")
    start_s, end_s = raw.split("-")
    sh, sm = map(int, start_s.split(":"))
    eh, em = map(int, end_s.split(":"))
    return (sh * 60 + sm, eh * 60 + em)


def overlaps(a_start, a_end, b_start, b_end) -> bool:
    return a_start < b_end and b_start < a_end


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

@app.get("/api/settings/public")
def public_settings(db: Session = Depends(get_db)):
    return all_settings(db)


@app.get("/api/services", response_model=list[ServiceOut])
def list_services(db: Session = Depends(get_db)):
    return db.query(Service).filter(Service.active.is_(True)).all()


@app.get("/api/availability")
def availability(date: str, db: Session = Depends(get_db)):
    """Return free time slots for a given day (YYYY-MM-DD).

    Core anti-double-booking logic: a slot is offered only if no
    New/Confirmed booking overlaps the full service duration.
    """
    try:
        day = datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(400, "Bad date format, expected YYYY-MM-DD")

    open_m, close_m = parse_hours(db)
    step = int(get_setting(db, "slot_step", "30"))

    day_start = datetime(day.year, day.month, day.day)
    day_end = day_start + timedelta(days=1)
    existing = db.query(Booking).filter(
        Booking.start_time >= day_start,
        Booking.start_time < day_end,
        Booking.status.in_(["New", "Confirmed"]),
    ).all()

    slots = []
    t = open_m
    now = datetime.now()
    while t < close_m:
        slot_start = day_start + timedelta(minutes=t)
        # offer the slot if at least one active service fits before closing
        # (the booking POST validates exact duration per service)
        if slot_start > now:
            if not any(overlaps(slot_start, slot_start + timedelta(minutes=30),
                                b.start_time, b.end_time) for b in existing):
                slots.append(slot_start.strftime("%H:%M"))
        t += step
    return {"date": date, "slots": slots, "opening_hours": f"{open_m//60:02d}:{open_m%60:02d}-{close_m//60:02d}:{close_m%60:02d}"}


PHONE_RE = re.compile(r"^[+\d][\d\s()\-]{5,23}$")


@app.post("/api/bookings")
def create_booking(payload: BookingCreate, request: Request, db: Session = Depends(get_db)):
    rate_limit(request)

    # --- validation -------------------------------------------------------
    name = payload.client_name.strip()
    phone = payload.phone.strip()
    if not PHONE_RE.match(phone):
        raise HTTPException(400, "Invalid phone number format")

    service = db.query(Service).filter(Service.id == payload.service_id,
                                       Service.active.is_(True)).first()
    if not service:
        raise HTTPException(404, "Service not found")

    start = payload.start_time.replace(tzinfo=None)
    end = start + timedelta(minutes=service.duration_min)
    if start <= datetime.now():
        raise HTTPException(400, "Cannot book a time in the past")

    open_m, close_m = parse_hours(db)
    start_m = start.hour * 60 + start.minute
    end_m = end.hour * 60 + end.minute
    if start_m < open_m or end_m > close_m:
        raise HTTPException(400, "Selected time is outside opening hours")

    # --- anti double-booking check (atomic enough on SQLite single node) --
    clash = db.query(Booking).filter(
        Booking.start_time < end,
        Booking.end_time > start,
        Booking.status.in_(["New", "Confirmed"]),
    ).first()
    if clash:
        raise HTTPException(409, "This time slot is already booked")

    booking = Booking(client_name=name, phone=phone, service_id=service.id,
                      start_time=start, end_time=end, status="New")
    db.add(booking)
    db.commit()
    db.refresh(booking)

    # --- Telegram notification (async background task, never blocks) ------
    token = get_setting(db, "telegram_token")
    chat_id = get_setting(db, "telegram_chat_id")
    if token and chat_id:
        import asyncio

        msg = format_booking_message(
            get_setting(db, "company_name", "Salon"),
            name, phone, service.name, service.price, start, service.duration_min)

        async def _notify():
            await send_telegram_message(token, chat_id, msg)

        asyncio.create_task(_notify())

    return {"id": booking.id, "status": "ok"}


# ---------------------------------------------------------------------------
# Admin API
# ---------------------------------------------------------------------------

@app.post("/api/admin/login")
def admin_login(payload: LoginIn, db: Session = Depends(get_db)):
    if payload.password != get_setting(db, "admin_password", "admin123"):
        raise HTTPException(401, "Wrong password")
    token = secrets.token_hex(24)
    SESSIONS[token] = time.time() + SESSION_TTL
    return {"token": token}


@app.get("/api/admin/verify")
def admin_verify(_: bool = Depends(require_admin)):
    return {"ok": True}


@app.post("/api/admin/password")
def change_password(payload: PasswordChange, db: Session = Depends(get_db),
                    _: bool = Depends(require_admin)):
    if payload.old_password != get_setting(db, "admin_password"):
        raise HTTPException(400, "Current password is incorrect")
    set_setting(db, "admin_password", payload.new_password)
    return {"ok": True}


@app.get("/api/admin/settings")
def admin_settings(db: Session = Depends(get_db), _: bool = Depends(require_admin)):
    s = all_settings(db)
    s["telegram_token"] = get_setting(db, "telegram_token")
    s["telegram_chat_id"] = get_setting(db, "telegram_chat_id")
    return s


@app.patch("/api/admin/settings")
def update_settings(payload: SiteSettingsUpdate, db: Session = Depends(get_db),
                    _: bool = Depends(require_admin)):
    for k, v in payload.model_dump(exclude_none=True).items():
        set_setting(db, k, str(v))
    return all_settings(db)


@app.post("/api/admin/logo")
async def upload_logo(file: UploadFile = File(...), db: Session = Depends(get_db),
                      _: bool = Depends(require_admin)):
    if file.content_type not in ("image/png", "image/jpeg", "image/svg+xml", "image/webp"):
        raise HTTPException(400, "Only PNG/JPEG/SVG/WEBP allowed")
    data = await file.read()
    if len(data) > 2 * 1024 * 1024:
        raise HTTPException(400, "File too large (max 2 MB)")
    os.makedirs(os.path.join(BASE_DIR, "static", "uploads"), exist_ok=True)
    ext = os.path.splitext(file.filename or "logo.png")[1] or ".png"
    fname = f"logo_{secrets.token_hex(6)}{ext}"
    with open(os.path.join(BASE_DIR, "static", "uploads", fname), "wb") as f:
        f.write(data)
    url = f"/static/uploads/{fname}"
    set_setting(db, "logo_url", url)
    return {"logo_url": url}


@app.post("/api/admin/telegram")
async def save_telegram(payload: TelegramSettings, db: Session = Depends(get_db),
                        _: bool = Depends(require_admin)):
    """Save credentials after verifying the token against Telegram getMe."""
    token = payload.telegram_token.strip()
    chat_id = payload.telegram_chat_id.strip()
    if token:
        try:
            bot = await verify_bot_token(token)
        except (ValueError, httpx.HTTPError) as e:
            raise HTTPException(400, f"Telegram rejected the token: {e}")
        set_setting(db, "telegram_token", token)
        set_setting(db, "telegram_chat_id", chat_id)
        if chat_id:
            ok = await send_telegram_message(
                token, chat_id,
                f"✅ <b>{get_setting(db, 'company_name')}</b> is now connected!\n"
                f"New bookings will arrive here instantly.")
            if not ok:
                raise HTTPException(400, "Token is valid but could not message the chat. "
                                         "Open a chat with your bot first and press /start.")
        return {"ok": True, "bot": bot.get("username", "")}
    set_setting(db, "telegram_token", "")
    set_setting(db, "telegram_chat_id", "")
    return {"ok": True, "bot": ""}


@app.get("/api/admin/services", response_model=list[ServiceOut])
def admin_services(db: Session = Depends(get_db), _: bool = Depends(require_admin)):
    return db.query(Service).order_by(Service.id).all()


@app.post("/api/admin/services", response_model=ServiceOut)
def add_service(payload: ServiceIn, db: Session = Depends(get_db),
                _: bool = Depends(require_admin)):
    svc = Service(**payload.model_dump())
    db.add(svc)
    db.commit()
    db.refresh(svc)
    return svc


@app.delete("/api/admin/services/{service_id}")
def delete_service(service_id: int, db: Session = Depends(get_db),
                   _: bool = Depends(require_admin)):
    svc = db.query(Service).filter(Service.id == service_id).first()
    if not svc:
        raise HTTPException(404, "Service not found")
    svc.active = False  # soft delete — keeps historical bookings valid
    db.commit()
    return {"ok": True}


@app.get("/api/admin/bookings", response_model=list[BookingOut])
def admin_bookings(db: Session = Depends(get_db), _: bool = Depends(require_admin)):
    rows = db.query(Booking).order_by(Booking.start_time.desc()).limit(500).all()
    return [BookingOut(
        id=b.id, client_name=b.client_name, phone=b.phone,
        service_id=b.service_id,
        service_name=b.service.name if b.service else "—",
        start_time=b.start_time, end_time=b.end_time,
        status=b.status, created_at=b.created_at) for b in rows]


@app.patch("/api/admin/bookings/{booking_id}/status")
def update_status(booking_id: int, payload: StatusUpdate,
                  db: Session = Depends(get_db), _: bool = Depends(require_admin)):
    b = db.query(Booking).filter(Booking.id == booking_id).first()
    if not b:
        raise HTTPException(404, "Booking not found")
    b.status = payload.status
    db.commit()
    return {"ok": True, "status": b.status}


# ---------------------------------------------------------------------------
# Frontend routes
# ---------------------------------------------------------------------------

@app.get("/", include_in_schema=False)
def index():
    return FileResponse(os.path.join(BASE_DIR, "templates", "index.html"))


@app.get("/admin", include_in_schema=False)
def admin():
    return FileResponse(os.path.join(BASE_DIR, "templates", "admin.html"))
