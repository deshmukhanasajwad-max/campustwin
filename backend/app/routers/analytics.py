from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get("/overview")
def overview(db: Session = Depends(get_db)):
    total_rooms = db.query(models.Resource).count()
    avg_util = db.query(func.avg(models.Resource.avg_utilization)).scalar() or 0
    total_energy = db.query(func.sum(models.UsageLog.energy_consumption_kwh)).scalar() or 0
    available = db.query(models.Resource).filter(models.Resource.booking_status == "Available").count()
    booked = db.query(models.Resource).filter(models.Resource.booking_status == "Booked").count()
    maint = db.query(models.Resource).filter(
        models.Resource.maintenance_status.in_(["Under Repair", "Needs Inspection"])
    ).count()
    buildings = db.query(func.count(func.distinct(models.Resource.building_name))).scalar() or 0
    return {
        "total_rooms": total_rooms,
        "buildings": buildings,
        "avg_utilization": round(float(avg_util), 1),
        "total_energy_kwh": round(float(total_energy), 0),
        "available": available,
        "booked": booked,
        "maintenance_flags": maint,
    }


@router.get("/by-building")
def by_building(db: Session = Depends(get_db)):
    rows = (
        db.query(models.Resource.building_name, func.avg(models.Resource.avg_utilization))
        .group_by(models.Resource.building_name)
        .order_by(func.avg(models.Resource.avg_utilization).desc())
        .all()
    )
    return {name: round(float(val), 1) for name, val in rows}


@router.get("/by-room-type")
def by_room_type(db: Session = Depends(get_db)):
    rows = (
        db.query(models.Resource.room_type, func.avg(models.Resource.avg_utilization))
        .group_by(models.Resource.room_type)
        .order_by(func.avg(models.Resource.avg_utilization).desc())
        .all()
    )
    return {name: round(float(val), 1) for name, val in rows}


@router.get("/by-department")
def by_department(db: Session = Depends(get_db)):
    rows = (
        db.query(models.Resource.department, func.avg(models.Resource.avg_utilization))
        .group_by(models.Resource.department)
        .order_by(func.avg(models.Resource.avg_utilization).desc())
        .all()
    )
    return {name: round(float(val), 1) for name, val in rows}


@router.get("/monthly")
def monthly_trend(db: Session = Depends(get_db)):
    month_expr = func.to_char(models.UsageLog.date, "YYYY-MM")
    rows = (
        db.query(
            month_expr.label("month"),
            func.avg(models.UsageLog.utilization_percentage),
            func.sum(models.UsageLog.energy_consumption_kwh),
        )
        .group_by("month")
        .order_by("month")
        .all()
    )
    return [
        {"month": m, "avg_util": round(float(u), 1), "energy": round(float(e), 1)}
        for m, u, e in rows
    ]


@router.get("/by-dow")
def by_day_of_week(db: Session = Depends(get_db)):
    order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    rows = (
        db.query(models.UsageLog.day_of_week, func.avg(models.UsageLog.utilization_percentage))
        .group_by(models.UsageLog.day_of_week)
        .all()
    )
    d = {name: round(float(val), 1) for name, val in rows}
    return {day: d.get(day, 0) for day in order}


@router.get("/by-timeslot")
def by_timeslot(db: Session = Depends(get_db)):
    rows = (
        db.query(models.UsageLog.time_slot, func.avg(models.UsageLog.utilization_percentage))
        .group_by(models.UsageLog.time_slot)
        .order_by(models.UsageLog.time_slot)
        .all()
    )
    return {slot: round(float(val), 1) for slot, val in rows}


@router.get("/booking-status")
def booking_status_dist(db: Session = Depends(get_db)):
    rows = (
        db.query(models.UsageLog.booking_status, func.count(models.UsageLog.id))
        .group_by(models.UsageLog.booking_status)
        .all()
    )
    return {name: count for name, count in rows}
