import csv
import io
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db

router = APIRouter(prefix="/api/reports", tags=["reports"])


def _csv_response(rows: list[dict], filename: str) -> StreamingResponse:
    buf = io.StringIO()
    if rows:
        writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}.csv"},
    )


@router.get("/inventory")
def inventory_report(db: Session = Depends(get_db)):
    resources = db.query(models.Resource).all()
    rows = [{
        "Room_ID": r.room_id, "Room_Type": r.room_type, "Building": r.building_name,
        "Department": r.department, "Capacity": r.capacity, "Avg_Utilization": r.avg_utilization,
        "Avg_Energy_kWh": r.avg_energy_kwh, "Maintenance_Status": r.maintenance_status,
        "Booking_Status": r.booking_status,
    } for r in resources]
    return _csv_response(rows, "inventory_report")


@router.get("/alerts")
def alerts_report(db: Session = Depends(get_db)):
    under = db.query(models.Resource).filter(models.Resource.avg_utilization < 35).all()
    over = db.query(models.Resource).filter(models.Resource.avg_utilization > 80).all()
    rows = []
    for r in under:
        rows.append({"Room_ID": r.room_id, "Building": r.building_name, "Avg_Utilization": r.avg_utilization, "Alert_Type": "Underutilized"})
    for r in over:
        rows.append({"Room_ID": r.room_id, "Building": r.building_name, "Avg_Utilization": r.avg_utilization, "Alert_Type": "Overutilized"})
    return _csv_response(rows, "alerts_report")
