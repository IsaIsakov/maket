"""
Database layer: SQLite via SQLAlchemy 2.0
Models: Service, Booking, Setting (key-value store for site config)
"""
import os
from datetime import datetime

from sqlalchemy import (Boolean, Column, DateTime, Float, ForeignKey, Integer,
                        String, Text, create_engine)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "salon.db")

engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"check_same_thread": False},  # required for FastAPI multi-threading
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


class Service(Base):
    __tablename__ = "services"

    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False)
    description = Column(String(300), default="")
    price = Column(Float, nullable=False, default=0.0)
    duration_min = Column(Integer, nullable=False, default=60)
    active = Column(Boolean, default=True)  # soft delete keeps booking history intact

    bookings = relationship("Booking", back_populates="service")


class Booking(Base):
    __tablename__ = "bookings"

    id = Column(Integer, primary_key=True)
    client_name = Column(String(120), nullable=False)
    phone = Column(String(40), nullable=False)
    service_id = Column(Integer, ForeignKey("services.id"), nullable=False)
    start_time = Column(DateTime, nullable=False)
    end_time = Column(DateTime, nullable=False)
    status = Column(String(20), default="New")  # New / Confirmed / Completed / Cancelled
    created_at = Column(DateTime, default=datetime.utcnow)

    service = relationship("Service", back_populates="bookings")


class Setting(Base):
    """Simple key-value table for site configuration (no migrations needed)."""
    __tablename__ = "settings"

    key = Column(String(60), primary_key=True)
    value = Column(Text, default="")


DEFAULT_SETTINGS = {
    "company_name": "Glamour Studio",
    "description": "Premium beauty & barber services. Book online in 30 seconds — no phone calls, no waiting.",
    "opening_hours": "09:00-20:00",   # format "HH:MM-HH:MM"
    "slot_step": "30",                # minutes between offered slots
    "admin_password": "admin123",     # CHANGE THIS after first login!
    "telegram_token": "",
    "telegram_chat_id": "",
    "logo_url": "",
}

SEED_SERVICES = [
    ("Men's Haircut", "Classic cut, wash & styling", 30.0, 45),
    ("Beard Trim & Shape", "Hot towel, razor finish", 20.0, 30),
    ("Women's Cut & Blowout", "Cut, wash & professional blowout", 45.0, 60),
    ("Full Coloring", "Premium dye, toner & treatment", 90.0, 120),
    ("Manicure", "Shape, cuticle care & polish", 35.0, 60),
]


def get_setting(db, key: str, default: str = "") -> str:
    row = db.query(Setting).filter(Setting.key == key).first()
    return row.value if row else DEFAULT_SETTINGS.get(key, default)


def set_setting(db, key: str, value: str):
    row = db.query(Setting).filter(Setting.key == key).first()
    if row:
        row.value = value
    else:
        db.add(Setting(key=key, value=value))
    db.commit()


def init_db():
    """Create tables and seed default data on first run."""
    Base.metadata.create_all(engine)
    db = SessionLocal()
    try:
        for k, v in DEFAULT_SETTINGS.items():
            if not db.query(Setting).filter(Setting.key == k).first():
                db.add(Setting(key=k, value=v))
        if db.query(Service).count() == 0:
            for name, desc, price, dur in SEED_SERVICES:
                db.add(Service(name=name, description=desc, price=price, duration_min=dur))
        db.commit()
    finally:
        db.close()
