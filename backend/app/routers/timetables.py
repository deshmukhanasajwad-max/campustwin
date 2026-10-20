"""Timetable upload + administrator approval.

Flow
----
1. Faculty (or an admin) uploads a timetable file (.csv / .xlsx). Every row is
   one weekly session: subject, faculty, class (student group), Class-or-Lab,
   day, time and — optionally — the room/building being requested.
   The timetable is stored as **Pending**. Nothing is booked yet.
2. An administrator reviews it and either approves or rejects it.
3. Only on approval are the requested locations accepted: every session is
   given a room (the requested one when it is free, otherwise the best free
   alternative) and real, conflict-checked bookings are created for each
   occurrence between the timetable's valid-from / valid-to dates.
"""
import csv
import io
import re
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import pandas as pd
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..security import get_current_user, require_admin

router = APIRouter(prefix="/api/timetables", tags=["timetables"])

MAX_UPLOAD_BYTES = 2 * 1024 * 1024
MAX_ROWS = 500
MAX_RANGE_DAYS = 26 * 7

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
DAY_LOOKUP = {d.lower(): d for d in DAYS}
DAY_LOOKUP.update({d[:3].lower(): d for d in DAYS})
DAY_LOOKUP.update({"tues": "Tuesday", "thur": "Thursday", "thurs": "Thursday", "weds": "Wednesday"})

# Which kinds of rooms can host which kind of session.
CLASS_ROOM_TYPES = ["Classroom", "Tutorial Room", "Seminar Room", "Discussion Room"]
LAB_ROOM_TYPES = ["Laboratory", "Research Lab", "Workshop"]

# Header aliases (matched after lower-casing and stripping non-alphanumerics).
ALIASES = {
    "subject": {"subject", "subjectname", "course", "coursename", "paper"},
    "faculty": {"faculty", "facultyname", "teacher", "instructor", "professor", "staff"},
    "class_name": {"class", "classname", "section", "group", "batch", "division", "year"},
    "type": {"type", "sessiontype", "kind", "classorlab", "mode", "classtype"},
    "lab": {"lab", "labroom", "laboratory"},
    "day": {"day", "dayofweek", "weekday"},
    "time": {"time", "timeslot", "slot", "timing", "timings", "period"},
    "start": {"start", "starttime", "from", "begin"},
    "end": {"end", "endtime", "to", "finish"},
    "room": {"room", "roomid", "location", "venue", "classroom", "roomno", "roomnumber"},
    "building": {"building", "buildingname", "block"},
}


# ───────────────────────── parsing helpers ─────────────────────────
def _norm(h) -> str:
    return re.sub(r"[^a-z0-9]", "", str(h).lower())


def _clean(v) -> str:
    if v is None:
        return ""
    try:
        if pd.isna(v):
            return ""
    except (TypeError, ValueError):
        pass
    return str(v).strip()


_TIME_RE = re.compile(r"(\d{1,2})(?:[:.](\d{2}))?(?:[:.]\d{2})?\s*([ap]\.?m\.?)?", re.I)


def _parse_time(token: str) -> Optional[tuple[int, int]]:
    m = _TIME_RE.fullmatch(token.strip())
    if not m:
        return None
    h, mi, ap = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or "").lower().replace(".", "")
    if mi > 59 or h > 24:
        return None
    if ap == "pm" and h < 12:
        h += 12
    elif ap == "am" and h == 12:
        h = 0
    elif not ap and 1 <= h <= 6:
        h += 12  # "1-3" in a campus timetable means the afternoon
    return h, mi


def _parse_range(text: str) -> Optional[tuple[tuple[int, int], tuple[int, int]]]:
    parts = re.split(r"\s*(?:-|–|—|to)\s*", text.strip(), maxsplit=1, flags=re.I)
    if len(parts) != 2:
        return None
    a, b = _parse_time(parts[0]), _parse_time(parts[1])
    return (a, b) if a and b else None


def _hhmm(t: tuple[int, int]) -> str:
    return f"{t[0]:02d}:{t[1]:02d}"


def hourly_slots(start: str, end: str) -> list[str]:
    """'09:30','11:00' -> ['09:00-10:00','10:00-11:00'] (whole-hour booking slots)."""
    sh = int(start[:2])
    eh = int(end[:2]) + (1 if int(end[3:5]) > 0 else 0)
    return [f"{h:02d}:00-{h + 1:02d}:00" for h in range(sh, eh)]


def _overlap(a: models.TimetableEntry, b: models.TimetableEntry) -> bool:
    return a.day_of_week == b.day_of_week and a.start_time < b.end_time and b.start_time < a.end_time


def _read_table(filename: str, raw: bytes) -> pd.DataFrame:
    name = (filename or "").lower()
    try:
        if name.endswith(".csv") or name.endswith(".txt"):
            return pd.read_csv(io.BytesIO(raw), dtype=str, keep_default_na=False, encoding_errors="replace",
                               sep=None, engine="python")
        if name.endswith((".xlsx", ".xlsm", ".xls")):
            return pd.read_excel(io.BytesIO(raw), dtype=str, keep_default_na=False)
    except Exception as exc:  # pragma: no cover - depends on the file
        raise HTTPException(400, f"Could not read the file: {exc}")
    raise HTTPException(400, "Unsupported file type. Upload a .csv or .xlsx file.")


def parse_timetable(df: pd.DataFrame, db: Session) -> tuple[list[dict], list[str]]:
    """Return (rows, errors). Rows are dicts ready to become TimetableEntry."""
    df = df.dropna(how="all")
    col: dict[str, str] = {}
    for key, names in ALIASES.items():
        for c in df.columns:
            if _norm(c) in names and key not in col:
                col[key] = c
    missing = []
    for need, label in (("subject", "Subject"), ("faculty", "Faculty"), ("class_name", "Class"), ("day", "Day")):
        if need not in col:
            missing.append(label)
    if "time" not in col and not ("start" in col and "end" in col):
        missing.append("Time (e.g. 09:00-11:00) or Start + End")
    if missing:
        raise HTTPException(400, "Missing required column(s): " + ", ".join(missing) +
                            ". Download the template for the expected layout.")
    if len(df) == 0:
        raise HTTPException(400, "The file has no rows.")
    if len(df) > MAX_ROWS:
        raise HTTPException(400, f"Too many rows ({len(df)}); the limit is {MAX_ROWS}.")

    known_rooms = {r[0] for r in db.query(models.Resource.room_id).all()}
    known_buildings = {r[0] for r in db.query(models.Resource.building_name).distinct().all()}
    rooms_lower = {r.lower(): r for r in known_rooms}
    buildings_lower = {b.lower(): b for b in known_buildings}

    rows, errors = [], []
    for idx, rec in enumerate(df.to_dict("records"), start=2):  # 2 = first data row in a spreadsheet
        get = lambda k: _clean(rec.get(col[k])) if k in col else ""  # noqa: E731
        subject, faculty, cls, day_raw = get("subject"), get("faculty"), get("class_name"), get("day")
        problems, warns = [], []
        for label, val in (("Subject", subject), ("Faculty", faculty), ("Class", cls)):
            if not val:
                problems.append(f"{label} is empty")
        day = DAY_LOOKUP.get(day_raw.lower().rstrip("."))
        if not day:
            problems.append(f"Day '{day_raw}' is not a weekday name")

        if "time" in col and get("time"):
            tr = _parse_range(get("time"))
        else:
            a, b = _parse_time(get("start")), _parse_time(get("end"))
            tr = (a, b) if a and b else None
        if not tr:
            problems.append("Time must look like 09:00-11:00")
        elif (tr[0][0] * 60 + tr[0][1]) >= (tr[1][0] * 60 + tr[1][1]):
            problems.append("End time must be after start time")
        elif tr[0][0] < 6 or tr[1][0] > 22 or (tr[1][0] == 22 and tr[1][1] > 0):
            problems.append("Time must be between 06:00 and 22:00")

        # Class or Lab — from the Type column, the Lab column, or the subject name.
        stype = None
        t_val, lab_val = get("type").lower(), get("lab")
        room_req = get("room")
        if t_val:
            stype = "Lab" if "lab" in t_val or "practical" in t_val else "Class"
        elif lab_val:
            low = lab_val.lower()
            if low in {"no", "n", "false", "0", "-", "none", "na", "n/a"}:
                stype = "Class"
            else:
                stype = "Lab"
                if low not in {"yes", "y", "true", "1", "x", "lab"} and not room_req:
                    room_req = lab_val  # the Lab column names the lab being requested
        else:
            stype = "Lab" if "lab" in subject.lower() else "Class"

        building_req = get("building")
        building = None
        if building_req:
            building = buildings_lower.get(building_req.lower())
            if not building:
                warns.append(f"Building '{building_req}' not found - any building will be considered")
        room = None
        if room_req:
            room = rooms_lower.get(room_req.lower())
            if not room:
                warns.append(f"Room '{room_req}' not found - a suitable {stype.lower()} room will be allocated")

        if problems:
            errors.append(f"Row {idx}: " + "; ".join(problems))
            continue
        if tr[0][1] or tr[1][1]:
            warns.append("Times are rounded out to whole-hour booking slots")
        rows.append(dict(subject=subject, faculty=faculty, class_name=cls, session_type=stype, day_of_week=day,
                         start_time=_hhmm(tr[0]), end_time=_hhmm(tr[1]), requested_room=room,
                         requested_building=building, warns=warns))
    return rows, errors


def _entry_out(e: models.TimetableEntry) -> dict:
    return {
        "id": e.id, "subject": e.subject, "faculty": e.faculty, "class_name": e.class_name,
        "session_type": e.session_type, "day_of_week": e.day_of_week,
        "start_time": e.start_time, "end_time": e.end_time,
        "requested_room": e.requested_room, "requested_building": e.requested_building,
        "allocated_room": e.allocated_room, "status": e.status, "note": e.note, "warning": e.warning,
    }


def _tt_out(t: models.Timetable, with_entries: bool = False) -> dict:
    counts: dict[str, int] = {}
    for e in t.entries:
        counts[e.status] = counts.get(e.status, 0) + 1
    out = {
        "id": t.id, "name": t.name, "department": t.department, "status": t.status,
        "valid_from": str(t.valid_from), "valid_to": str(t.valid_to),
        "uploaded_by": t.uploader.name if t.uploader else None,
        "uploaded_by_email": t.uploader.email if t.uploader else None,
        "reviewed_by": t.reviewer.name if t.reviewer else None,
        "reviewed_at": t.reviewed_at.isoformat() if t.reviewed_at else None,
        "review_note": t.review_note,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "entry_count": len(t.entries),
        "class_count": sum(1 for e in t.entries if e.session_type == "Class"),
        "lab_count": sum(1 for e in t.entries if e.session_type == "Lab"),
        "warning_count": sum(1 for e in t.entries if e.warning),
        "status_counts": counts,
    }
    if with_entries:
        out["entries"] = [_entry_out(e) for e in t.entries]
    return out


def _can_view(t: models.Timetable, user: models.User) -> bool:
    return user.role == "administrator" or t.uploaded_by == user.id


def _get_or_404(db: Session, tid: int) -> models.Timetable:
    t = db.query(models.Timetable).filter(models.Timetable.id == tid).first()
    if not t:
        raise HTTPException(404, "Timetable not found")
    return t


# ───────────────────────── endpoints ─────────────────────────
@router.get("/template")
def template():
    """CSV template showing the expected layout."""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Subject", "Faculty", "Class", "Type", "Day", "Time", "Room", "Building"])
    w.writerow(["Data Structures", "Dr. Rohan Bose", "CSE-3A", "Class", "Monday", "09:00-10:00", "", "Academic Block A"])
    w.writerow(["Data Structures Lab", "Dr. Rohan Bose", "CSE-3A", "Lab", "Wednesday", "14:00-16:00", "", "Science Block"])
    w.writerow(["Thermodynamics", "Prof. Priya Rao", "ME-2B", "Class", "Tuesday", "11:00-12:00", "", ""])
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=timetable_template.csv"})


@router.post("")
async def upload_timetable(
    name: str = Form(...),
    valid_from: Optional[str] = Form(None),
    valid_to: Optional[str] = Form(None),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    if user.role not in ("administrator", "faculty"):
        raise HTTPException(403, "Only faculty and administrators can upload timetables")
    name = name.strip()
    if not name:
        raise HTTPException(400, "Give the timetable a name")
    try:
        vf = date.fromisoformat(valid_from) if valid_from else date.today()
        vt = date.fromisoformat(valid_to) if valid_to else vf + timedelta(weeks=12) - timedelta(days=1)
    except ValueError:
        raise HTTPException(400, "Dates must be YYYY-MM-DD")
    if vt < vf:
        raise HTTPException(400, "'Valid to' must not be before 'valid from'")
    if (vt - vf).days > MAX_RANGE_DAYS:
        raise HTTPException(400, "A timetable can cover at most 26 weeks")

    raw = await file.read()
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(400, "File is larger than 2 MB")
    rows, errors = parse_timetable(_read_table(file.filename, raw), db)
    if errors:
        more = f" (+{len(errors) - 15} more)" if len(errors) > 15 else ""
        raise HTTPException(400, "Fix these rows and upload again: " + " | ".join(errors[:15]) + more)

    tt = models.Timetable(name=name, uploaded_by=user.id, department=user.department,
                          valid_from=vf, valid_to=vt, status="Pending")
    entries = [models.TimetableEntry(**{k: v for k, v in r.items() if k != "warns"},
                                     status="Pending", warning="; ".join(r["warns"]) or None) for r in rows]
    # Clash warnings inside the file itself.
    for i, a in enumerate(entries):
        for b in entries[i + 1:]:
            if not _overlap(a, b):
                continue
            msgs = []
            if a.faculty.lower() == b.faculty.lower():
                msgs.append(f"{a.faculty} is scheduled twice at the same time")
            if a.class_name.lower() == b.class_name.lower():
                msgs.append(f"{a.class_name} has two sessions at the same time")
            if a.requested_room and a.requested_room == b.requested_room:
                msgs.append(f"room {a.requested_room} is requested twice at the same time")
            if msgs:
                m = "Clash: " + ", ".join(msgs)
                for e in (a, b):
                    e.warning = f"{e.warning}; {m}" if e.warning and m not in e.warning else (e.warning or m)
    tt.entries = entries
    db.add(tt)
    db.commit()
    db.refresh(tt)
    return _tt_out(tt, with_entries=True)


@router.get("")
def list_timetables(status: Optional[str] = None, db: Session = Depends(get_db),
                    user: models.User = Depends(get_current_user)):
    if user.role not in ("administrator", "faculty"):
        raise HTTPException(403, "Not available for your role")
    q = db.query(models.Timetable)
    if user.role != "administrator":
        q = q.filter(models.Timetable.uploaded_by == user.id)
    if status:
        q = q.filter(models.Timetable.status == status)
    return [_tt_out(t) for t in q.order_by(models.Timetable.created_at.desc()).limit(200).all()]


@router.get("/{tid}")
def get_timetable(tid: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    t = _get_or_404(db, tid)
    if not _can_view(t, user):
        raise HTTPException(403, "Not your timetable")
    return _tt_out(t, with_entries=True)


class ReviewBody(BaseModel):
    note: Optional[str] = None


def _occurrences(t: models.Timetable, e: models.TimetableEntry) -> list[date]:
    target = DAYS.index(e.day_of_week)
    d = t.valid_from + timedelta(days=(target - t.valid_from.weekday()) % 7)
    out = []
    while d <= t.valid_to:
        out.append(d)
        d += timedelta(days=7)
    return out


@router.post("/{tid}/approve")
def approve_timetable(tid: int, body: ReviewBody = ReviewBody(), db: Session = Depends(get_db),
                      admin: models.User = Depends(require_admin)):
    """Accept the timetable, then accept (allocate + book) the requested locations."""
    t = _get_or_404(db, tid)
    if t.status != "Pending":
        raise HTTPException(409, f"This timetable is already {t.status.lower()}")

    # Everything already booked in the period, so allocation never double-books a room.
    busy: dict[str, set[tuple[date, str]]] = {}
    for room_id, d, slot in (
        db.query(models.Booking.room_id, models.Booking.date, models.Booking.time_slot)
        .filter(models.Booking.status != "Cancelled",
                models.Booking.date >= t.valid_from, models.Booking.date <= t.valid_to).all()
    ):
        busy.setdefault(room_id, set()).add((d, slot))

    resources = db.query(models.Resource).order_by(models.Resource.avg_utilization.asc()).all()
    by_id = {r.room_id: r for r in resources}

    def usable(r: models.Resource) -> bool:
        return r.maintenance_status != "Under Repair"

    def is_free(room_id: str, needed: set[tuple[date, str]]) -> bool:
        return not (busy.get(room_id, set()) & needed)

    def find_free(types: list[str], needed, building: Optional[str], exclude: Optional[str] = None):
        for r in resources:  # already sorted: least-used rooms first
            if r.room_type in types and usable(r) and r.room_id != exclude \
                    and (building is None or r.building_name == building) and is_free(r.room_id, needed):
                return r
        return None

    created = 0
    for e in t.entries:
        slots = hourly_slots(e.start_time, e.end_time)
        dates = _occurrences(t, e)
        needed = {(d, s) for d in dates for s in slots}
        if not needed:
            e.status, e.note = "Unallocated", "No matching weekday between the valid-from and valid-to dates"
            continue
        types = LAB_ROOM_TYPES if e.session_type == "Lab" else CLASS_ROOM_TYPES
        asked = by_id.get(e.requested_room) if e.requested_room else None
        chosen, note = None, None
        if asked is not None:
            if usable(asked) and is_free(asked.room_id, needed):
                chosen, note = asked, "Requested room accepted"
            else:
                why = "under repair" if not usable(asked) else "already booked at that time"
                chosen = (find_free([asked.room_type], needed, asked.building_name, exclude=asked.room_id)
                          or find_free(types, needed, e.requested_building or asked.building_name, exclude=asked.room_id)
                          or find_free(types, needed, None, exclude=asked.room_id))
                if chosen:
                    note = f"Requested {asked.room_id} is {why}; allocated {chosen.room_id} instead"
        else:
            chosen = (find_free(types, needed, e.requested_building) if e.requested_building else None) \
                or find_free(types, needed, None)
            if chosen:
                note = "Room allocated automatically (least-used free " + e.session_type.lower() + " room)"
                if e.requested_building and chosen.building_name != e.requested_building:
                    note += f"; none free in {e.requested_building}"
        if not chosen:
            e.status, e.note = "Unallocated", "No suitable room is free for every week of this timetable"
            continue
        e.allocated_room = chosen.room_id
        e.status = "Allocated" if (asked is not None and chosen.room_id == asked.room_id) or asked is None else "Reallocated"
        e.note = note
        for d, s in sorted(needed):
            busy.setdefault(chosen.room_id, set()).add((d, s))
            db.add(models.Booking(user_id=t.uploaded_by, room_id=chosen.room_id, date=d, time_slot=s,
                                  purpose=f"{e.subject} - {e.class_name} ({e.faculty})",
                                  status="Confirmed", source="timetable", timetable_entry_id=e.id))
            created += 1

    t.status = "Approved"
    t.reviewed_by = admin.id
    t.reviewed_at = datetime.now(timezone.utc)
    t.review_note = (body.note or "").strip() or None
    db.commit()
    db.refresh(t)
    out = _tt_out(t, with_entries=True)
    out["bookings_created"] = created
    return out


@router.post("/{tid}/reject")
def reject_timetable(tid: int, body: ReviewBody = ReviewBody(), db: Session = Depends(get_db),
                     admin: models.User = Depends(require_admin)):
    t = _get_or_404(db, tid)
    if t.status != "Pending":
        raise HTTPException(409, f"This timetable is already {t.status.lower()}")
    t.status = "Rejected"
    t.reviewed_by = admin.id
    t.reviewed_at = datetime.now(timezone.utc)
    t.review_note = (body.note or "").strip() or None
    for e in t.entries:
        e.status = "Rejected"
    db.commit()
    db.refresh(t)
    return _tt_out(t, with_entries=True)


@router.delete("/{tid}")
def cancel_timetable(tid: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    """Withdraw a pending timetable, or (admin / owner) cancel an approved one and free its rooms."""
    t = _get_or_404(db, tid)
    if not _can_view(t, user):
        raise HTTPException(403, "Not your timetable")
    if t.status in ("Rejected", "Cancelled"):
        raise HTTPException(409, f"This timetable is already {t.status.lower()}")
    ids = [e.id for e in t.entries]
    freed = 0
    if ids:
        freed = (db.query(models.Booking)
                 .filter(models.Booking.timetable_entry_id.in_(ids), models.Booking.status != "Cancelled")
                 .update({"status": "Cancelled"}, synchronize_session=False))
    t.status = "Cancelled"
    db.commit()
    return {"ok": True, "bookings_cancelled": freed}
