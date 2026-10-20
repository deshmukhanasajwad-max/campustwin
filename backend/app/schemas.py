from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel, EmailStr


class UserCreate(BaseModel):
    name: str
    email: EmailStr
    password: str
    role: str = "student"
    department: Optional[str] = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    name: str
    role: str
    email: EmailStr


class ResourceOut(BaseModel):
    room_id: str
    room_type: str
    building_name: str
    department: str
    capacity: int
    maintenance_status: str
    booking_status: str
    avg_utilization: float
    avg_energy_kwh: float

    class Config:
        from_attributes = True


class ResourcePage(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[ResourceOut]


class BookingCreate(BaseModel):
    room_id: Optional[str] = None
    building_name: Optional[str] = None
    room_type: Optional[str] = None
    date: date
    time_slot: str
    purpose: str = "General use"


class BookingOut(BaseModel):
    id: int
    room_id: str
    date: date
    time_slot: str
    purpose: str
    status: str
    source: Optional[str] = "manual"
    created_at: datetime

    class Config:
        from_attributes = True
