"""AI Insights: turns the twin's data into plain-language findings and actions.

Everything is computed server-side from the database (no external API keys):
a scikit-learn regression for the forecast, plus statistical rules over
utilization, energy, maintenance and timetable data. Each section is isolated,
so one failing section can never blank the whole page.
"""
import logging
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends
from sklearn.linear_model import LinearRegression
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..security import get_current_user

log = logging.getLogger("campustwin.insights")
router = APIRouter(prefix="/api/insights", tags=["insights"])

UNDER, OVER = 35.0, 80.0


def _ins(severity, category, title, detail, action=None):
    return {"severity": severity, "category": category, "title": title, "detail": detail, "action": action}


def _forecast(months, values):
    if len(values) < 3:
        return None
    X = np.arange(len(values)).reshape(-1, 1)
    model = LinearRegression().fit(X, values)
    preds = model.predict(np.arange(len(values), len(values) + 3).reshape(-1, 1))
    return float(model.coef_[0]), [round(float(min(100, max(0, p))), 1) for p in preds], float(model.score(X, values))


def _trend_insights(db):
    out, chart = [], None
    month = func.to_char(models.UsageLog.date, "YYYY-MM")
    rows = db.query(month, func.avg(models.UsageLog.utilization_percentage)).group_by(month).order_by(month).all()
    months, vals = [r[0] for r in rows], np.array([float(r[1]) for r in rows])
    f = _forecast(months, vals)
    if f:
        slope, preds, r2 = f
        chart = {"months": months, "historical": [round(float(v), 1) for v in vals], "forecast": preds}
        direction = "rising" if slope > 0.3 else "falling" if slope < -0.3 else "flat"
        out.append(_ins(
            "warning" if (direction == "rising" and preds[-1] > OVER - 10) else "info", "Forecast",
            f"Campus utilization is {direction} ({slope:+.2f} pts/month)",
            f"Latest month: {vals[-1]:.1f}%. A linear model projects {preds[0]}% → {preds[-1]}% over the next 3 months "
            f"(fit R² {r2:.2f}{' - a weak trend, treat as roughly stable' if r2 < 0.3 else ''}).",
            "Review capacity before the peak." if direction == "rising" else None))
        spread = vals.max() - vals.min()
        if spread < 3:
            out.append(_ins("info", "Forecast", "Demand is very steady month to month",
                            f"Monthly averages stay within {spread:.1f} points, so seasonal planning is unlikely to help; "
                            "gains must come from re-allocating rooms, not from timing."))
    return out, chart


def _pattern_insights(db):
    out = []
    slots = db.query(models.UsageLog.time_slot, func.avg(models.UsageLog.utilization_percentage)) \
        .group_by(models.UsageLog.time_slot).all()
    if len(slots) >= 2:
        s = sorted(slots, key=lambda x: x[1])
        lo, hi = s[0], s[-1]
        out.append(_ins("info", "Patterns", f"Busiest slot {hi[0]}, quietest {lo[0]}",
                        f"Average utilization is {hi[1]:.1f}% at {hi[0]} versus {lo[1]:.1f}% at {lo[0]}.",
                        f"Shift flexible sessions into {lo[0]} to relieve {hi[0]}." if hi[1] - lo[1] > 2 else None))
    days = db.query(models.UsageLog.day_of_week, func.avg(models.UsageLog.utilization_percentage)) \
        .group_by(models.UsageLog.day_of_week).all()
    if len(days) >= 2:
        d = sorted(days, key=lambda x: x[1])
        out.append(_ins("info", "Patterns", f"{d[-1][0]} is the busiest day, {d[0][0]} the quietest",
                        f"{d[-1][0]} averages {d[-1][1]:.1f}% utilization and {d[0][0]} {d[0][1]:.1f}%."))
    return out


def _resource_insights(db):
    out, moves = [], []
    res = pd.read_sql(db.query(models.Resource).statement, db.bind)
    if res.empty:
        return out, moves
    total = len(res)
    over, under = res[res.avg_utilization > OVER], res[res.avg_utilization < UNDER]
    out.append(_ins("critical" if len(over) / total > .15 else "warning" if len(over) else "positive", "Utilization",
                    f"{len(over)} rooms are over {OVER:.0f}% utilized",
                    f"That is {len(over) / total:.0%} of {total:,} resources; they have little headroom for new bookings.",
                    "Move flexible sessions to the under-used rooms listed below." if len(over) else None))
    out.append(_ins("warning" if len(under) / total > .1 else "info", "Utilization",
                    f"{len(under)} rooms are under {UNDER:.0f}% utilized",
                    f"{len(under) / total:.0%} of resources are barely used - candidates for consolidation or re-purposing."))

    b = res.groupby("building_name").avg_utilization.mean().sort_values()
    if len(b) >= 2:
        out.append(_ins("info", "Buildings", f"{b.index[-1]} is under most pressure ({b.iloc[-1]:.1f}%)",
                        f"{b.index[0]} has the most slack at {b.iloc[0]:.1f}% - a {b.iloc[-1] - b.iloc[0]:.1f}-point gap."))

    # Reallocation suggestions: pair hot rooms with idle rooms of the same type.
    usable = res[res.maintenance_status != "Under Repair"]
    for _, hot in over.sort_values("avg_utilization", ascending=False).iterrows():
        pool = usable[(usable.room_type == hot.room_type) & (usable.avg_utilization < UNDER)
                      & (usable.capacity >= hot.capacity * 0.8)]
        if pool.empty:
            continue
        same = pool[pool.building_name == hot.building_name]
        cand = (same if not same.empty else pool).sort_values("avg_utilization").iloc[0]
        moves.append({"from_room": hot.room_id, "from_util": round(float(hot.avg_utilization), 1),
                      "to_room": cand.room_id, "to_util": round(float(cand.avg_utilization), 1),
                      "room_type": hot.room_type, "building": hot.building_name, "to_building": cand.building_name,
                      "same_building": bool(cand.building_name == hot.building_name)})
        if len(moves) >= 8:
            break
    if moves:
        out.append(_ins("positive", "Optimization", f"{len(moves)} concrete re-allocations found",
                        "Each pairs an over-used room with an idle room of the same type and similar capacity.",
                        "See the re-allocation table below."))

    # Energy: heavy consumers relative to how much they are used.
    r = res[res.avg_utilization > 0].copy()
    r["kwh_per_util"] = r.avg_energy_kwh / r.avg_utilization
    wasteful = r[(r.avg_utilization < UNDER)].sort_values("avg_energy_kwh", ascending=False).head(5)
    if not wasteful.empty:
        out.append(_ins("warning", "Energy", "Quiet rooms that still draw a lot of power",
                        "Top examples (avg kWh/session at low utilization): " +
                        ", ".join(f"{x.room_id} ({x.avg_energy_kwh:.0f} kWh @ {x.avg_utilization:.0f}%)" for x in wasteful.itertuples()),
                        "Check HVAC/lighting schedules for these rooms."))

    repair = res[res.maintenance_status == "Under Repair"]
    risky = res[(res.maintenance_status.isin(["Under Repair", "Needs Inspection"])) & (res.avg_utilization > OVER)]
    out.append(_ins("warning" if len(repair) else "positive", "Maintenance",
                    f"{len(repair)} rooms are under repair; {len(risky)} busy rooms are flagged for work",
                    f"{len(repair) / total:.0%} of capacity is out of service. "
                    f"{len(risky)} rooms are both heavily used and flagged (repair/inspection).",
                    "Prioritise repairs on heavily used rooms first." if len(risky) else None))
    return out, moves


def _timetable_insights(db, user):
    out = []
    q = db.query(models.Timetable)
    if user.role != "administrator":
        q = q.filter(models.Timetable.uploaded_by == user.id)
    tts = q.all()
    if not tts:
        return out
    pending = [t for t in tts if t.status == "Pending"]
    if pending:
        who = "waiting for your approval" if user.role == "administrator" else "waiting for administrator approval"
        out.append(_ins("warning", "Timetables", f"{len(pending)} timetable(s) {who}",
                        "Rooms and labs are only booked after approval: " + ", ".join(t.name for t in pending[:4]),
                        "Open Timetables to review." if user.role == "administrator" else None))
    approved_ids = [t.id for t in tts if t.status == "Approved"]
    if approved_ids:
        ents = db.query(models.TimetableEntry).filter(models.TimetableEntry.timetable_id.in_(approved_ids)).all()
        bad = [e for e in ents if e.status == "Unallocated"]
        moved = [e for e in ents if e.status == "Reallocated"]
        if bad:
            out.append(_ins("critical", "Timetables", f"{len(bad)} approved session(s) have no room",
                            "No suitable room was free for every week: " + ", ".join(f"{e.subject} ({e.class_name})" for e in bad[:4])))
        if moved:
            out.append(_ins("info", "Timetables", f"{len(moved)} session(s) moved to a different room",
                            "The requested room was unavailable so a free alternative was booked."))
        if not bad:
            out.append(_ins("positive", "Timetables", f"All {len(ents)} approved sessions have a room",
                            "Every class and lab in approved timetables is allocated and booked."))
    warns = db.query(models.TimetableEntry).join(models.Timetable).filter(
        models.Timetable.status == "Pending", models.TimetableEntry.warning.like("%Clash%"))
    if user.role != "administrator":
        warns = warns.filter(models.Timetable.uploaded_by == user.id)
    n = warns.count()
    if n:
        out.append(_ins("warning", "Timetables", f"{n} pending session(s) contain a clash",
                        "A faculty member, class or room appears twice at the same time. Fix before approval."))
    return out


@router.get("")
def get_insights(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    insights, forecast, moves, errors = [], None, [], []
    for name, fn in (
        ("trend", lambda: _trend_insights(db)),
        ("patterns", lambda: _pattern_insights(db)),
        ("resources", lambda: _resource_insights(db)),
        ("timetables", lambda: _timetable_insights(db, user)),
    ):
        try:
            res = fn()
            if name == "trend":
                insights += res[0]
                forecast = res[1]
            elif name == "resources":
                insights += res[0]
                moves = res[1]
            else:
                insights += res
        except Exception as exc:  # one broken section must not blank the page
            log.exception("insight section %s failed", name)
            db.rollback()
            errors.append(f"{name}: {exc.__class__.__name__}")
    order = {"critical": 0, "warning": 1, "positive": 2, "info": 3}
    insights.sort(key=lambda i: order.get(i["severity"], 9))
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "insights": insights,
        "forecast": forecast,
        "reallocations": moves,
        "summary": {s: sum(1 for i in insights if i["severity"] == s) for s in order},
        "partial_errors": errors,
    }
