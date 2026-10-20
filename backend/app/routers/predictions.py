from typing import Optional
import numpy as np
from fastapi import APIRouter, Depends
from sklearn.linear_model import LinearRegression
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db

router = APIRouter(prefix="/api/predictions", tags=["predictions"])


@router.get("")
def forecast(
    building: Optional[str] = None,
    method: str = "linear",
    db: Session = Depends(get_db),
):
    month_expr = func.to_char(models.UsageLog.date, "YYYY-MM")
    q = db.query(month_expr.label("month"), func.avg(models.UsageLog.utilization_percentage))
    if building:
        q = q.join(models.Resource, models.Resource.room_id == models.UsageLog.room_id)
        q = q.filter(models.Resource.building_name == building)
    rows = q.group_by("month").order_by("month").all()

    months = [m for m, _ in rows]
    values = np.array([float(v) for _, v in rows], dtype=float)

    if len(values) < 2:
        return {"months": months, "historical": values.tolist(), "forecast": [], "method": method}

    if method == "movavg":
        window = values[-3:] if len(values) >= 3 else values
        avg = float(window.mean())
        forecast_vals = [round(avg, 1)] * 3
    else:
        X = np.arange(len(values)).reshape(-1, 1)
        model = LinearRegression().fit(X, values)
        future_X = np.arange(len(values), len(values) + 3).reshape(-1, 1)
        preds = model.predict(future_X)
        forecast_vals = [round(float(min(100, max(0, p))), 1) for p in preds]

    return {
        "months": months,
        "historical": [round(float(v), 1) for v in values],
        "forecast": forecast_vals,
        "method": method,
        "building": building or "campus-wide",
    }
