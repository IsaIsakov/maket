"""Pydantic schemas — strict input validation at the API boundary."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class BookingCreate(BaseModel):
    client_name: str = Field(min_length=2, max_length=120)
    phone: str = Field(min_length=7, max_length=25)
    service_id: int = Field(gt=0)
    start_time: datetime  # ISO 8601, e.g. "2026-10-15T14:00"


class BookingOut(BaseModel):
    id: int
    client_name: str
    phone: str
    service_id: int
    service_name: str
    start_time: datetime
    end_time: datetime
    status: str
    created_at: datetime


class ServiceIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    description: str = Field(default="", max_length=300)
    price: float = Field(ge=0)
    duration_min: int = Field(ge=10, le=480)


class ServiceOut(BaseModel):
    id: int
    name: str
    description: str
    price: float
    duration_min: int
    active: bool


class SiteSettingsUpdate(BaseModel):
    company_name: Optional[str] = Field(default=None, max_length=120)
    description: Optional[str] = Field(default=None, max_length=1000)
    opening_hours: Optional[str] = Field(default=None, pattern=r"^\d{2}:\d{2}-\d{2}:\d{2}$")
    slot_step: Optional[int] = Field(default=None, ge=10, le=120)


class TelegramSettings(BaseModel):
    telegram_token: str = Field(default="", max_length=100)
    telegram_chat_id: str = Field(default="", max_length=40)


class LoginIn(BaseModel):
    password: str = Field(min_length=1, max_length=100)


class PasswordChange(BaseModel):
    old_password: str = Field(min_length=1, max_length=100)
    new_password: str = Field(min_length=6, max_length=100)


class StatusUpdate(BaseModel):
    status: str = Field(pattern="^(New|Confirmed|Completed|Cancelled)$")
