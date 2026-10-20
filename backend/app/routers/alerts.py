from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


@router.get("")
def get_alerts(
    under_threshold: float = Query(35),
    over_threshold: float = Query(80),
    db: Session = Depends(get_db),
):
    underutilized = (
        db.query(models.Resource)
        .filter(models.Resource.avg_utilization < under_threshold)
        .order_by(models.Resource.avg_utilization.asc())
        .limit(20)
        .all()
    )
    overutilized = (
        db.query(models.Resource)
        .filter(models.Resource.avg_utilization > over_threshold)
        .order_by(models.Resource.avg_utilization.desc())
        .limit(20)
        .all()
    )
    maintenance = (
        db.query(models.Resource)
        .filter(models.Resource.maintenance_status.in_(["Under Repair", "Needs Inspection"]))
        .limit(30)
        .all()
    )
    return {
        "underutilized": [schemas.ResourceOut.model_validate(r) for r in underutilized],
        "overutilized": [schemas.ResourceOut.model_validate(r) for r in overutilized],
        "maintenance": [schemas.ResourceOut.model_validate(r) for r in maintenance],
        "counts": {
            "underutilized": db.query(models.Resource).filter(models.Resource.avg_utilization < under_threshold).count(),
            "overutilized": db.query(models.Resource).filter(models.Resource.avg_utilization > over_threshold).count(),
            "maintenance": db.query(models.Resource).filter(
                models.Resource.maintenance_status.in_(["Under Repair", "Needs Inspection"])
            ).count(),
        },
    }
