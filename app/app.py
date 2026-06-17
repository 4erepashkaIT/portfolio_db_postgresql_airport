"""Streamlit interface for the Auckland International Airport database."""

import os
from datetime import date, datetime, time as dtime

import pandas as pd
import psycopg2
import psycopg2.pool
import streamlit as st
import re

#APP CONFIGURATION

st.set_page_config(
    page_title="Auckland Airport DB",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    /* Trim extra top padding */
    .block-container { padding-top: 1.5rem; }

    /* Role badge */
    .role-badge {
        display: inline-block;
        padding: 3px 12px;
        border-radius: 20px;
        font-size: 13px;
        font-weight: 700;
        letter-spacing: 0.03em;
    }
    .badge-admin      { background: #fee2e2; color: #991b1b; }
    .badge-dispatcher { background: #dbeafe; color: #1e3a8a; }
    .badge-cashier    { background: #d1fae5; color: #065f46; }

    /* Tables — slightly rounded corners */
    div[data-testid="stDataFrame"] { border-radius: 8px; overflow: hidden; }

    /* Query buttons */
    .stButton > button[kind="primary"] { border-radius: 6px; font-weight: 600; }
    </style>
    """,
    unsafe_allow_html=True,
)

#User credentials
USERS: dict = {
    "Administrator": {
        "db_user":  "admin_user",
        "password": "admin_pass_2024",
        "badge":    "badge-admin",
    },
    "Dispatcher": {
        "db_user":  "dispatcher_user",
        "password": "dispatcher_pass_2024",
        "badge":    "badge-dispatcher",
    },
    "Cashier": {
        "db_user":  "cashier_user",
        "password": "cashier_pass_2024",
        "badge":    "badge-cashier",
    },
}

#PostgreSQL connection parameters
DB_CFG: dict = {
    "host":     os.getenv("DB_HOST",     "localhost"),
    "port":     int(os.getenv("DB_PORT", "5432")),
    "database": os.getenv("POSTGRES_DB", "airport_db"),
}

#Table labels
TABLE_LABELS: dict = {
    "airline":          "Airlines",
    "aircraft":         "Aircraft",
    "flight":           "Flights",
    "passenger":        "Passengers",
    "ticket":           "Tickets",
    "employee":         "Employees",
    "crew_assignment":  "Crew assignments",
}

ROLE_ALLOWED_TABLES = {
    "Administrator": list(TABLE_LABELS.keys()),
    "Dispatcher":    ["airline", "aircraft", "flight", "employee", "crew_assignment"],
    "Cashier":       ["flight", "passenger", "ticket"],
}

#Query list
QUERY_LIST = [
    "1.  Passengers on a flight",
    "2.  Flight schedule for a date",
    "3.  Flights of an airline",
    "4.  Free seats on a flight",
    "5.  Crew of a flight",
    "6.  Delayed and cancelled flights over a period",
    "7.  Aircraft usage history",
    "8.  Average ticket price by class",
    "9.  Top 5 passengers by spend",
    "10. Flights with available seats",
    "11. Number of flights by status",
    "12. Passengers without a middle name",
    "13. Employees with no assignments",
]

ROLE_ALLOWED_QUERIES = {
    "Administrator": list(range(1, 14)),
    "Dispatcher":    list(range(1, 14)),
    "Cashier":       [1, 2, 4, 6, 7, 8, 9, 10, 11, 12],
}

#Standard crew roles
CREW_ROLES = [
    "captain",
    "first officer",
    "navigator",
    "flight engineer",
    "senior flight attendant",
    "flight attendant",
]

#Airline registration countries
OTHER_COUNTRY = "Other…"
COUNTRIES = [
    "New Zealand", "Australia", "Singapore", "United Arab Emirates",
    "Hong Kong", "Fiji", "United States", "United Kingdom",
    "China", "Japan", OTHER_COUNTRY,
]

#DATABASE HELPERS

@st.cache_resource(show_spinner=False)
def _get_pool(user: str, password: str) -> psycopg2.pool.ThreadedConnectionPool:
    """Connection pool per database user.

    `st.cache_resource` keeps the pool between script reruns, so a new TCP
    connection is not opened on every request. The pool is thread-safe.
    """
    return psycopg2.pool.ThreadedConnectionPool(
        minconn=1, maxconn=5, **DB_CFG, user=user, password=password
    )


def _borrow_conn():
    """Take a connection from the current user's pool."""
    c = st.session_state["creds"]
    return _get_pool(c["user"], c["password"])


def query_df(sql: str, params=None) -> pd.DataFrame:
    """Run a SELECT and return a DataFrame.

    On error it shows the message via st.error and returns an empty DataFrame
    flagged with `attrs["query_error"]`, so show_result does not duplicate it.
    """
    pool = _borrow_conn()
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            cols = [d[0] for d in (cur.description or [])]
            df = pd.DataFrame(cur.fetchall(), columns=cols)
        conn.commit()
        return df
    except Exception as exc:
        try:
            conn.rollback()
        except Exception:
            pass
        st.error(f"Query error: {exc}")
        df = pd.DataFrame()
        df.attrs["query_error"] = True
        return df
    finally:
        pool.putconn(conn, close=bool(conn.closed))


def run_cmd(sql: str, params=None, return_rowcount: bool = False) -> tuple:
    """Run an INSERT / UPDATE / DELETE.

    Returns (ok: bool, error: str|None) or, when return_rowcount=True,
    (ok: bool, error: str|None, affected_rows: int).
    """
    pool = _borrow_conn()
    conn = pool.getconn()
    rowcount = 0
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rowcount = cur.rowcount
        conn.commit()
        return (True, None, rowcount) if return_rowcount else (True, None)
    except Exception as exc:
        try:
            conn.rollback()
        except Exception:
            pass
        return (False, str(exc), 0) if return_rowcount else (False, str(exc))
    finally:
        pool.putconn(conn, close=bool(conn.closed))


def _safe_table(tbl: str) -> str:
    """Guard against SQL injection when interpolating a table name.

    A table name cannot be passed as a parameter (%s), so it is checked against
    the whitelist of known tables before being interpolated into an f-string.
    """
    if tbl not in TABLE_LABELS:
        raise ValueError(f"Invalid table name: {tbl!r}")
    return tbl


#Role checks
def role() -> str:
    return st.session_state.get("role", "")

def is_admin() -> bool:
    return role() == "Administrator"

def is_dispatcher() -> bool:
    return role() in ("Administrator", "Dispatcher")

def is_cashier() -> bool:
    return role() in ("Administrator", "Cashier")


#Query result output
def show_result(df: pd.DataFrame) -> None:
    if df.attrs.get("query_error"):
        return  # query_df already showed the error — do not add "No data found"
    if df.empty:
        st.info("No data found.")
    else:
        st.caption(f"Rows found: **{len(df)}**")
        st.dataframe(df, width="stretch")

def page_login() -> None:
    _, col, _ = st.columns([1, 1.2, 1])
    with col:
        st.markdown("## Auckland Airport DB")
        st.caption("Database management system for Auckland International Airport")
        st.divider()
        sel_role = st.selectbox("User role", list(USERS.keys()))
        pwd = st.text_input("Password", type="password", placeholder="Enter password...")

        if st.button("Sign in", type="primary", width="stretch"):
            if pwd == USERS[sel_role]["password"]:
                st.session_state["role"] = sel_role
                st.session_state["creds"] = {
                    "user":     USERS[sel_role]["db_user"],
                    "password": USERS[sel_role]["password"],
                }
                st.rerun()
            else:
                st.error("Incorrect password. Please try again.")

        with st.expander("Demo passwords"):
            for r, u in USERS.items():
                st.caption(f"**{r}:** `{u['password']}`")

def sidebar_nav() -> str:
    r = role()
    u = USERS[r]
    st.sidebar.markdown("## Auckland Airport DB")
    st.sidebar.markdown(
        f'<span class="role-badge {u["badge"]}">{r}</span>',
        unsafe_allow_html=True,
    )
    st.sidebar.caption(f"DB user: `{u['db_user']}`")
    st.sidebar.divider()

    nav_items = ["Home", "Tables", "Queries", "Reports", "Manage"]
    if is_admin():
        nav_items.append("Security")

    selected = st.sidebar.radio("Navigation", nav_items, label_visibility="collapsed")
    st.sidebar.divider()
    if st.sidebar.button("Sign out", width='stretch'):
        for k in ("role", "creds"):
            st.session_state.pop(k, None)
        st.rerun()
    return selected

def page_home() -> None:
    st.title("Home")
    st.markdown(f"Welcome! You are signed in as **{role()}**.")
    st.divider()

    # Metrics only for tables available to the current role
    ROLE_TABLES = {
        "Administrator": [
            ("Airlines",         "airline"),
            ("Aircraft",         "aircraft"),
            ("Flights",          "flight"),
            ("Passengers",       "passenger"),
            ("Tickets",          "ticket"),
            ("Employees",        "employee"),
            ("Crew assignments", "crew_assignment"),
        ],
        "Dispatcher": [
            ("Airlines",         "airline"),
            ("Aircraft",         "aircraft"),
            ("Flights",          "flight"),
            ("Employees",        "employee"),
            ("Crew assignments", "crew_assignment"),
        ],
        "Cashier": [
            ("Flights",    "flight"),
            ("Passengers", "passenger"),
            ("Tickets",    "ticket"),
        ],
    }

    table_defs = ROLE_TABLES.get(role(), [])
    cols = st.columns(len(table_defs))
    for col, (lbl, tbl) in zip(cols, table_defs):
        res = query_df(f"SELECT COUNT(*) AS cnt FROM {_safe_table(tbl)};")
        cnt = int(res.iloc[0]["cnt"]) if not res.empty else "—"
        col.metric(lbl, cnt)

    st.divider()
    st.subheader("Your access rights")
    rights = {
        "Administrator": [
            "Full access to all tables (SELECT, INSERT, UPDATE, DELETE)",
            "Create and manage database users (CREATEDB, CREATEROLE)",
            "Database backup and restore",
        ],
        "Dispatcher": [
            "View all tables (SELECT)",
            "Add and modify flights (INSERT, UPDATE on flight)",
            "Manage crew assignments (INSERT, UPDATE, DELETE on crew_assignment)",
            "Update aircraft data (UPDATE on aircraft)",
            "No access to modify passenger data, tickets, or airlines",
        ],
        "Cashier": [
            "View flights, passengers, tickets (SELECT)",
            "Register new passengers (INSERT on passenger)",
            "Sell tickets (INSERT on ticket)",
            "Cancel (delete) tickets (DELETE on ticket)",
            "Update a passenger's phone and passport (UPDATE phone, passport_no)",
            "No access to modify flights, aircraft, employees, or airlines",
        ],
    }
    for item in rights.get(role(), []):
        st.markdown(f"- {item}")

    st.divider()
    st.subheader("Database overview")
    st.markdown("""
    The **Auckland Airport** database has **7 entities** linked by foreign keys. Every flight
    departs from or arrives at Auckland (enforced by the `chk_airport_hub` constraint).

    | Table | Description |
    |---|---|
    | `airline` | Airlines (IATA code, name, country) |
    | `aircraft` | Aircraft (tail number, model, capacity, year built) |
    | `flight` | Flights (number, route, departure/arrival time, status) |
    | `passenger` | Passengers (name, passport, date of birth, phone) |
    | `ticket` | Tickets (number, seat, class, price, purchase date) |
    | `employee` | Crew members (name, position, staff number) |
    | `crew_assignment` | Crew assignments to flights (M:N junction table) |

    DBMS: **PostgreSQL 16**. Deployment: **Docker Compose**.
    """)

def page_tables() -> None:
    st.title("Browse tables")
    allowed = ROLE_ALLOWED_TABLES.get(role(), [])
    c1, c2, c3 = st.columns([2, 1, 1])
    tbl    = c1.selectbox("Table", allowed,
                          format_func=lambda x: TABLE_LABELS[x])
    limit  = c2.selectbox("Rows", [10, 25, 50, 100], index=1)
    offset = c3.number_input("Offset", min_value=0, step=10, value=0)

    total_df = query_df(f"SELECT COUNT(*) AS cnt FROM {_safe_table(tbl)};")
    total    = int(total_df.iloc[0]["cnt"]) if not total_df.empty else 0
    data     = query_df(
        f"SELECT * FROM {_safe_table(tbl)} ORDER BY 1 LIMIT %s OFFSET %s;",
        (limit, offset),
    )

    if total == 0:
        shown = "—"
    else:
        shown = f"{offset + 1}–{min(offset + limit, total)}"
    st.caption(
        f"Table **{TABLE_LABELS[tbl]}** · Total rows: **{total}** · "
        f"Showing: {shown}"
    )

    if not data.empty:
        st.dataframe(data, width="stretch", height=420)
    else:
        st.info("Table is empty or not available for your role.")


def page_queries() -> None:
    st.title("Database queries")
    st.caption("13 queries with sorting, grouping, calculations and table joins.")
    allowed_indices = ROLE_ALLOWED_QUERIES.get(role(), list(range(1, 14)))
    filtered_queries = [q for q in QUERY_LIST
                        if int(q.split(".")[0].strip()) in allowed_indices]

    sel = st.selectbox("Select a query", filtered_queries)
    st.divider()
    idx = int(sel.split(".")[0].strip())
    _render_query(idx)


def _render_query(idx: int) -> None:  # noqa: C901
    if idx == 1:
        st.subheader("1. Passengers on a specific flight")
        st.caption(
            "Joins three tables: `passenger → ticket → flight`. "
            "`COALESCE` replaces `NULL` with a dash. Sorted by last name."
        )
        flight_no = st.text_input("Flight number", value="NZ0247",
                                  placeholder="e.g. NZ0247")
        if st.button("Run", key="q1"):
            show_result(query_df("""
                SELECT p.last_name                  AS last_name,
                       p.first_name                 AS first_name,
                       COALESCE(p.middle_name, '—') AS middle_name,
                       t.seat_no                    AS seat,
                       t.service_class              AS service_class,
                       t.price                      AS price_usd
                FROM passenger p
                JOIN ticket t ON t.passenger_id = p.passenger_id
                JOIN flight  f ON f.flight_id   = t.flight_id
                WHERE f.flight_number = %s
                ORDER BY p.last_name, p.first_name;
            """, (flight_no,)))

    elif idx == 2:
        st.subheader("2. Flight schedule for a specific date")
        st.caption(
            "Filter by date via `DATE(depart_at)`. Sorted by departure time."
        )
        d = st.date_input("Date", value=date(2026, 7, 3))
        if st.button("Run", key="q2"):
            show_result(query_df("""
                SELECT f.flight_number AS flight_number,
                       f.city_from     AS from_city,
                       f.city_to       AS to_city,
                       f.depart_at     AS departure,
                       f.arrive_at     AS arrival,
                       f.status        AS status
                FROM flight f
                WHERE DATE(f.depart_at) = %s
                ORDER BY f.depart_at;
            """, (d,)))

    elif idx == 3:
        st.subheader("3. Flights of a specific airline")
        st.caption(
            "Joins three tables: `flight → aircraft → airline`. Filter by IATA code."
        )
        airlines = query_df("SELECT iata_code, name FROM airline ORDER BY name;")
        if airlines.empty:
            st.warning("No airline data.")
            return
        al_opts = {
            f"{row['name']} ({row['iata_code']})": row["iata_code"]
            for _, row in airlines.iterrows()
        }
        al_label = st.selectbox("Airline", list(al_opts.keys()))
        if st.button("Run", key="q3"):
            show_result(query_df("""
                SELECT f.flight_number AS flight_number,
                       f.city_from     AS from_city,
                       f.city_to       AS to_city,
                       f.depart_at     AS departure,
                       f.status        AS status,
                       ac.model        AS aircraft_model
                FROM flight   f
                JOIN aircraft ac ON ac.tail_number = f.tail_number
                JOIN airline  al ON al.iata_code   = ac.iata_code
                WHERE al.iata_code = %s
                ORDER BY f.depart_at;
            """, (al_opts[al_label],)))

    elif idx == 4:
        st.subheader("4. Number of free seats on a specific flight")
        st.caption(
            "`COUNT` aggregation with `LEFT JOIN`. "
            "Aircraft capacity minus tickets sold."
        )
        flights = query_df(
            "SELECT flight_id, flight_number, city_from, city_to FROM flight ORDER BY depart_at;"
        )
        if flights.empty:
            st.warning("No flights in the database.")
            return
        f_opts = {
            f"[{r['flight_id']}] {r['flight_number']}  {r['city_from']} → {r['city_to']}": r["flight_id"]
            for _, r in flights.iterrows()
        }
        f_label = st.selectbox("Flight", list(f_opts.keys()), key="q4_sel")
        if st.button("Run", key="q4"):
            res = query_df("""
                SELECT f.flight_number                    AS flight_number,
                       f.city_from || ' → ' || f.city_to  AS route,
                       ac.capacity                        AS capacity,
                       COUNT(t.ticket_no)                 AS sold,
                       ac.capacity - COUNT(t.ticket_no)   AS free_seats
                FROM flight f
                JOIN aircraft ac   ON ac.tail_number = f.tail_number
                LEFT JOIN ticket t ON t.flight_id    = f.flight_id
                WHERE f.flight_id = %s
                GROUP BY f.flight_number, f.city_from, f.city_to, ac.capacity;
            """, (f_opts[f_label],))
            if not res.empty:
                row = res.iloc[0]
                m1, m2, m3 = st.columns(3)
                m1.metric("Capacity", int(row["capacity"]))
                m2.metric("Sold",     int(row["sold"]))
                m3.metric("Free",     int(row["free_seats"]))
                st.dataframe(res, width="stretch")

    elif idx == 5:
        st.subheader("5. Crew of a specific flight")
        st.caption(
            "Joins three tables: `employee → crew_assignment → flight`. "
            "Sorted by position and last name."
        )
        flights = query_df(
            "SELECT flight_id, flight_number, city_from, city_to FROM flight ORDER BY depart_at;"
        )
        if flights.empty:
            st.warning("No flights.")
            return
        f_opts = {
            f"[{r['flight_id']}] {r['flight_number']}  {r['city_from']} → {r['city_to']}": r["flight_id"]
            for _, r in flights.iterrows()
        }
        f_label = st.selectbox("Flight", list(f_opts.keys()), key="q5_sel")
        if st.button("Run", key="q5"):
            show_result(query_df("""
                SELECT e.last_name                  AS last_name,
                       e.first_name                 AS first_name,
                       COALESCE(e.middle_name, '—') AS middle_name,
                       e.position                   AS position,
                       ca.crew_role                 AS crew_role
                FROM employee        e
                JOIN crew_assignment ca ON ca.employee_id = e.employee_id
                WHERE ca.flight_id = %s
                ORDER BY e.position, e.last_name;
            """, (f_opts[f_label],)))

    elif idx == 6:
        st.subheader("6. Delayed and cancelled flights over a period")
        st.caption(
            "Filter `IN ('delayed', 'cancelled')` and `BETWEEN` over a date range."
        )
        c1, c2 = st.columns(2)
        d1 = c1.date_input("From", value=date(2026, 5, 1),   key="q6d1")
        d2 = c2.date_input("To",   value=date.today(), key="q6d2")
        if st.button("Run", key="q6"):
            show_result(query_df("""
                SELECT f.flight_number AS flight_number,
                       f.city_from     AS from_city,
                       f.city_to       AS to_city,
                       f.depart_at     AS departure,
                       f.status        AS status
                FROM flight f
                WHERE f.status IN ('delayed', 'cancelled')
                  AND DATE(f.depart_at) BETWEEN %s AND %s
                ORDER BY f.depart_at;
            """, (d1, d2)))

    elif idx == 7:
        st.subheader("7. Aircraft usage history over a period")
        st.caption(
            "JOIN `flight → aircraft`. Filter by tail number and date range."
        )
        aircrafts = query_df("SELECT tail_number, model FROM aircraft ORDER BY tail_number;")
        if aircrafts.empty:
            st.warning("No aircraft.")
            return
        ac_opts = {
            f"{r['tail_number']} ({r['model']})": r["tail_number"]
            for _, r in aircrafts.iterrows()
        }
        ac_label = st.selectbox("Aircraft", list(ac_opts.keys()))
        c1, c2 = st.columns(2)
        d1 = c1.date_input("From", value=date(2026, 1, 1),   key="q7d1")
        d2 = c2.date_input("To",   value=date.today(), key="q7d2")
        if st.button("Run", key="q7"):
            show_result(query_df("""
                SELECT f.flight_number AS flight_number,
                       f.city_from     AS from_city,
                       f.city_to       AS to_city,
                       f.depart_at     AS departure,
                       f.arrive_at     AS arrival,
                       f.status        AS status
                FROM flight   f
                JOIN aircraft ac ON ac.tail_number = f.tail_number
                WHERE ac.tail_number = %s
                  AND DATE(f.depart_at) BETWEEN %s AND %s
                ORDER BY f.depart_at;
            """, (ac_opts[ac_label], d1, d2)))

    elif idx == 8:
        st.subheader("8. Average ticket price by service class")
        st.caption(
            "Aggregate functions `AVG`, `MIN`, `MAX` with `GROUP BY service_class`."
        )
        if st.button("Run", key="q8"):
            res = query_df("""
                SELECT service_class        AS service_class,
                       COUNT(*)             AS tickets,
                       ROUND(AVG(price), 2) AS avg_price,
                       MIN(price)           AS min_price,
                       MAX(price)           AS max_price
                FROM ticket
                GROUP BY service_class
                ORDER BY avg_price DESC;
            """)
            show_result(res)
            if not res.empty:
                st.markdown("**Average price by class (USD)**")
                st.bar_chart(res.set_index("service_class")["avg_price"].astype(float),
                             height=220, color="#4f8ef7")

    elif idx == 9:
        st.subheader("9. Top 5 passengers by total ticket spend")
        st.caption(
            "`GROUP BY` passenger, `SUM(price)`, `DESC` sort, `LIMIT 5`."
        )
        if st.button("Run", key="q9"):
            show_result(query_df("""
                SELECT p.last_name || ' ' || p.first_name AS passenger,
                       COUNT(t.ticket_no)                 AS tickets_bought,
                       SUM(t.price)                       AS total_spent_usd
                FROM passenger p
                JOIN ticket t ON t.passenger_id = p.passenger_id
                GROUP BY p.passenger_id, p.last_name, p.first_name
                ORDER BY total_spent_usd DESC
                LIMIT 5;
            """))

    elif idx == 10:
        st.subheader("10. Flights with seats still available")
        st.caption(
            "Filter via `HAVING COUNT(ticket_no) < capacity`. Excludes cancelled flights."
        )
        if st.button("Run", key="q10"):
            show_result(query_df("""
                SELECT f.flight_id                          AS flight_id,
                       f.flight_number                      AS flight_number,
                       f.city_from || ' → ' || f.city_to    AS route,
                       f.depart_at                          AS departure,
                       ac.capacity                          AS capacity,
                       COUNT(t.ticket_no)                   AS sold,
                       ac.capacity - COUNT(t.ticket_no)     AS free
                FROM flight   f
                JOIN aircraft ac   ON ac.tail_number = f.tail_number
                LEFT JOIN ticket t ON t.flight_id    = f.flight_id
                WHERE f.status NOT IN ('cancelled')
                GROUP BY f.flight_id, f.flight_number, f.city_from,
                         f.city_to, f.depart_at, ac.capacity
                HAVING COUNT(t.ticket_no) < ac.capacity
                ORDER BY f.depart_at;
            """))

    elif idx == 11:
        st.subheader("11. Number of flights by status")
        st.caption("`GROUP BY status` + `COUNT(*)`. Simple aggregation query.")
        if st.button("Run", key="q11"):
            res = query_df("""
                SELECT status AS status, COUNT(*) AS num_flights
                FROM flight
                GROUP BY status
                ORDER BY num_flights DESC;
            """)
            show_result(res)
            if not res.empty:
                st.bar_chart(res.set_index("status")["num_flights"], height=220)

    elif idx == 12:
        st.subheader("12. Passengers without a middle name")
        st.caption(
            "Filter `WHERE middle_name IS NULL`. The middle name is optional in the model."
        )
        if st.button("Run", key="q12"):
            show_result(query_df("""
                SELECT passenger_id AS passenger_id,
                       last_name    AS last_name,
                       first_name   AS first_name,
                       passport_no  AS passport,
                       phone        AS phone
                FROM passenger
                WHERE middle_name IS NULL
                ORDER BY last_name;
            """))

    elif idx == 13:
        st.subheader("13. Employees with no flight assignments")
        st.caption(
            "Correlated `NOT EXISTS` subquery. Finds employees not used on any flight."
        )
        if st.button("Run", key="q13"):
            show_result(query_df("""
                SELECT e.employee_id                       AS employee_id,
                       e.last_name || ' ' || e.first_name  AS full_name,
                       e.position                          AS position,
                       e.hire_date                         AS hire_date
                FROM employee e
                WHERE NOT EXISTS (
                    SELECT 1 FROM crew_assignment ca
                    WHERE ca.employee_id = e.employee_id
                )
                ORDER BY e.last_name;
            """))

#  REPORTS — helper functions

def _report_flights() -> None:
    st.subheader("Flight load report")
    st.caption(
        "For each flight: capacity, sales, load percentage and total revenue. "
        "Aggregate functions `COUNT`, `SUM`, `ROUND`."
    )
    if st.button("Generate", key="rep1"):
        res = query_df("""
            SELECT f.flight_number                                     AS flight_number,
                   f.city_from || ' → ' || f.city_to                   AS route,
                   f.depart_at::DATE                                   AS date,
                   f.status                                            AS status,
                   ac.capacity                                         AS capacity,
                   COUNT(t.ticket_no)                                  AS sold,
                   ROUND(COUNT(t.ticket_no)::NUMERIC /
                         ac.capacity * 100, 1)                         AS load_pct,
                   COALESCE(SUM(t.price), 0)                           AS revenue_usd
            FROM flight   f
            JOIN aircraft ac   ON ac.tail_number = f.tail_number
            LEFT JOIN ticket t ON t.flight_id    = f.flight_id
            GROUP BY f.flight_id, f.flight_number, f.city_from,
                     f.city_to, f.depart_at, f.status, ac.capacity
            ORDER BY load_pct DESC;
        """)
        if not res.empty:
            st.dataframe(res, width="stretch")
            st.markdown("**Flight load, %**")
            st.bar_chart(
                res.set_index("flight_number")["load_pct"].astype(float),
                height=280, color="#22c55e",
            )

def _report_employees() -> None:
    st.subheader("Employee report")
    st.caption(
        "Full name, position, years of service (via `AGE`) and number of flights in the period. "
        "`LEFT JOIN` so employees without assignments are shown too."
    )
    c1, c2 = st.columns(2)
    d1 = c1.date_input("From", value=date(2026, 1, 1),   key="rep2d1")
    d2 = c2.date_input("To",   value=date.today(), key="rep2d2")
    if st.button("Generate", key="rep2"):
        res = query_df("""
            SELECT e.employee_id                                          AS employee_id,
                   TRIM(e.last_name || ' ' || e.first_name || ' ' ||
                        COALESCE(e.middle_name, ''))                      AS full_name,
                   e.position                                             AS position,
                   EXTRACT(YEAR FROM AGE(CURRENT_DATE, e.hire_date))::INT AS years_of_service,
                   COUNT(f.flight_id)                                     AS flights_in_period
            FROM employee e
            LEFT JOIN crew_assignment ca ON ca.employee_id = e.employee_id
            LEFT JOIN flight f           ON f.flight_id    = ca.flight_id
                                        AND DATE(f.depart_at) BETWEEN %s AND %s
            GROUP BY e.employee_id, e.last_name, e.first_name,
                     e.middle_name, e.position, e.hire_date
            ORDER BY flights_in_period DESC, e.last_name;
        """, (d1, d2))
        if not res.empty:
            st.dataframe(res, width="stretch")


def _report_airlines() -> None:
    st.subheader("Airline report")
    st.caption(
        "For each airline: fleet size, number of completed flights and total revenue. "
        "`COUNT DISTINCT` + `FILTER (WHERE ...)`. "
        "Four tables: `airline → aircraft → flight → ticket`."
    )
    if st.button("Generate", key="rep3"):
        res = query_df("""
            SELECT al.iata_code                                          AS iata_code,
                   al.name                                               AS airline,
                   al.country                                            AS country,
                   COUNT(DISTINCT ac.tail_number)                        AS aircraft_count,
                   COUNT(DISTINCT f.flight_id)
                       FILTER (WHERE f.status = 'completed')             AS flights_completed,
                   COALESCE(SUM(t.price), 0)                             AS revenue_usd
            FROM airline al
            LEFT JOIN aircraft ac ON ac.iata_code  = al.iata_code
            LEFT JOIN flight   f  ON f.tail_number = ac.tail_number
            LEFT JOIN ticket   t  ON t.flight_id   = f.flight_id
            GROUP BY al.iata_code, al.name, al.country
            ORDER BY revenue_usd DESC;
        """)
        if not res.empty:
            st.dataframe(res, width="stretch")
            st.markdown("**Revenue by airline (USD)**")
            st.bar_chart(
                res.set_index("airline")["revenue_usd"].astype(float),
                height=280, color="#6366f1",
            )


def page_reports() -> None:
    st.title("Reports")
    st.caption("Summary reports with grouping, aggregation and data visualization.")

    report_defs = [("Flight load", _report_flights)]
    if role() != "Cashier":
        report_defs += [
            ("By employee", _report_employees),
            ("By airline",  _report_airlines),
        ]

    tabs = st.tabs([label for label, _ in report_defs])
    for widget, (_, render_fn) in zip(tabs, report_defs):
        with widget:
            render_fn()

def _aircraft_location(tail_number: str) -> str:
    """Return the aircraft's current location based on its latest flight.

    Logic:
    - If there is an active flight (departed but not yet arrived) — "In air (from → to)"
    - Otherwise — city_to of the last completed/landed flight
    - If there are no flights — "Unknown"
    """
    airborne = query_df("""
        SELECT city_from, city_to
        FROM flight
        WHERE tail_number = %s
          AND status NOT IN ('cancelled')
          AND depart_at <= NOW()
          AND arrive_at  > NOW()
        ORDER BY depart_at DESC
        LIMIT 1;
    """, (tail_number,))
    if not airborne.empty:
        r = airborne.iloc[0]
        return f"In air ({r['city_from']} → {r['city_to']})"

    last = query_df("""
        SELECT city_to, arrive_at, status
        FROM flight
        WHERE tail_number = %s
          AND status NOT IN ('cancelled')
          AND arrive_at <= NOW()
        ORDER BY arrive_at DESC
        LIMIT 1;
    """, (tail_number,))
    if not last.empty:
        return f"At {last.iloc[0]['city_to']}"

    upcoming = query_df("""
        SELECT city_from, depart_at
        FROM flight
        WHERE tail_number = %s
          AND status NOT IN ('cancelled')
          AND depart_at > NOW()
        ORDER BY depart_at ASC
        LIMIT 1;
    """, (tail_number,))
    if not upcoming.empty:
        r = upcoming.iloc[0]
        return f"Awaiting departure from {r['city_from']}"

    return "Unknown (no flights)"

def page_manage() -> None:
    st.title("Manage data")
    st.caption("Available operations depend on your role.")

    tab_defs: list = []
    if is_dispatcher():
        tab_defs += [
            ("Add flight",    _tab_add_flight),
            ("Flight status", _tab_update_flight_status),
            ("Assign crew",   _tab_assign_crew),
        ]
    if is_cashier():
        tab_defs += [
            ("Add passenger",  _tab_add_passenger),
            ("Sell ticket",    _tab_add_ticket),
            ("Edit passenger", _tab_update_passenger),
        ]
    if is_admin():
        tab_defs += [
            ("Airline",      _tab_add_airline),
            ("Aircraft",     _tab_add_aircraft),
            ("Add employee", _tab_add_employee),
        ]

    if not tab_defs:
        st.info("Data management is not available for your role.")
        return

    tabs = st.tabs([label for label, _ in tab_defs])
    for widget, (_, render_fn) in zip(tabs, tab_defs):
        with widget:
            render_fn()

#Tabs: dispatcher

def _tab_add_flight() -> None:
    st.subheader("Add a new flight")
    aircrafts = query_df("SELECT tail_number, model FROM aircraft ORDER BY tail_number;")
    if aircrafts.empty:
        st.warning("No aircraft available. Add an aircraft first.")
        return
    ac_opts = {
        f"{r['tail_number']} ({r['model']})": r["tail_number"]
        for _, r in aircrafts.iterrows()
    }

    # Aircraft chosen outside the form so its current location updates live
    c0a, c0b = st.columns(2)
    ac_label_pre = c0a.selectbox("Aircraft *", list(ac_opts.keys()), key="add_flight_ac")
    loc = _aircraft_location(ac_opts[ac_label_pre])
    c0b.markdown(f"**Current location:**  \n{loc}")
    st.divider()

    with st.form("form_add_flight"):
        c1, c2     = st.columns(2)
        flight_no  = c1.text_input("Flight number *", placeholder="NZ0101")
        ac_label   = c2.selectbox("Aircraft *", list(ac_opts.keys()),
                                  index=list(ac_opts.keys()).index(ac_label_pre))
        direction  = c1.radio("Direction *",
                              ["Departure from Auckland", "Arrival to Auckland"])
        other_city = c2.text_input(
            "Other city *", placeholder="Sydney",
            help="The city at the other end of the route. Auckland is fixed on the opposite side.",
        )
        dep_date   = c1.date_input("Departure date *", value=date.today())
        dep_time   = c1.time_input("Departure time *", value=dtime(8, 0))
        arr_date   = c2.date_input("Arrival date *", value=date.today())
        arr_time   = c2.time_input("Arrival time *", value=dtime(11, 0))
        submitted  = st.form_submit_button("Add flight", type="primary")
        if submitted:
            other_city = other_city.strip()
            if not all([flight_no, other_city]):
                st.error("Fill in all fields marked *")
            elif other_city.lower() == "auckland":
                st.error("The other city must be different from Auckland.")
            else:
                if direction == "Departure from Auckland":
                    city_from, city_to = "Auckland", other_city
                else:
                    city_from, city_to = other_city, "Auckland"
                depart_at = datetime.combine(dep_date, dep_time)
                arrive_at = datetime.combine(arr_date, arr_time)
                if arr_date < dep_date:
                    st.error("Arrival date cannot be earlier than departure date.")
                elif arr_date == dep_date and arr_time <= dep_time:
                    st.error("When the dates match, arrival time must be later than departure time.")
                elif arrive_at <= depart_at:
                    st.error("Arrival time must be later than departure time.")
                else:
                    # Is the aircraft already assigned to a flight that day?
                    conflict = query_df("""
                        SELECT flight_number, city_from, city_to, depart_at
                        FROM flight
                        WHERE tail_number = %s
                          AND DATE(depart_at) = %s
                          AND status <> 'cancelled'
                    """, (ac_opts[ac_label], dep_date))
                    if not conflict.empty:
                        r = conflict.iloc[0]
                        st.error(
                            f"Aircraft **{ac_opts[ac_label]}** is already assigned to flight "
                            f"**{r['flight_number']}** ({r['city_from']} → {r['city_to']}, "
                            f"departs {r['depart_at'].strftime('%H:%M')}) that day. "
                            f"Choose another aircraft or date."
                        )
                    else:
                        ok, err = run_cmd("""
                            INSERT INTO flight
                                (flight_number, city_from, city_to,
                                 depart_at, arrive_at, tail_number)
                            VALUES (%s, %s, %s, %s, %s, %s);
                        """, (flight_no, city_from, city_to,
                              depart_at, arrive_at, ac_opts[ac_label]))
                        if ok:
                            st.success(f"Flight **{flight_no}** added successfully.")
                        else:
                            st.error(f"Error: {err}")


def _tab_update_flight_status() -> None:
    st.subheader("Update flight status")
    flights = query_df("""
        SELECT flight_id, flight_number, city_from, city_to, status
        FROM flight ORDER BY depart_at DESC;
    """)
    if flights.empty:
        st.info("No flights in the database.")
        return
    f_opts = {
        f"[{r['flight_id']}] {r['flight_number']}  {r['city_from']} → {r['city_to']}  ({r['status']})": r["flight_id"]
        for _, r in flights.iterrows()
    }
    with st.form("form_upd_status"):
        f_label  = st.selectbox("Flight", list(f_opts.keys()))
        new_stat = st.selectbox(
            "New status",
            ["scheduled", "delayed", "cancelled", "completed"],
        )
        if st.form_submit_button("Update status", type="primary"):
            ok, err = run_cmd(
                "UPDATE flight SET status = %s WHERE flight_id = %s;",
                (new_stat, f_opts[f_label]),
            )
            if ok:
                st.success(f"Status changed to “{new_stat}”.")
            else:
                st.error(err)


def _tab_assign_crew() -> None:
    st.subheader("Assign an employee to a flight")
    flights   = query_df(
        "SELECT flight_id, flight_number, city_from, city_to FROM flight ORDER BY depart_at DESC;"
    )
    employees = query_df(
        "SELECT employee_id, last_name, first_name, position FROM employee ORDER BY last_name;"
    )
    if flights.empty or employees.empty:
        st.warning("No flights or employees available.")
        return

    f_opts = {
        f"[{r['flight_id']}] {r['flight_number']}  {r['city_from']} → {r['city_to']}": r["flight_id"]
        for _, r in flights.iterrows()
    }
    e_opts = {
        f"[{r['employee_id']}] {r['last_name']} {r['first_name']} ({r['position']})": r["employee_id"]
        for _, r in employees.iterrows()
    }

    with st.form("form_assign_crew"):
        f_label   = st.selectbox("Flight",   list(f_opts.keys()))
        e_label   = st.selectbox("Employee", list(e_opts.keys()))
        crew_role = st.selectbox("Crew role *", CREW_ROLES)
        if st.form_submit_button("Assign", type="primary"):
            if not crew_role:
                st.error("Specify the crew role.")
            else:
                ok, err, affected = run_cmd("""
                    INSERT INTO crew_assignment (flight_id, employee_id, crew_role)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (flight_id, employee_id) DO NOTHING;
                """, (f_opts[f_label], e_opts[e_label], crew_role), return_rowcount=True)
                if ok and affected:
                    st.success("Employee assigned to the flight.")
                elif ok:
                    st.warning("This employee is already assigned to this flight.")
                else:
                    st.error(err)

    st.divider()
    st.subheader("Remove an employee from a flight")
    assignments = query_df("""
        SELECT ca.flight_id, f.flight_number,
               e.last_name, e.first_name, e.employee_id, ca.crew_role
        FROM crew_assignment ca
        JOIN flight   f ON f.flight_id   = ca.flight_id
        JOIN employee e ON e.employee_id = ca.employee_id
        ORDER BY f.flight_number, e.last_name;
    """)
    if assignments.empty:
        st.info("No assignments yet.")
        return
    a_opts = {
        f"Flight {r['flight_number']} — {r['last_name']} {r['first_name']} ({r['crew_role']})": (r["flight_id"], r["employee_id"])
        for _, r in assignments.iterrows()
    }
    a_label = st.selectbox("Assignment to remove", list(a_opts.keys()))
    if st.button("Remove assignment", type="secondary"):
        fid, eid = a_opts[a_label]
        ok, err = run_cmd(
            "DELETE FROM crew_assignment WHERE flight_id = %s AND employee_id = %s;",
            (fid, eid),
        )
        if ok:
            st.success("Assignment removed.")
            st.rerun()
        else:
            st.error(err)

#  Tabs: CASHIER
def _valid_phone(s: str) -> bool:
    """International phone: optional leading +, then 8–15 digits."""
    return re.fullmatch(r"\+?\d{8,15}", re.sub(r"[\s()\-]", "", s)) is not None


def _valid_passport(s: str) -> bool:
    """Passport number: 6–9 letters or digits."""
    return re.fullmatch(r"[A-Za-z0-9]{6,9}", s.strip()) is not None


def _fmt_ticket_no(key: str) -> None:
    """Ticket number mask: digits only, exactly 13 (IATA format).

    Missing digits are padded with leading zeros directly in the field (visible
    in the UI); extra digits beyond 13 are dropped. An empty field stays empty.
    """
    digits = re.sub(r"\D", "", st.session_state[key])[:13]
    st.session_state[key] = digits.zfill(13) if digits else ""


def _fmt_iata(key: str) -> None:
    """IATA code mask: 2 alphanumeric characters, uppercase.

    Codes like S7 or U6 are valid, so digits are not stripped.
    """
    st.session_state[key] = re.sub(r"[^A-Za-z0-9]", "", st.session_state[key]).upper()[:2]


def _tab_add_passenger() -> None:
    st.subheader("Register a new passenger")

    c1, c2 = st.columns(2)
    last_name   = c1.text_input("Last name *")
    first_name  = c2.text_input("First name *")
    middle_name = c1.text_input("Middle name (optional)")
    passport_no = c1.text_input(
        "Passport number *",
        placeholder="AB123456",
        help="6–9 letters or digits.",
    )
    birth_date = c1.date_input(
        "Date of birth *",
        value=date(1990, 1, 1),
        min_value=date(1900, 1, 1),
        max_value=date.today(),
    )
    phone = c2.text_input(
        "Phone *",
        placeholder="+64 21 555 0143",
        help="International format, e.g. +64 21 555 0143.",
    )

    if st.button("Add passenger", type="primary"):
        errors = []
        if not all([last_name, first_name]):
            errors.append("Fill in the Last name and First name.")
        if not _valid_passport(passport_no):
            errors.append("Passport number must be 6–9 letters or digits.")
        if not _valid_phone(phone):
            errors.append("Phone must be in international format (optional + and 8–15 digits).")

        if errors:
            for e in errors:
                st.error(e)
        else:
            ok, err = run_cmd("""
                INSERT INTO passenger
                    (last_name, first_name, middle_name,
                     passport_no, birth_date, phone)
                VALUES (%s, %s, %s, %s, %s, %s);
            """, (
                last_name, first_name,
                middle_name if middle_name else None,
                passport_no.strip(), birth_date, phone.strip(),
            ))
            if ok:
                st.success(f"Passenger **{last_name} {first_name}** added.")
                st.rerun()
            else:
                st.error(f"Error: {err}")


def _tab_add_ticket() -> None:
    st.subheader("Sell a ticket")
    st.caption(
        "Tickets can be sold for flights that have not departed yet; delayed flights "
        "remain available after their original departure time. Cancelled and completed "
        "flights are not listed."
    )

    # Initialize and deferred-clear the ticket number field
    if "tkt_no" not in st.session_state:
        st.session_state["tkt_no"] = ""
    if st.session_state.get("tkt_clear"):
        st.session_state["tkt_no"] = ""
        st.session_state["tkt_clear"] = False

    passengers = query_df("""
        SELECT passenger_id, last_name, first_name, passport_no
        FROM passenger ORDER BY last_name;
    """)
    avail_flights = query_df("""
        SELECT f.flight_id, f.flight_number, f.city_from, f.city_to,
               f.depart_at,
               ac.capacity - COUNT(t.ticket_no) AS free_seats
        FROM flight   f
        JOIN aircraft ac   ON ac.tail_number = f.tail_number
        LEFT JOIN ticket t ON t.flight_id    = f.flight_id
        WHERE f.status NOT IN ('cancelled', 'completed')
          AND (f.depart_at > NOW() OR f.status = 'delayed')
        GROUP BY f.flight_id, f.flight_number, f.city_from,
                 f.city_to, f.depart_at, ac.capacity
        HAVING ac.capacity - COUNT(t.ticket_no) > 0
        ORDER BY f.depart_at;
    """)

    if passengers.empty:
        st.warning("No registered passengers. Add a passenger first.")
        return
    if avail_flights.empty:
        st.warning("No available flights with free seats.")
        return

    p_opts = {
        f"[{r['passenger_id']}] {r['last_name']} {r['first_name']}  (passport: {r['passport_no']})": r["passenger_id"]
        for _, r in passengers.iterrows()
    }
    f_opts = {
        f"[{r['flight_id']}] {r['flight_number']}  {r['city_from']} → {r['city_to']}  ({int(r['free_seats'])} free seats)": r["flight_id"]
        for _, r in avail_flights.iterrows()
    }

    # Widgets outside st.form so the ticket number mask updates live
    c1, c2     = st.columns(2)
    c1.text_input(
        "Ticket number *",
        key="tkt_no",
        max_chars=13,
        placeholder="0000000000000",
        on_change=_fmt_ticket_no,
        args=("tkt_no",),
        help="13 digits (IATA format). Missing digits are padded with leading zeros.",
    )
    p_label    = c2.selectbox("Passenger *", list(p_opts.keys()))
    f_label    = c1.selectbox("Flight *",    list(f_opts.keys()))
    seat_no    = c2.text_input("Seat *", placeholder="12A")
    svc_class  = c1.selectbox("Class", ["economy", "business", "first"])
    price      = c2.number_input(
        "Price (USD) *", min_value=1.0, step=50.0, value=300.0, format="%.2f"
    )
    purch_date = c1.date_input("Purchase date", value=date.today())

    if st.button("Sell ticket", type="primary"):
        ticket_no = st.session_state["tkt_no"]
        if not ticket_no or not seat_no:
            st.error("Fill in all required fields (*)")
        elif len(ticket_no) != 13:
            st.error("Ticket number must contain exactly 13 digits.")
        else:
            ok, err = run_cmd("""
                INSERT INTO ticket
                    (ticket_no, seat_no, service_class, price,
                     purchase_date, passenger_id, flight_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s);
            """, (
                ticket_no, seat_no, svc_class, price,
                purch_date, p_opts[p_label], f_opts[f_label],
            ))
            if ok:
                st.session_state["tkt_clear"] = True
                st.success(f"Ticket **{ticket_no}** sold successfully.")
                st.rerun()
            else:
                st.error(f"Error: {err}")

    #Cancel (delete) a ticket
    st.divider()
    st.subheader("Cancel a ticket")
    sold = query_df("""
        SELECT t.ticket_no, t.seat_no, t.price,
               p.last_name, p.first_name, f.flight_number
        FROM ticket t
        JOIN passenger p ON p.passenger_id = t.passenger_id
        JOIN flight    f ON f.flight_id    = t.flight_id
        ORDER BY t.ticket_no;
    """)
    if sold.empty:
        st.info("No tickets sold yet.")
        return
    t_opts = {
        f"No. {r['ticket_no']} · flight {r['flight_number']} · seat {r['seat_no']} · "
        f"{r['last_name']} {r['first_name']} ({r['price']} USD)": r["ticket_no"]
        for _, r in sold.iterrows()
    }
    t_label = st.selectbox("Ticket to cancel", list(t_opts.keys()))
    if st.button("Cancel ticket", type="secondary"):
        ok, err = run_cmd(
            "DELETE FROM ticket WHERE ticket_no = %s;",
            (t_opts[t_label],),
        )
        if ok:
            st.success("Ticket cancelled.")
            st.rerun()
        else:
            st.error(err)


def _tab_update_passenger() -> None:
    st.subheader("Edit passenger details")
    st.caption("The cashier can change only the phone and passport number.")

    passengers = query_df("""
        SELECT passenger_id, last_name, first_name, passport_no, phone
        FROM passenger ORDER BY last_name;
    """)
    if passengers.empty:
        st.info("No registered passengers.")
        return

    p_dict = {
        f"[{r['passenger_id']}] {r['last_name']} {r['first_name']}  (passport: {r['passport_no']})": r
        for _, r in passengers.iterrows()
    }
    p_label = st.selectbox("Select a passenger", list(p_dict.keys()))
    pdata   = p_dict[p_label]

    with st.form("form_upd_passenger"):
        new_phone    = st.text_input("Phone",           value=str(pdata["phone"]))
        new_passport = st.text_input("Passport number", value=str(pdata["passport_no"]))
        if st.form_submit_button("Save changes", type="primary"):
            errors = []
            if not _valid_passport(new_passport):
                errors.append("Passport number must be 6–9 letters or digits.")
            if not _valid_phone(new_phone):
                errors.append("Phone must be in international format (optional + and 8–15 digits).")

            if errors:
                for e in errors:
                    st.error(e)
            else:
                ok, err = run_cmd("""
                    UPDATE passenger
                       SET phone = %s, passport_no = %s
                     WHERE passenger_id = %s;
                """, (new_phone.strip(), new_passport.strip(), int(pdata["passenger_id"])))
                if ok:
                    st.success("Passenger details updated.")
                else:
                    st.error(err)

#Tabs: ADMINISTRATOR
def _tab_add_airline() -> None:
    st.subheader("Add an airline")

    if "air_iata" not in st.session_state:
        st.session_state["air_iata"] = ""

    # Widgets outside st.form so the IATA code mask updates live
    c1, c2  = st.columns(2)
    c1.text_input(
        "IATA code (2 chars) *",
        key="air_iata",
        placeholder="NZ",
        on_change=_fmt_iata,
        args=("air_iata",),
        help="Exactly 2 alphanumeric characters. Extra characters are removed automatically.",
    )
    name    = c2.text_input("Airline name *")
    country = st.selectbox("Country of registration *", COUNTRIES)
    if country == OTHER_COUNTRY:
        country = st.text_input("Specify the country *").strip()

    if st.button("Add", type="primary"):
        iata = st.session_state["air_iata"]
        if not all([iata, name, country]):
            st.error("Fill in all required fields (*)")
        elif len(iata) != 2:
            st.error("The IATA code must be exactly 2 characters.")
        else:
            ok, err = run_cmd(
                "INSERT INTO airline (iata_code, name, country) VALUES (%s, %s, %s);",
                (iata, name, country),
            )
            if ok:
                st.success(f"Airline **{name}** ({iata}) added.")
            else:
                st.error(err)

    st.divider()
    st.caption("Current airlines:")
    airlines = query_df("SELECT * FROM airline ORDER BY name;")
    st.dataframe(airlines, width="stretch")

    #Delete an airline
    st.subheader("Delete an airline")
    if airlines.empty:
        st.info("No airlines yet.")
        return
    al_opts = {
        f"{r['name']} ({r['iata_code']})": r["iata_code"]
        for _, r in airlines.iterrows()
    }
    al_label = st.selectbox("Airline to delete", list(al_opts.keys()))
    if st.button("Delete airline", type="secondary"):
        ok, err = run_cmd(
            "DELETE FROM airline WHERE iata_code = %s;",
            (al_opts[al_label],),
        )
        if ok:
            st.success("Airline deleted.")
            st.rerun()
        else:
            st.error(
                "Could not delete: aircraft are linked to this airline. "
                "Delete or reassign its aircraft first.\n\n"
                f"Details: {err}"
            )

def _tab_add_aircraft() -> None:
    st.subheader("Add an aircraft")
    airlines = query_df("SELECT iata_code, name FROM airline ORDER BY name;")
    if airlines.empty:
        st.warning("No airlines. Add an airline first.")
        return
    al_opts = {
        f"{r['name']} ({r['iata_code']})": r["iata_code"]
        for _, r in airlines.iterrows()
    }
    with st.form("form_add_aircraft"):
        c1, c2   = st.columns(2)
        tail     = c1.text_input("Tail number *", placeholder="ZK-NZE")
        model    = c2.text_input("Model *",       placeholder="Boeing 787-9")
        capacity = c1.number_input(
            "Capacity (seats) *", min_value=1, max_value=853, value=180, step=1
        )
        year     = c2.number_input(
            "Year built *",
            min_value=1950, max_value=date.today().year,
            value=2015, step=1,
        )
        al_label = st.selectbox("Airline *", list(al_opts.keys()))
        if st.form_submit_button("Add aircraft", type="primary"):
            if not all([tail, model]):
                st.error("Fill in all required fields (*)")
            else:
                ok, err = run_cmd("""
                    INSERT INTO aircraft (tail_number, model, capacity, year_built, iata_code)
                    VALUES (%s, %s, %s, %s, %s);
                """, (tail, model, capacity, year, al_opts[al_label]))
                if ok:
                    st.success(f"Aircraft **{tail}** ({model}) added.")
                else:
                    st.error(err)

    st.divider()
    st.caption("Current fleet:")
    aircrafts = query_df("SELECT * FROM aircraft ORDER BY tail_number;")
    if not aircrafts.empty:
        aircrafts["location"] = aircrafts["tail_number"].apply(_aircraft_location)
    st.dataframe(aircrafts, width="stretch")

    #Delete an aircraft
    st.subheader("Delete an aircraft")
    if aircrafts.empty:
        st.info("No aircraft yet.")
        return
    ac_del_opts = {
        f"{r['tail_number']} ({r['model']})": r["tail_number"]
        for _, r in aircrafts.iterrows()
    }
    ac_del_label = st.selectbox("Aircraft to delete", list(ac_del_opts.keys()))
    if st.button("Delete aircraft", type="secondary"):
        ok, err = run_cmd(
            "DELETE FROM aircraft WHERE tail_number = %s;",
            (ac_del_opts[ac_del_label],),
        )
        if ok:
            st.success("Aircraft deleted.")
            st.rerun()
        else:
            st.error(
                "Could not delete: flights are assigned to this aircraft. "
                "Delete or reassign the related flights first.\n\n"
                f"Details: {err}"
            )


# Allowed employee positions (must match chk_position in the schema)
EMPLOYEE_POSITIONS = ["pilot", "co-pilot", "flight attendant"]

def _tab_add_employee() -> None:
    st.subheader("Register a new employee")
    st.caption(
        "Register a crew member. The staff number is a 6-digit number (100000–999999); "
        "the position comes from the approved list."
    )
    with st.form("form_add_employee"):
        c1, c2      = st.columns(2)
        employee_id = c1.number_input(
            "Staff number *",
            min_value=100000, max_value=999999, value=100000, step=1,
            help="6-digit staff number (100000–999999).",
        )
        position    = c2.selectbox("Position *", EMPLOYEE_POSITIONS)
        last_name   = c1.text_input("Last name *")
        first_name  = c2.text_input("First name *")
        middle_name = c1.text_input("Middle name (optional)")
        hire_date   = c2.date_input(
            "Hire date *",
            value=date.today(),
            min_value=date(1950, 1, 1),
            max_value=date.today(),
        )
        if st.form_submit_button("Add employee", type="primary"):
            if not all([last_name, first_name]):
                st.error("Fill in the Last name and First name.")
            else:
                ok, err = run_cmd("""
                    INSERT INTO employee
                        (employee_id, last_name, first_name, middle_name,
                         position, hire_date)
                    VALUES (%s, %s, %s, %s, %s, %s);
                """, (
                    int(employee_id), last_name, first_name,
                    middle_name if middle_name else None,
                    position, hire_date,
                ))
                if ok:
                    st.success(
                        f"Employee **{last_name} {first_name}** "
                        f"(staff no. {int(employee_id)}) added."
                    )
                else:
                    st.error(
                        "Could not add the employee. "
                        "The staff number may already be in use.\n\n"
                        f"Details: {err}"
                    )

    st.divider()
    st.caption("Current employees:")
    st.dataframe(
        query_df("SELECT * FROM employee ORDER BY last_name;"),
        width="stretch",
    )

#page: security (Administrator only)

def page_security() -> None:
    st.title("Database security")
    if not is_admin():
        st.error("Access denied. Administrator role required.")
        return

    st.markdown(
        "Security is implemented with **PostgreSQL**: a role-based access model at the "
        "database level. The **principle of least privilege** — each user gets only the "
        "rights needed to perform their job."
    )
    st.divider()

    perms = pd.DataFrame({
        "User":           ["admin_user",          "dispatcher_user",                   "cashier_user"],
        "Role":           ["Administrator",        "Dispatcher",                        "Cashier"],
        "SELECT":         ["All tables",           "All tables",                        "flight, passenger, ticket, aircraft"],
        "INSERT":         ["All tables",           "flight, crew_assignment",           "passenger, ticket"],
        "UPDATE":         ["All tables",           "flight, aircraft, crew_assignment", "passenger (phone, passport_no)"],
        "DELETE":         ["All tables",           "crew_assignment",                   "ticket"],
        "Special rights": ["CREATEDB CREATEROLE",  "—",                                 "—"],
    })
    st.dataframe(perms, width="stretch", hide_index=True)

    st.divider()
    with st.expander("View code: 02_users.sql"):
        st.code("""

--  02_users.sql — Create users and assign privileges

-- ── Administrator ──────────────────────────────────────
CREATE USER admin_user WITH PASSWORD 'admin_pass_2024' CREATEDB CREATEROLE;
GRANT ALL PRIVILEGES ON ALL TABLES    IN SCHEMA public TO admin_user;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO admin_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT ALL ON TABLES    TO admin_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT ALL ON SEQUENCES TO admin_user;

-- ── Dispatcher ─────────────────────────────────────────
CREATE USER dispatcher_user WITH PASSWORD 'dispatcher_pass_2024';
-- Can read everything
GRANT SELECT ON ALL TABLES IN SCHEMA public TO dispatcher_user;
-- Manage flights and crew
GRANT INSERT, UPDATE, DELETE ON flight          TO dispatcher_user;
GRANT INSERT, UPDATE, DELETE ON crew_assignment TO dispatcher_user;
GRANT UPDATE                 ON aircraft        TO dispatcher_user;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO dispatcher_user;

-- ── Cashier ────────────────────────────────────────────
CREATE USER cashier_user WITH PASSWORD 'cashier_pass_2024';
-- Read: flights, passengers, tickets + aircraft (for JOINs in queries and reports)
GRANT SELECT ON flight, passenger, ticket, aircraft TO cashier_user;
GRANT INSERT ON passenger, ticket         TO cashier_user;
-- Cancel tickets
GRANT DELETE ON ticket                    TO cashier_user;
-- Only the passenger's phone and passport
GRANT UPDATE (phone, passport_no) ON passenger TO cashier_user;
GRANT USAGE, SELECT ON SEQUENCE
    passenger_passenger_id_seq TO cashier_user;
        """, language="sql")

    st.divider()
    st.subheader("Check current privileges")
    if st.button("Query privileges from information_schema", key="check_privs"):
        result = query_df("""
            SELECT grantee        AS grantee,
                   table_name     AS table_name,
                   privilege_type AS privilege
            FROM information_schema.role_table_grants
            WHERE grantee IN ('admin_user', 'dispatcher_user', 'cashier_user')
            ORDER BY grantee, table_name, privilege_type;
        """)
        if not result.empty:
            st.dataframe(result, width="stretch")
        else:
            st.info(
                "No privileges found, or the current session lacks rights to read "
                "`information_schema.role_table_grants`."
            )

    st.divider()
    st.subheader("Additional safeguards")
    st.markdown("""
    - **Trigger** `trg_check_seat_availability` — selling a ticket beyond the aircraft
      capacity is rejected with an error.
    - **`CHECK` constraint** on flight status: only `'scheduled'`, `'delayed'`,
      `'cancelled'`, `'completed'` are allowed.
    - **`UNIQUE (flight_id, seat_no)`** in `ticket` — the same seat cannot be sold
      twice on a flight.
    - **`UNIQUE passport_no`** in `passenger` — duplicate passports are not allowed.
    - **`CHECK (city_from = 'Auckland' OR city_to = 'Auckland')`** — only Auckland
      departures and arrivals are stored.
    - **Containerization** via Docker — the database is isolated from the host OS.
    """)

#entry point

def main() -> None:
    if "role" not in st.session_state:
        page_login()
        return

    page = sidebar_nav()

    dispatch = {
        "Home":     page_home,
        "Tables":   page_tables,
        "Queries":  page_queries,
        "Reports":  page_reports,
        "Manage":   page_manage,
        "Security": page_security,
    }
    dispatch.get(page, page_home)()

if __name__ == "__main__":
    main()
