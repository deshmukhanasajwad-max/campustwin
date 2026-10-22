# CampusTwin – Project Guide (for viva / demonstration)

## 1. One-paragraph summary
CampusTwin is a **data-driven digital twin of a college campus**. It keeps a virtual copy of every room
(2,627 rooms, 10 buildings) built from historical usage data, shows utilization, energy use and maintenance
status, forecasts demand, suggests how to use rooms better, and lets faculty upload **timetables** that an
**administrator must approve** before the requested classrooms/labs are booked.

## 2. Technology used

| Layer | Technology |
|---|---|
| Programming languages | **Python 3.11** (backend), **JavaScript, HTML, CSS** (frontend), **SQL** (via SQLAlchemy) |
| Backend framework | **FastAPI** (REST API) served by Uvicorn |
| Database | **PostgreSQL** (accessed with SQLAlchemy ORM + psycopg2) |
| Data processing | **pandas**, **NumPy** (CSV loading/cleaning, Excel/CSV timetable parsing) |
| Machine learning | **scikit-learn** (`LinearRegression`) |
| Frontend charts | **Chart.js** (single-page app, no framework) |
| Security | **JWT** tokens (python-jose), **bcrypt** password hashing (passlib), role-based access |
| Deployment | **Docker**, **GitHub**, **Render** |

## 3. Dataset
* File: `data/college_resource_management_digital_twin_dataset_1.csv` (sample/simulated campus dataset).
* **10,500 records × 35 columns**, dates 2025-01-06 → 2025-07-04.
* Covers **2,627 rooms, 10 buildings, 23 room types, 13 departments, 1,000 faculty IDs**.
* Key columns: Date, Day_of_Week, Time_Slot, Building_Name, Room_ID, Room_Type, Department, Course, Faculty,
  Scheduled_Capacity, Actual_Occupancy, **Utilization_Percentage**, Booking_Status, **Energy_Consumption_kWh**,
  Temperature, CO2, Maintenance_Status, Next_Scheduled_Maintenance.
* At first start `seed_data.py` loads it into PostgreSQL: one row per room in `resources` (with average
  utilization / energy) and every raw record in `usage_logs`.

## 4. Algorithms and techniques
1. **Linear regression (scikit-learn)** – fits monthly average utilization against time and predicts the next
   3 months (Predictions page and AI Insights). R² is reported so a weak trend is not over-claimed.
2. **Moving average** – alternative forecast (mean of the last 3 months).
3. **Threshold rules** – a room is *under-utilized* below 35 % and *over-utilized* above 80 %; drives Alerts.
4. **Re-allocation suggestion (greedy matching)** – pairs each over-used room with the least-used idle room of
   the **same type** and similar capacity, preferring the same building.
5. **Room allocation on timetable approval (greedy first-fit)** – for each session: try the requested room; if it
   is busy/under repair take the least-utilized free room of a suitable type (Class → Classroom/Tutorial/
   Seminar/Discussion; Lab → Laboratory/Research Lab/Workshop). Availability is checked for **every week**
   in the timetable's date range, using sets of (date, hour-slot).
6. **Conflict detection** – a room can never be booked twice for the same date and hour; timetable clashes
   (same faculty / class / room at the same time) are detected by interval-overlap tests.
7. **SQL aggregation** – `GROUP BY` / `AVG` / `SUM` for building, department, time-slot, weekday and monthly
   analytics.
8. **Approval workflow (state machine)** – Timetable: `Pending → Approved | Rejected → (Cancelled)`.
9. **Authentication & authorization** – JWT login; roles: administrator / faculty / student.
10. **ETL** – CSV → pandas → aggregated tables in PostgreSQL.

> Note on "AI": the insights are produced by **machine learning (linear regression) plus statistical rules** –
> not by a large language model. Say it that way if asked.

## 5. Architecture
```
Browser (HTML/JS/Chart.js SPA)  --REST/JSON + JWT-->  FastAPI  --SQLAlchemy-->  PostgreSQL
                                                         |
                                           pandas / scikit-learn (analysis, forecast)
```
Database tables: `users`, `resources`, `usage_logs`, `bookings`, `timetables`, `timetable_entries`.

## 6. Features by role
* **Administrator**: overview dashboard, twin map, resources, bookings, **Timetable Approvals** (approve/reject),
  **AI Insights**, utilization analytics, predictions, alerts, CSV reports.
* **Faculty**: **upload timetable**, see its status and allocated rooms, facility schedule, book a resource,
  AI Insights, utilization.
* **Student**: view overview, twin map, facilities, request a resource.

## 7. Timetable flow (explain this one clearly)
1. Faculty uploads CSV/Excel: **Subject, Faculty, Class, Type (Class/Lab), Day, Time**, optional Room/Building.
2. Rows are validated; errors are reported by row number. Status = **Pending**; nothing is booked.
3. Administrator opens *Timetable Approvals* and approves or rejects.
4. On **approval**, the requested classroom/lab locations are accepted: rooms are allocated and confirmed
   bookings are created for each week. If the requested room is busy, another suitable room is allocated and the
   session is marked *Reallocated*; if none is free it is marked *Unallocated*.

## 8. What was fixed in this version
* **Predictions / AI Insights chart crashed** (Chart.js config was missing its `type`) – fixed; Chart.js is now
  bundled locally so a blocked CDN cannot break the page.
* Public sign-up could create administrators – now always creates a student.
* App could not find its frontend folder outside Docker; database URL / port handling for Render added.

## 9. How to run
**Docker (easiest):** `docker compose up --build` → open http://localhost:8000
**Without Docker:** install PostgreSQL, then follow *Option B* in `README.md`.
Demo logins: admin@campustwin.app / admin123, faculty@campustwin.app / faculty123, student@campustwin.app / student123.

## 10. How to show the code to the invigilator
1. Open the GitHub repository (link in your submission) – it proves the work and shows the commit history.
2. Open the folder in **VS Code** and walk through in this order (≈ 5–8 minutes):
   1. `README.md` – what the project is and how to run it.
   2. `data/…csv` – the dataset (open it, show the columns).
   3. `backend/app/models.py` – the database tables.
   4. `backend/app/seed_data.py` – how the dataset is loaded into PostgreSQL.
   5. `backend/app/routers/predictions.py` and `insights.py` – the machine-learning part (LinearRegression).
   6. `backend/app/routers/timetables.py` – upload parsing, approval, room allocation.
   7. `backend/app/security.py` – JWT and password hashing.
   8. `frontend/index.html` – the user interface.
3. Then run the **live demo** (see script below).

### Demo script (≈ 5 minutes)
1. Log in as **faculty** → *My Timetables* → download the template → upload a filled file → show it is **Pending**.
2. Sign out, log in as **administrator** → *Timetable Approvals* (badge shows 1) → open it → **Approve**.
3. Show the allocated rooms and notes (Allocated / Reallocated). Open *Bookings* to show the bookings now exist.
4. Open **AI Insights** → explain findings, forecast chart and the re-allocation table.
5. Show *Overview*, *Twin Map* and *Predictions* briefly.

### Questions an invigilator may ask
* *Which algorithm predicts demand?* Linear regression on monthly average utilization (scikit-learn).
* *Why PostgreSQL?* Relational data, transactions, constraints, strong aggregation – needed for conflict checks.
* *How do you prevent double booking?* Every booking is checked against existing rows for the same room, date and slot.
* *How is the system secured?* bcrypt-hashed passwords, JWT tokens, role checks on every protected endpoint.
* *Is the data real?* It is a sample/simulated dataset; the system is designed to take real data or IoT feeds later.
* *Limitations / future work?* No live IoT sensors; simple linear model (could use time-series models such as
  ARIMA/Prophet); no email notifications.
