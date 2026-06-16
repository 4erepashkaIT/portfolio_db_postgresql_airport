# Auckland Airport DB

A database management system for **Auckland International Airport (AKL)**. The database stores
only flights that **depart from or arrive at Auckland**, with international and domestic routes,
airlines, aircraft, passengers, tickets, crew and assignments.

## Tech stack

| Layer | Stack |
|---|---|
| DBMS | PostgreSQL 16 (Docker image `postgres:16-alpine`) |
| Web UI | Python 3.9+, Streamlit ≥ 1.43 |
| DB adapter | psycopg2-binary ≥ 2.9 |
| Containerization | Docker Compose |

---

## Project structure

```
airport_db/
├── docker-compose.yml        # Brings up the PostgreSQL container
├── .env                      # PostgreSQL environment variables
├── sql/
│   ├── 01_schema.sql         # DDL: tables, trigger, constraints
│   ├── 02_users.sql          # Create DB users and grant privileges
│   └── 03_data.sql           # Sample data (airlines, flights, tickets …)
└── app/
    ├── app.py                # Streamlit app (all UI and SQL queries)
    └── requirements.txt      # Python dependencies
```

---

## Database schema

The database has **7 tables** linked by foreign keys:

```
airline ──< aircraft ──< flight ──< ticket >── passenger
                            └──< crew_assignment >── employee
```

| Table | Key | Description |
|---|---|---|
| `airline` | `iata_code` CHAR(2) PK | Airlines: IATA code, name, country |
| `aircraft` | `tail_number` PK | Aircraft: model, capacity, year built, airline |
| `flight` | `flight_id` SERIAL PK | Flights: number, route, departure/arrival time, status |
| `passenger` | `passenger_id` SERIAL PK | Passengers: name, passport (UNIQUE), date of birth, phone |
| `ticket` | `ticket_no` VARCHAR PK | Tickets: seat, class, price (USD), purchase date |
| `employee` | `employee_id` INTEGER PK | Crew members: name, position, hire date |
| `crew_assignment` | `(flight_id, employee_id)` PK | Crew assignments to flights (M:N) |

### Integrity constraints

- `CHECK` on flight status: `'scheduled'`, `'delayed'`, `'cancelled'`, `'completed'`
- `CHECK` on service class: `'economy'`, `'business'`, `'first'`
- `CHECK (city_from = 'Auckland' OR city_to = 'Auckland')` — single-hub airport; every flight
  must depart from or arrive at Auckland
- `UNIQUE (flight_id, seat_no)` — a seat cannot be sold twice
- `UNIQUE passport_no` — duplicate passports are not allowed
- Trigger `trg_check_seat_availability` — blocks selling a ticket when no seats are free

---

## Security role model

Implemented with PostgreSQL (principle of least privilege):

| DB user | App role | Privileges |
|---|---|---|
| `admin_user` | Administrator | `ALL` on every table; `CREATEDB`, `CREATEROLE` |
| `dispatcher_user` | Dispatcher | `SELECT` on everything; `INSERT/UPDATE/DELETE` on `flight`, `crew_assignment`; `UPDATE` on `aircraft` |
| `cashier_user` | Cashier | `SELECT` on `flight`, `passenger`, `ticket`; `INSERT` on `passenger`, `ticket`; `UPDATE (phone, passport_no)` on `passenger` |

---

## Application features

### Pages

| Page | Access | Description |
|---|---|---|
| Home | All | Table metrics, role rights description, database overview |
| Tables | By role | Paginated table browsing |
| Queries | By role | 13 parametric SQL queries |
| Reports | By role | Summary reports with visualization (bar chart) |
| Manage | By role | Add/edit data through forms |
| Security | Administrator only | Privilege matrix, DDL view, privilege check |

### 13 preset queries

1. Passengers on a specific flight
2. Flight schedule for a date
3. Flights of a specific airline *(not available to the Cashier)*
4. Number of free seats on a flight
5. Crew of a specific flight *(not available to the Cashier)*
6. Delayed and cancelled flights over a period
7. Aircraft usage history over a period
8. Average ticket price by service class
9. Top 5 passengers by total spend
10. Flights with available seats
11. Number of flights by status
12. Passengers without a middle name
13. Employees with no flight assignments *(not available to the Cashier)*

### Reports

- **Flight load** — capacity, sales, load percentage, revenue (USD)
- **By employee** — years of service, number of flights in a period *(Dispatcher, Administrator)*
- **By airline** — fleet size, completed flights, revenue *(Dispatcher, Administrator)*

---

## Quick start

### Requirements

- [Docker](https://docs.docker.com/get-docker/) and Docker Compose (included in Docker Desktop)
- Python 3.9 or newer
- pip

### 1. Start the database

```bash
# From the repository root
docker compose up -d
```

Docker Compose brings up the `airport_postgres` container on port **5432**.
On the **first start**, PostgreSQL automatically runs the scripts in `sql/` in alphabetical order:
`01_schema.sql` → `02_users.sql` → `03_data.sql`.

Make sure the database is ready for connections:

```bash
docker compose ps          # container status — "healthy"
docker compose logs --tail=20 postgres   # initialization log
```

### 2. Install Python dependencies

```bash
cd app
pip install -r requirements.txt
```

If you use a virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Run the Streamlit app

```bash
# From the app/ folder
streamlit run app.py
```

The app opens at **http://localhost:8501**.

### 4. Sign in

On the login page, choose a role and enter the password:

| Role | Password |
|---|---|
| Administrator | `admin_pass_2024` |
| Dispatcher | `dispatcher_pass_2024` |
| Cashier | `cashier_pass_2024` |

> The passwords are also shown directly on the login page under "Demo passwords".

---

## Container management

```bash
# Stop the container (data is kept in the pg_data Docker volume)
docker compose stop

# Remove the container AND all data (full database reset)
docker compose down -v

# Rebuild the database from scratch (re-runs the SQL scripts)
docker compose down -v && docker compose up -d
```

> The SQL init scripts run only on an empty data volume. After editing any file in `sql/`,
> run `docker compose down -v && docker compose up -d` for the changes to take effect.

---

## Environment variables (.env)

| Variable | Default | Description |
|---|---|---|
| `POSTGRES_DB` | `airport_db` | Database name |
| `POSTGRES_USER` | `postgres` | PostgreSQL superuser |
| `POSTGRES_PASSWORD` | `postgres_root_2024` | Superuser password |
| `PGPORT` | `5432` | PostgreSQL port |

The app also reads `DB_HOST` and `DB_PORT` from the environment (default `localhost:5432`).

---

## Direct connection to PostgreSQL

```bash
# Via Docker
docker exec -it airport_postgres psql -U postgres -d airport_db

# Via psql (if installed locally)
psql -h localhost -p 5432 -U postgres -d airport_db
```
