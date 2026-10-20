from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..security import get_current_user, require_admin

router = APIRouter(prefix="/api/bookings", tags=["bookings"])


@router.post("", response_model=schemas.BookingOut)
def create_booking(
    payload: schemas.BookingCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    # Resolve a candidate room: either an exact room_id, or the
    # lowest-utilization non-maintenance room matching building/type.
    room = None
    if payload.room_id:
        room = db.query(models.Resource).filter(models.Resource.room_id == payload.room_id).first()
        if not room:
            raise HTTPException(status_code=404, detail="Resource not found")
    else:
        q = db.query(models.Resource).filter(models.Resource.maintenance_status != "Under Repair")
        if payload.building_name:
            q = q.filter(models.Resource.building_name == payload.building_name)
        if payload.room_type:
            q = q.filter(models.Resource.room_type == payload.room_type)
        room = q.order_by(models.Resource.avg_utilization.asc()).first()
        if not room:
            raise HTTPException(status_code=404, detail="No matching resource available for that building/type")

    if room.maintenance_status == "Under Repair":
        raise HTTPException(status_code=409, detail=f"{room.room_id} is under repair and cannot be booked")

    # Real conflict check: same room, same date, same time slot, active status.
    conflict = (
        db.query(models.Booking)
        .filter(
            models.Booking.room_id == room.room_id,
            models.Booking.date == payload.date,
            models.Booking.time_slot == payload.time_slot,
            models.Booking.status != "Cancelled",
        )
        .first()
    )
    if conflict:
        raise HTTPException(status_code=409, detail=f"{room.room_id} is already booked on {payload.date} at {payload.time_slot}")

    booking = models.Booking(
        user_id=user.id,
        room_id=room.room_id,
        date=payload.date,
        time_slot=payload.time_slot,
        purpose=payload.purpose,
        status="Confirmed",
    )
    db.add(booking)
    db.commit()
    db.refresh(booking)
    return booking


@router.get("/mine", response_model=list[schemas.BookingOut])
def my_bookings(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    return (
        db.query(models.Booking)
        .filter(models.Booking.user_id == user.id, models.Booking.source != "timetable")
        .order_by(models.Booking.created_at.desc())
        .all()
    )


@router.get("", response_model=list[schemas.BookingOut])
def all_bookings(db: Session = Depends(get_db), _admin: models.User = Depends(require_admin)):
    return db.query(models.Booking).order_by(models.Booking.created_at.desc()).limit(200).all()


@router.delete("/{booking_id}")
def cancel_booking(booking_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    booking = db.query(models.Booking).filter(models.Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    if booking.user_id != user.id and user.role != "administrator":
        raise HTTPException(status_code=403, detail="Not your booking")
    booking.status = "Cancelled"
    db.commit()
    return {"ok": True}
