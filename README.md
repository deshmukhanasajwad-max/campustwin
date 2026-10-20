# CampusTwin — Full Stack (Frontend + Backend + Database)

A working implementation of the Data-Driven Digital Twin for College Resource
Management System, running entirely on your own PC — **no AWS, no cloud
account needed.**

- **Frontend**: single-page app (HTML/CSS/JS + Chart.js), served by the backend
- **Backend**: FastAPI (Python) — real JWT auth, booking conflict checks, SQL
  analytics, scikit-learn demand prediction
- **Database**: PostgreSQL, seeded automatically from the included CSV dataset
  (2,627 resources, 10,500 historical usage records)

This has been tested end-to-end: seeding, login, resource search/pagination,
booking + conflict detection, all analytics endpoints, predictions, alerts,
and CSV report exports all work against a real Postgres database.

## Option A — Docker (recommended, easiest)

**Requirements:** [Docker Desktop](https://www.docker.com/products/docker-desktop/)
installed and running (Windows, Mac, or Linux).

1. Unzip this project and open a terminal in the `campustwin-fullstack/` folder.
2. Run:
   ```
   docker compose up --build
   ```
3. Wait for the log to show `[seed] done.` and `Application startup complete.`
   (first run only — it loads the CSV into Postgres, takes ~30–60 seconds).
4. Open **http://localhost:8000** in your browser.
5. Sign in with a demo account:

   | Role | Email | Password |
   |---|---|---|
   | Administrator | admin@campustwin.app | admin123 |
   | Faculty | faculty@campustwin.app | faculty123 |
   | Student | student@campustwin.app | student123 |

To stop: `Ctrl+C`, then `docker compose down` (add `-v` to also wipe the database
and force a fresh reseed next time).

## Option B — Without Docker (manual install)

**Requirements:** Python 3.11+, PostgreSQL 14+ installed locally.

1. Create the database:
   ```
   psql -U postgres -c "CREATE USER campustwin WITH PASSWORD 'campustwin';"
   psql -U postgres -c "CREATE DATABASE campustwin OWNER campustwin;"
   ```
2. Install backend dependencies:
   ```
   cd backend
   pip install -r requirements.txt
   ```
3. Set environment variables and run:
   ```
   export DATABASE_URL="postgresql+psycopg2://campustwin:campustwin@localhost:5432/campustwin"
   export CSV_PATH="../data/college_resource_management_digital_twin_dataset_1.csv"
   export JWT_SECRET="pick-any-random-string"
   uvicorn app.main:app --host 0.0.0.0 --port 8000
   ```
   (On Windows, use `set` instead of `export`, or a `.env` loader of your choice.)
4. Open **http://localhost:8000**.

## Timetable upload & approval

Faculty and administrators can upload a timetable (**Timetables** in the sidebar). Upload a `.csv` or
`.xlsx` with one row per weekly session — use the **Download template** button for the layout:

| Subject | Faculty | Class | Type | Day | Time | Room (optional) | Building (optional) |
|---|---|---|---|---|---|---|---|
| Data Structures | Dr. Rohan Bose | CSE-3A | Class | Monday | 09:00-10:00 | | Academic Block A |
| Data Structures Lab | Dr. Rohan Bose | CSE-3A | Lab | Wednesday | 14:00-16:00 | | Science Block |

A `Lab` column (yes/no, or the lab's room ID) is accepted instead of `Type`. Start/End columns also work.

1. **Upload** → the timetable is stored as *Pending*. Nothing is booked. Clashes (same faculty / class / room
   at the same time) are flagged as warnings.
2. **Administrator approves** (sidebar → *Timetable Approvals*, with a pending-count badge) or rejects with a note.
3. **On approval the requested locations are accepted**: each class/lab gets its requested room if it is free
   and in service, otherwise the best free alternative (flagged *Reallocated*), and conflict-checked bookings are
   created for every week between *valid from* and *valid to*. Sessions that cannot be placed are marked
   *Unallocated*. An approved timetable can be cancelled to release its rooms.

## AI Insights

**AI Insights** (admin and faculty) turns the live data into plain-language findings: forecast trend, busiest
slots/days, over- and under-used rooms, concrete room re-allocation suggestions, energy waste, maintenance risk
and timetable status. It runs entirely server-side (scikit-learn + statistical rules) — no external API key.

## Deploying to Render

`render.yaml` is a Blueprint: in Render choose **New → Blueprint**, select this repo, and it creates a
PostgreSQL database plus the web service (Docker). The first start seeds the database from the CSV (~1 min).
`JWT_SECRET` is generated automatically. Change the demo account passwords before sharing the URL.

## What's real vs. simplified

| Feature | Status |
|---|---|
| Login / JWT auth | Real — bcrypt-hashed passwords, JWT tokens |
| Resource registry, search, pagination | Real — SQL queries against Postgres |
| Bookings + conflict detection | Real — persisted, checked against the `bookings` table |
| Utilization / energy / booking-status analytics | Real — live SQL aggregation over 10,500 usage records |
| Demand prediction | Real — scikit-learn `LinearRegression`, computed server-side |
| Alerts (under/over-utilized, maintenance) | Real — computed from the database |
| CSV report exports | Real — streamed from the database |
| IoT sensors, real-time occupancy, ERP integration | Not included — out of scope per the SRS (§4.2, §25) |

## Project structure

```
campustwin-fullstack/
├── docker-compose.yml       # one-command startup (db + backend)
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app/
│       ├── main.py          # FastAPI app, mounts API + serves frontend
│       ├── database.py      # SQLAlchemy engine/session
│       ├── models.py        # User, Resource, UsageLog, Booking, Timetable tables
│       ├── schemas.py       # Pydantic request/response models
│       ├── security.py      # password hashing + JWT
│       ├── seed_data.py     # loads the CSV into Postgres on first run
│       └── routers/         # auth, resources, bookings, analytics,
│                             # predictions, alerts, reports, timetables, insights
├── frontend/
│   └── index.html           # the whole SPA — talks to the API via fetch()
└── data/
    └── college_resource_management_digital_twin_dataset_1.csv
```

## Moving to AWS later

The `AWS_Guied_to_devlope_the_project.docx` you provided separately lays out
the cloud deployment path (S3 → Glue → DynamoDB → API Gateway → hosted
frontend). This local stack maps directly onto that: the FastAPI backend can
be containerized and deployed as-is (e.g. to ECS/Fargate or Elastic
Beanstalk), and the Postgres database can move to Amazon RDS by changing only
the `DATABASE_URL` environment variable — no application code changes needed.
