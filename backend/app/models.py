from sqlalchemy import (
    Column, Integer, String, Float, Date, DateTime, ForeignKey, Text, func
)
from sqlalchemy.orm import relationship
from .database import Base


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    role = Column(String, nullable=False)  # administrator | faculty | student
    department = Column(String, nullable=True)

    bookings = relationship("Booking", back_populates="user")


class Resource(Base):
    """One row per physical resource (room), with aggregated stats
    pre-computed at seed time from historical usage logs."""
    __tablename__ = "resources"
    room_id = Column(String, primary_key=True, index=True)
    room_type = Column(String, index=True)
    building_name = Column(String, index=True)
    department = Column(String, index=True)
    capacity = Column(Integer)
    maintenance_status = Column(String)
    booking_status = Column(String)
    next_scheduled_maintenance = Column(Date, nullable=True)
    avg_utilization = Column(Float, default=0)
    avg_energy_kwh = Column(Float, default=0)

    usage_logs = relationship("UsageLog", back_populates="resource")
    bookings = relationship("Booking", back_populates="resource")


class UsageLog(Base):
    """Raw historical usage records imported from the source dataset.
    Backs all time-series analytics and predictions."""
    __tablename__ = "usage_logs"
    id = Column(Integer, primary_key=True, index=True)
    room_id = Column(String, ForeignKey("resources.room_id"), index=True)
    date = Column(Date, index=True)
    day_of_week = Column(String)
    time_slot = Column(String)
    users_count = Column(Integer)
    purpose = Column(String)
    utilization_percentage = Column(Float)
    energy_consumption_kwh = Column(Float)
    booking_status = Column(String)

    resource = relationship("Resource", back_populates="usage_logs")


class Booking(Base):
    """Live bookings created through the app — persisted, real conflict
    checking against overlapping room/date/time_slot."""
    __tablename__ = "bookings"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    room_id = Column(String, ForeignKey("resources.room_id"))
    date = Column(Date, index=True)
    time_slot = Column(String, index=True)
    purpose = Column(String)
    status = Column(String, default="Confirmed")
    # "manual" = made through the booking form; "timetable" = generated when an
    # administrator approved a timetable.
    source = Column(String, default="manual")
    timetable_entry_id = Column(Integer, nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="bookings")
    resource = relationship("Resource", back_populates="bookings")


class Timetable(Base):
    """An uploaded timetable. Stays 'Pending' until an administrator accepts it;
    only then are the requested rooms/labs allocated and booked."""
    __tablename__ = "timetables"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    uploaded_by = Column(Integer, ForeignKey("users.id"), index=True)
    department = Column(String, nullable=True)
    valid_from = Column(Date, nullable=False)
    valid_to = Column(Date, nullable=False)
    status = Column(String, default="Pending", index=True)  # Pending | Approved | Rejected | Cancelled
    review_note = Column(Text, nullable=True)
    reviewed_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    uploader = relationship("User", foreign_keys=[uploaded_by])
    reviewer = relationship("User", foreign_keys=[reviewed_by])
    entries = relationship("TimetableEntry", back_populates="timetable",
                           cascade="all, delete-orphan", order_by="TimetableEntry.id")


class TimetableEntry(Base):
    """One weekly session: subject + faculty + class(section) + class/lab, with
    the room/lab location that is being requested."""
    __tablename__ = "timetable_entries"
    id = Column(Integer, primary_key=True, index=True)
    timetable_id = Column(Integer, ForeignKey("timetables.id"), index=True)
    subject = Column(String, nullable=False)
    faculty = Column(String, nullable=False)
    class_name = Column(String, nullable=False)       # the student group / section, e.g. "CSE-3A"
    session_type = Column(String, nullable=False)     # Class | Lab
    day_of_week = Column(String, nullable=False)
    start_time = Column(String, nullable=False)       # "HH:MM"
    end_time = Column(String, nullable=False)         # "HH:MM"
    requested_room = Column(String, nullable=True)    # specific room_id asked for (optional)
    requested_building = Column(String, nullable=True)
    allocated_room = Column(String, nullable=True)
    status = Column(String, default="Pending")        # Pending | Allocated | Reallocated | Unallocated | Rejected
    note = Column(Text, nullable=True)
    warning = Column(Text, nullable=True)             # clash warnings found at upload time

    timetable = relationship("Timetable", back_populates="entries")
