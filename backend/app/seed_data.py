import os
import pandas as pd
from sqlalchemy.orm import Session

from . import models
from .security import hash_password

CSV_PATH = os.getenv("CSV_PATH", "/app/data/college_resource_management_digital_twin_dataset_1.csv")


def needs_seed(db: Session) -> bool:
    return db.query(models.Resource).count() == 0


def seed(db: Session):
    print(f"[seed] loading dataset from {CSV_PATH} ...")
    df = pd.read_csv(CSV_PATH)
    df["Date"] = pd.to_datetime(df["Date"])
    df["Next_Scheduled_Maintenance"] = pd.to_datetime(df["Next_Scheduled_Maintenance"], errors="coerce")

    # ---- Resources (one row per room, aggregated) ----
    latest = df.sort_values("Date").groupby("Room_ID").last().reset_index()
    room_stats = df.groupby("Room_ID").agg(
        avg_utilization=("Utilization_Percentage", "mean"),
        avg_energy_kwh=("Energy_Consumption_kWh", "mean"),
        capacity=("Scheduled_Capacity", "max"),
    ).reset_index()
    attrs = df.groupby("Room_ID").agg(
        room_type=("Room_Type", lambda x: x.mode().iat[0]),
        building_name=("Building_Name", lambda x: x.mode().iat[0]),
        department=("Department", lambda x: x.mode().iat[0]),
    ).reset_index()
    merged = room_stats.merge(attrs, on="Room_ID").merge(
        latest[["Room_ID", "Maintenance_Status", "Booking_Status", "Next_Scheduled_Maintenance"]],
        on="Room_ID",
    )

    print(f"[seed] inserting {len(merged)} resources ...")
    resources = []
    for row in merged.itertuples(index=False):
        nsm = row.Next_Scheduled_Maintenance
        resources.append(models.Resource(
            room_id=row.Room_ID,
            room_type=row.room_type,
            building_name=row.building_name,
            department=row.department,
            capacity=int(row.capacity) if pd.notna(row.capacity) else 0,
            maintenance_status=row.Maintenance_Status,
            booking_status=row.Booking_Status,
            next_scheduled_maintenance=nsm.date() if pd.notna(nsm) else None,
            avg_utilization=round(float(row.avg_utilization), 1),
            avg_energy_kwh=round(float(row.avg_energy_kwh), 2),
        ))
    db.bulk_save_objects(resources)
    db.commit()

    # ---- Raw usage logs (drives all analytics & predictions) ----
    print(f"[seed] inserting {len(df)} usage log records ...")
    batch = []
    for row in df.itertuples(index=False):
        batch.append(models.UsageLog(
            room_id=row.Room_ID,
            date=row.Date.date(),
            day_of_week=row.Day_of_Week,
            time_slot=row.Time_Slot,
            users_count=int(row.Actual_Occupancy) if pd.notna(row.Actual_Occupancy) else 0,
            purpose=row.Booking_Purpose,
            utilization_percentage=float(row.Utilization_Percentage),
            energy_consumption_kwh=float(row.Energy_Consumption_kWh),
            booking_status=row.Booking_Status,
        ))
        if len(batch) >= 2000:
            db.bulk_save_objects(batch)
            db.commit()
            batch = []
    if batch:
        db.bulk_save_objects(batch)
        db.commit()

    # ---- Demo users (one per role) ----
    print("[seed] creating demo users ...")
    demo_users = [
        models.User(name="Admin User", email="admin@campustwin.app",
                    password_hash=hash_password("admin123"), role="administrator", department="IT Services"),
        models.User(name="Prof. Faculty", email="faculty@campustwin.app",
                    password_hash=hash_password("faculty123"), role="faculty", department="Computer Science"),
        models.User(name="Student User", email="student@campustwin.app",
                    password_hash=hash_password("student123"), role="student", department="Computer Science"),
    ]
    db.bulk_save_objects(demo_users)
    db.commit()
    print("[seed] done.")
