from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, func
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db

router = APIRouter(prefix="/api/resources", tags=["resources"])


@router.get("", response_model=schemas.ResourcePage)
def list_resources(
    search: Optional[str] = None,
    building: Optional[str] = None,
    room_type: Optional[str] = None,
    status: Optional[str] = Query(None, description="under | normal | over"),
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
):
    q = db.query(models.Resource)
    if search:
        like = f"%{search}%"
        q = q.filter(or_(
            models.Resource.room_id.ilike(like),
            models.Resource.building_name.ilike(like),
            models.Resource.department.ilike(like),
        ))
    if building:
        q = q.filter(models.Resource.building_name == building)
    if room_type:
        q = q.filter(models.Resource.room_type == room_type)
    if status == "under":
        q = q.filter(models.Resource.avg_utilization < 35)
    elif status == "normal":
        q = q.filter(models.Resource.avg_utilization >= 35, models.Resource.avg_utilization <= 80)
    elif status == "over":
        q = q.filter(models.Resource.avg_utilization > 80)

    total = q.count()
    items = (
        q.order_by(models.Resource.avg_utilization.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return schemas.ResourcePage(total=total, page=page, page_size=page_size, items=items)


@router.get("/filters")
def get_filter_options(db: Session = Depends(get_db)):
    buildings = [r[0] for r in db.query(models.Resource.building_name).distinct().order_by(models.Resource.building_name)]
    room_types = [r[0] for r in db.query(models.Resource.room_type).distinct().order_by(models.Resource.room_type)]
    departments = [r[0] for r in db.query(models.Resource.department).distinct().order_by(models.Resource.department)]
    return {"buildings": buildings, "room_types": room_types, "departments": departments}


@router.get("/{room_id}")
def get_resource(room_id: str, db: Session = Depends(get_db)):
    res = db.query(models.Resource).filter(models.Resource.room_id == room_id).first()
    if not res:
        raise HTTPException(status_code=404, detail="Resource not found")
    recent = (
        db.query(models.UsageLog)
        .filter(models.UsageLog.room_id == room_id)
        .order_by(models.UsageLog.date.desc())
        .limit(10)
        .all()
    )
    return {
        "resource": schemas.ResourceOut.model_validate(res),
        "recent_usage": [
            {
                "date": str(u.date), "time_slot": u.time_slot, "utilization_percentage": u.utilization_percentage,
                "energy_consumption_kwh": u.energy_consumption_kwh, "purpose": u.purpose,
            } for u in recent
        ],
    }
