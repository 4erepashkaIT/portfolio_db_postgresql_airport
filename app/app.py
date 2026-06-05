"""
app.py — Streamlit-интерфейс для базы данных «Аэропорт»
Курсовой проект по дисциплине «Базы данных»
Специальность: 09.03.03 Прикладная информатика
"""

import os
from datetime import date, datetime, time as dtime

import pandas as pd
import psycopg2
import psycopg2.pool
import streamlit as st
import re

# ══════════════════════════════════════════════════════════════════════
#  КОНФИГУРАЦИЯ ПРИЛОЖЕНИЯ
# ══════════════════════════════════════════════════════════════════════

st.set_page_config(
    page_title="Аэропорт — БД",
    page_icon="✈️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    /* Убираем лишние отступы сверху */
    .block-container { padding-top: 1.5rem; }

    /* Значок роли */
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

    /* Таблицы — чуть скруглённые углы */
    div[data-testid="stDataFrame"] { border-radius: 8px; overflow: hidden; }

    /* Кнопки запросов */
    .stButton > button[kind="primary"] { border-radius: 6px; font-weight: 600; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ── Учётные данные пользователей ──────────────────────────────────────
USERS: dict = {
    "Администратор": {
        "db_user":  "admin_user",
        "password": "admin_pass_2024",
        "badge":    "badge-admin",
        "icon":     "🔴",
    },
    "Диспетчер": {
        "db_user":  "dispatcher_user",
        "password": "dispatcher_pass_2024",
        "badge":    "badge-dispatcher",
        "icon":     "🔵",
    },
    "Кассир": {
        "db_user":  "cashier_user",
        "password": "cashier_pass_2024",
        "badge":    "badge-cashier",
        "icon":     "🟢",
    },
}

# ── Параметры подключения к PostgreSQL ───────────────────────────────
DB_CFG: dict = {
    "host":     os.getenv("DB_HOST",     "localhost"),
    "port":     int(os.getenv("DB_PORT", "5432")),
    "database": os.getenv("POSTGRES_DB", "airport_db"),
}

# ── Русские названия таблиц ───────────────────────────────────────────
TABLE_LABELS: dict = {
    "airline":          "✈️ Авиакомпании",
    "aircraft":         "🛩️ Самолёты",
    "flight":           "🛫 Рейсы",
    "passenger":        "👤 Пассажиры",
    "ticket":           "🎫 Билеты",
    "employee":         "👨‍✈️ Сотрудники",
    "crew_assignment":  "📋 Назначения экипажа",
}

ROLE_ALLOWED_TABLES = {
    "Администратор": list(TABLE_LABELS.keys()),
    "Диспетчер":     ["airline", "aircraft", "flight", "employee", "crew_assignment"],
    "Кассир":        ["flight", "passenger", "ticket"],
}
# ── Список запросов ───────────────────────────────────────────────────
QUERY_LIST = [
    "1.  Список пассажиров конкретного рейса",
    "2.  Расписание рейсов на дату",
    "3.  Рейсы конкретной авиакомпании",
    "4.  Свободные места на рейсе",
    "5.  Экипаж конкретного рейса",
    "6.  Задержанные и отменённые рейсы за период",
    "7.  История использования самолёта",
    "8.  Средняя цена билета по классам",
    "9.  Топ-5 пассажиров по расходам",
    "10. Рейсы со свободными местами",
    "11. Количество рейсов по статусам",
    "12. Пассажиры без отчества",
    "13. Сотрудники без назначений на рейсы",
]

ROLE_ALLOWED_QUERIES = {
    "Администратор": list(range(1, 14)),   # все 13
    "Диспетчер":     list(range(1, 14)),   # все 13
    "Кассир":        [1, 2, 4, 6, 7, 8, 9, 10, 11, 12],  # без 3, 5, 13
}

# ── Стандартный список ролей в экипаже ────────────────────────────────
CREW_ROLES = [
    "командир воздушного судна",
    "второй пилот",
    "штурман",          # правдоподобная доп. роль
    "бортинженер",      # правдоподобная доп. роль
    "старший бортпроводник",
    "бортпроводник",
]

# ── Список стран регистрации авиакомпаний ─────────────────────────────
OTHER_COUNTRY = "Другая…"
COUNTRIES = [
    "Россия", "США", "Великобритания", "Германия", "Франция",
    "Турция", "ОАЭ", "Китай", "Казахстан", OTHER_COUNTRY,
]


# ══════════════════════════════════════════════════════════════════════
#  ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ БД
# ══════════════════════════════════════════════════════════════════════

@st.cache_resource(show_spinner=False)
def _get_pool(user: str, password: str) -> psycopg2.pool.ThreadedConnectionPool:
    """Пул соединений на каждого пользователя БД.

    `st.cache_resource` хранит пул между перезапусками скрипта, поэтому новое
    TCP-соединение не открывается на каждый запрос. Пул потокобезопасный.
    """
    return psycopg2.pool.ThreadedConnectionPool(
        minconn=1, maxconn=5, **DB_CFG, user=user, password=password
    )


def _borrow_conn():
    """Взять соединение из пула текущего пользователя."""
    c = st.session_state["creds"]
    return _get_pool(c["user"], c["password"])


def query_df(sql: str, params=None) -> pd.DataFrame:
    """Выполнить SELECT и вернуть DataFrame.

    При ошибке выводит её через st.error и возвращает пустой DataFrame с
    пометкой `attrs["query_error"]`, чтобы show_result не дублировал сообщение.
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
        st.error(f"Ошибка выполнения запроса: {exc}")
        df = pd.DataFrame()
        df.attrs["query_error"] = True
        return df
    finally:
        pool.putconn(conn, close=bool(conn.closed))


def run_cmd(sql: str, params=None, return_rowcount: bool = False) -> tuple:
    """Выполнить INSERT / UPDATE / DELETE.

    Возвращает (успех: bool, ошибка: str|None) либо, при return_rowcount=True,
    (успех: bool, ошибка: str|None, затронуто_строк: int).
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
    """Защита от SQL-инъекции при подстановке имени таблицы в запрос.

    Имя таблицы нельзя передать параметром (%s), поэтому проверяем его по
    белому списку известных таблиц перед интерполяцией в f-строку.
    """
    if tbl not in TABLE_LABELS:
        raise ValueError(f"Недопустимое имя таблицы: {tbl!r}")
    return tbl


# ── Проверка ролей ────────────────────────────────────────────────────
def role() -> str:
    return st.session_state.get("role", "")

def is_admin() -> bool:
    return role() == "Администратор"

def is_dispatcher() -> bool:
    return role() in ("Администратор", "Диспетчер")

def is_cashier() -> bool:
    return role() in ("Администратор", "Кассир")


# ── Вывод результата запроса ──────────────────────────────────────────
def show_result(df: pd.DataFrame) -> None:
    if df.attrs.get("query_error"):
        return  # ошибку уже показал query_df — не дублируем «Данные не найдены»
    if df.empty:
        st.info("Данные не найдены.")
    else:
        st.caption(f"Найдено строк: **{len(df)}**")
        st.dataframe(df, width="stretch")


# ══════════════════════════════════════════════════════════════════════
#  СТРАНИЦА: АВТОРИЗАЦИЯ
# ══════════════════════════════════════════════════════════════════════

def page_login() -> None:
    _, col, _ = st.columns([1, 1.2, 1])
    with col:
        st.markdown("## ✈️ АэропортБД")
        st.caption("Учебная система управления базой данных аэропорта")
        st.divider()
        sel_role = st.selectbox("Роль пользователя", list(USERS.keys()))
        pwd = st.text_input("Пароль", type="password", placeholder="Введите пароль...")

        if st.button("Войти", type="primary", width="stretch"):
            if pwd == USERS[sel_role]["password"]:
                st.session_state["role"] = sel_role
                st.session_state["creds"] = {
                    "user":     USERS[sel_role]["db_user"],
                    "password": USERS[sel_role]["password"],
                }
                st.rerun()
            else:
                st.error("❌ Неверный пароль. Попробуйте ещё раз.")

        with st.expander("📌 Тестовые пароли для демонстрации"):
            for r, u in USERS.items():
                st.caption(f"**{r}:** `{u['password']}`")


# ══════════════════════════════════════════════════════════════════════
#  БОКОВОЕ МЕНЮ
# ══════════════════════════════════════════════════════════════════════

def sidebar_nav() -> str:
    r = role()
    u = USERS[r]
    st.sidebar.markdown("## ✈️ АэропортБД")
    st.sidebar.markdown(
        f'<span class="role-badge {u["badge"]}">{u["icon"]} {r}</span>',
        unsafe_allow_html=True,
    )
    st.sidebar.caption(f"Пользователь БД: `{u['db_user']}`")
    st.sidebar.divider()

    nav_items = [
        "🏠 Главная",
        "📋 Таблицы",
        "🔍 Запросы",
        "📊 Отчёты",
        "✏️ Управление",
    ]
    if is_admin():
        nav_items.append("🔐 Безопасность")

    selected = st.sidebar.radio("Навигация", nav_items, label_visibility="collapsed")
    st.sidebar.divider()
    if st.sidebar.button("🚪 Выйти", width='stretch'):
        for k in ("role", "creds"):
            st.session_state.pop(k, None)
        st.rerun()
    return selected


# ══════════════════════════════════════════════════════════════════════
#  СТРАНИЦА: ГЛАВНАЯ
# ══════════════════════════════════════════════════════════════════════

def page_home() -> None:
    st.title("🏠 Главная")
    st.markdown(f"Добро пожаловать! Вы вошли как **{role()}**.")
    st.divider()

    # Метрики только по таблицам, доступным текущей роли
    ROLE_TABLES = {
        "Администратор": [
            ("✈️", "Авиакомпаний", "airline"),
            ("🛩️", "Самолётов",   "aircraft"),
            ("🛫", "Рейсов",       "flight"),
            ("👤", "Пассажиров",   "passenger"),
            ("🎫", "Билетов",      "ticket"),
            ("👨‍✈️", "Сотрудников", "employee"),
            ("📋", "Назначений",   "crew_assignment"),
        ],
        "Диспетчер": [
            ("✈️", "Авиакомпаний", "airline"),
            ("🛩️", "Самолётов",   "aircraft"),
            ("🛫", "Рейсов",       "flight"),
            ("👨‍✈️", "Сотрудников", "employee"),
            ("📋", "Назначений",   "crew_assignment"),
        ],
        "Кассир": [
            ("🛫", "Рейсов",     "flight"),
            ("👤", "Пассажиров", "passenger"),
            ("🎫", "Билетов",    "ticket"),
        ],
    }

    table_defs = ROLE_TABLES.get(role(), [])
    cols = st.columns(len(table_defs))
    for col, (icon, lbl, tbl) in zip(cols, table_defs):
        res = query_df(f"SELECT COUNT(*) AS cnt FROM {_safe_table(tbl)};")
        cnt = int(res.iloc[0]["cnt"]) if not res.empty else "—"
        col.metric(f"{icon} {lbl}", cnt)

    st.divider()
    st.subheader("📌 Ваши права доступа")
    rights = {
        "Администратор": [
            "✅ Полный доступ ко всем таблицам (SELECT, INSERT, UPDATE, DELETE)",
            "✅ Создание и управление пользователями БД (CREATEDB, CREATEROLE)",
            "✅ Резервное копирование и восстановление БД",
        ],
        "Диспетчер": [
            "✅ Просмотр всех таблиц (SELECT)",
            "✅ Добавление и изменение рейсов (INSERT, UPDATE на flight)",
            "✅ Управление назначениями экипажа (INSERT, UPDATE, DELETE на crew_assignment)",
            "✅ Изменение данных самолётов (UPDATE на aircraft)",
            "❌ Запрещено изменять данные пассажиров, билеты и авиакомпании",
        ],
        "Кассир": [
            "✅ Просмотр рейсов, пассажиров, билетов (SELECT)",
            "✅ Добавление новых пассажиров (INSERT на passenger)",
            "✅ Продажа билетов (INSERT на ticket)",
            "✅ Отмена (удаление) билетов (DELETE на ticket)",
            "✅ Изменение телефона и номера паспорта пассажира (UPDATE phone, passport_no)",
            "❌ Запрещено изменять рейсы, самолёты, сотрудников и авиакомпании",
        ],
    }
    for item in rights.get(role(), []):
        st.markdown(item)

    st.divider()
    st.subheader("📐 Описание базы данных")
    st.markdown("""
    База данных **«Аэропорт»** содержит **7 сущностей**, связанных между собой внешними ключами:

    | Таблица | Описание |
    |---|---|
    | `airline` | Авиакомпании (код IATA, название, страна) |
    | `aircraft` | Самолёты (бортовой номер, модель, вместимость, год выпуска) |
    | `flight` | Рейсы (номер, маршрут, время вылета/прилёта, статус) |
    | `passenger` | Пассажиры (ФИО, паспорт, дата рождения, телефон) |
    | `ticket` | Билеты (номер, место, класс, цена, дата покупки) |
    | `employee` | Сотрудники экипажа (ФИО, должность, табельный номер) |
    | `crew_assignment` | Назначения экипажа на рейсы (связующая таблица M:M) |

    СУБД: **PostgreSQL 16**. Развёртывание: **Docker Compose**.
    """)


# ══════════════════════════════════════════════════════════════════════
#  СТРАНИЦА: ПРОСМОТР ТАБЛИЦ
# ══════════════════════════════════════════════════════════════════════

def page_tables() -> None:
    st.title("📋 Просмотр таблиц")
    allowed = ROLE_ALLOWED_TABLES.get(role(), [])
    c1, c2, c3 = st.columns([2, 1, 1])
    tbl    = c1.selectbox("Таблица", allowed,
                          format_func=lambda x: TABLE_LABELS[x])
    limit  = c2.selectbox("Строк", [10, 25, 50, 100], index=1)
    offset = c3.number_input("Смещение", min_value=0, step=10, value=0)

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
        f"Таблица **{TABLE_LABELS[tbl]}** · Всего строк: **{total}** · "
        f"Показано: {shown}"
    )

    if not data.empty:
        st.dataframe(data, width="stretch", height=420)
    else:
        st.info("Таблица пуста или данные недоступны для вашей роли.")


# ══════════════════════════════════════════════════════════════════════
#  СТРАНИЦА: ЗАПРОСЫ
# ══════════════════════════════════════════════════════════════════════

def page_queries() -> None:
    st.title("🔍 Запросы к базе данных")
    st.caption("13 запросов с сортировкой, группировкой, вычислениями и соединением таблиц.")
    allowed_indices = ROLE_ALLOWED_QUERIES.get(role(), list(range(1, 14)))
    filtered_queries = [q for q in QUERY_LIST
                        if int(q.split(".")[0].strip()) in allowed_indices]

    sel = st.selectbox("Выберите запрос", filtered_queries)
    st.divider()
    idx = int(sel.split(".")[0].strip())
    _render_query(idx)


def _render_query(idx: int) -> None:  # noqa: C901

    # ──── Запрос 1 ─────────────────────────────────────────────────────
    if idx == 1:
        st.subheader("1. Список пассажиров конкретного рейса")
        st.caption(
            "Соединение трёх таблиц: `passenger → ticket → flight`. "
            "`COALESCE` заменяет `NULL` на «—». Сортировка по фамилии."
        )
        flight_no = st.text_input("Номер рейса", value="SU1234",
                                  placeholder="Например, SU1234")
        if st.button("▶ Выполнить", key="q1"):
            show_result(query_df("""
                SELECT p.last_name                      AS фамилия,
                       p.first_name                     AS имя,
                       COALESCE(p.middle_name, '—')     AS отчество,
                       t.seat_no                        AS место,
                       t.service_class                  AS класс,
                       t.price                          AS цена_руб
                FROM passenger p
                JOIN ticket t ON t.passenger_id = p.passenger_id
                JOIN flight  f ON f.flight_id   = t.flight_id
                WHERE f.flight_number = %s
                ORDER BY p.last_name, p.first_name;
            """, (flight_no,)))

    # ──── Запрос 2 ─────────────────────────────────────────────────────
    elif idx == 2:
        st.subheader("2. Расписание рейсов на конкретную дату")
        st.caption(
            "Фильтрация по дате через `DATE(depart_at)`. "
            "Результат отсортирован по времени вылета."
        )
        d = st.date_input("Дата", value=date(2026, 7, 3))
        if st.button("▶ Выполнить", key="q2"):
            show_result(query_df("""
                SELECT f.flight_number AS номер_рейса,
                       f.city_from    AS откуда,
                       f.city_to      AS куда,
                       f.depart_at    AS вылет,
                       f.arrive_at    AS прилёт,
                       f.status       AS статус
                FROM flight f
                WHERE DATE(f.depart_at) = %s
                ORDER BY f.depart_at;
            """, (d,)))

    # ──── Запрос 3 ─────────────────────────────────────────────────────
    elif idx == 3:
        st.subheader("3. Рейсы конкретной авиакомпании")
        st.caption(
            "Соединение трёх таблиц: `flight → aircraft → airline`. "
            "Фильтр по коду IATA."
        )
        airlines = query_df("SELECT iata_code, name FROM airline ORDER BY name;")
        if airlines.empty:
            st.warning("Нет данных об авиакомпаниях.")
            return
        al_opts = {
            f"{row['name']} ({row['iata_code']})": row["iata_code"]
            for _, row in airlines.iterrows()
        }
        al_label = st.selectbox("Авиакомпания", list(al_opts.keys()))
        if st.button("▶ Выполнить", key="q3"):
            show_result(query_df("""
                SELECT f.flight_number AS номер_рейса,
                       f.city_from    AS откуда,
                       f.city_to      AS куда,
                       f.depart_at    AS вылет,
                       f.status       AS статус,
                       ac.model       AS модель_самолёта
                FROM flight   f
                JOIN aircraft ac ON ac.tail_number = f.tail_number
                JOIN airline  al ON al.iata_code   = ac.iata_code
                WHERE al.iata_code = %s
                ORDER BY f.depart_at;
            """, (al_opts[al_label],)))

    # ──── Запрос 4 ─────────────────────────────────────────────────────
    elif idx == 4:
        st.subheader("4. Количество свободных мест на конкретном рейсе")
        st.caption(
            "Агрегация `COUNT` с `LEFT JOIN`. "
            "Вместимость самолёта минус количество проданных билетов."
        )
        flights = query_df(
            "SELECT flight_id, flight_number, city_from, city_to FROM flight ORDER BY depart_at;"
        )
        if flights.empty:
            st.warning("Нет рейсов в базе данных.")
            return
        f_opts = {
            f"[{r['flight_id']}] {r['flight_number']}  {r['city_from']} → {r['city_to']}": r["flight_id"]
            for _, r in flights.iterrows()
        }
        f_label = st.selectbox("Рейс", list(f_opts.keys()), key="q4_sel")
        if st.button("▶ Выполнить", key="q4"):
            res = query_df("""
                SELECT f.flight_number                      AS номер_рейса,
                       f.city_from || ' → ' || f.city_to   AS направление,
                       ac.capacity                         AS вместимость,
                       COUNT(t.ticket_no)                  AS продано,
                       ac.capacity - COUNT(t.ticket_no)    AS свободных_мест
                FROM flight f
                JOIN aircraft ac   ON ac.tail_number = f.tail_number
                LEFT JOIN ticket t ON t.flight_id    = f.flight_id
                WHERE f.flight_id = %s
                GROUP BY f.flight_number, f.city_from, f.city_to, ac.capacity;
            """, (f_opts[f_label],))
            if not res.empty:
                row = res.iloc[0]
                m1, m2, m3 = st.columns(3)
                m1.metric("🛩️ Вместимость",    int(row["вместимость"]))
                m2.metric("🎫 Продано",         int(row["продано"]))
                m3.metric("💺 Свободно",        int(row["свободных_мест"]))
                st.dataframe(res, width="stretch")

    # ──── Запрос 5 ─────────────────────────────────────────────────────
    elif idx == 5:
        st.subheader("5. Экипаж конкретного рейса")
        st.caption(
            "Соединение трёх таблиц: `employee → crew_assignment → flight`. "
            "Сортировка по должности и фамилии."
        )
        flights = query_df(
            "SELECT flight_id, flight_number, city_from, city_to FROM flight ORDER BY depart_at;"
        )
        if flights.empty:
            st.warning("Нет рейсов.")
            return
        f_opts = {
            f"[{r['flight_id']}] {r['flight_number']}  {r['city_from']} → {r['city_to']}": r["flight_id"]
            for _, r in flights.iterrows()
        }
        f_label = st.selectbox("Рейс", list(f_opts.keys()), key="q5_sel")
        if st.button("▶ Выполнить", key="q5"):
            show_result(query_df("""
                SELECT e.last_name                    AS фамилия,
                       e.first_name                   AS имя,
                       COALESCE(e.middle_name, '—')   AS отчество,
                       e.position                     AS должность,
                       ca.crew_role                   AS роль_в_экипаже
                FROM employee        e
                JOIN crew_assignment ca ON ca.employee_id = e.employee_id
                WHERE ca.flight_id = %s
                ORDER BY e.position, e.last_name;
            """, (f_opts[f_label],)))

    # ──── Запрос 6 ─────────────────────────────────────────────────────
    elif idx == 6:
        st.subheader("6. Задержанные и отменённые рейсы за период")
        st.caption(
            "Фильтр `IN ('задержан', 'отменён')` и `BETWEEN` по диапазону дат."
        )
        c1, c2 = st.columns(2)
        d1 = c1.date_input("С",  value=date(2026, 5, 1),   key="q6d1")
        d2 = c2.date_input("По", value=date.today(), key="q6d2")
        if st.button("▶ Выполнить", key="q6"):
            show_result(query_df("""
                SELECT f.flight_number AS номер_рейса,
                       f.city_from    AS откуда,
                       f.city_to      AS куда,
                       f.depart_at    AS вылет,
                       f.status       AS статус
                FROM flight f
                WHERE f.status IN ('задержан', 'отменён')
                  AND DATE(f.depart_at) BETWEEN %s AND %s
                ORDER BY f.depart_at;
            """, (d1, d2)))

    # ──── Запрос 7 ─────────────────────────────────────────────────────
    elif idx == 7:
        st.subheader("7. История использования самолёта за период")
        st.caption(
            "JOIN `flight → aircraft`. Фильтр по бортовому номеру и диапазону дат."
        )
        aircrafts = query_df("SELECT tail_number, model FROM aircraft ORDER BY tail_number;")
        if aircrafts.empty:
            st.warning("Нет самолётов.")
            return
        ac_opts = {
            f"{r['tail_number']} ({r['model']})": r["tail_number"]
            for _, r in aircrafts.iterrows()
        }
        ac_label = st.selectbox("Самолёт", list(ac_opts.keys()))
        c1, c2 = st.columns(2)
        d1 = c1.date_input("С",  value=date(2026, 1, 1),   key="q7d1")
        d2 = c2.date_input("По", value=date.today(), key="q7d2")
        if st.button("▶ Выполнить", key="q7"):
            show_result(query_df("""
                SELECT f.flight_number AS номер_рейса,
                       f.city_from    AS откуда,
                       f.city_to      AS куда,
                       f.depart_at    AS вылет,
                       f.arrive_at    AS прилёт,
                       f.status       AS статус
                FROM flight   f
                JOIN aircraft ac ON ac.tail_number = f.tail_number
                WHERE ac.tail_number = %s
                  AND DATE(f.depart_at) BETWEEN %s AND %s
                ORDER BY f.depart_at;
            """, (ac_opts[ac_label], d1, d2)))

    # ──── Запрос 8 ─────────────────────────────────────────────────────
    elif idx == 8:
        st.subheader("8. Средняя цена билета по классам обслуживания")
        st.caption(
            "Агрегатные функции `AVG`, `MIN`, `MAX` с `GROUP BY service_class`."
        )
        if st.button("▶ Выполнить", key="q8"):
            res = query_df("""
                SELECT service_class             AS класс,
                       COUNT(*)                  AS билетов,
                       ROUND(AVG(price), 2)      AS средняя_цена,
                       MIN(price)                AS минимальная,
                       MAX(price)                AS максимальная
                FROM ticket
                GROUP BY service_class
                ORDER BY средняя_цена DESC;
            """)
            show_result(res)
            if not res.empty:
                st.markdown("**Средняя цена по классам (руб.)**")
                st.bar_chart(res.set_index("класс")["средняя_цена"].astype(float),
                             height=220, color="#4f8ef7")

    # ──── Запрос 9 ─────────────────────────────────────────────────────
    elif idx == 9:
        st.subheader("9. Топ-5 пассажиров по суммарным расходам на билеты")
        st.caption(
            "`GROUP BY` пассажиру, `SUM(price)`, сортировка `DESC`, `LIMIT 5`."
        )
        if st.button("▶ Выполнить", key="q9"):
            show_result(query_df("""
                SELECT p.last_name || ' ' || p.first_name AS пассажир,
                       COUNT(t.ticket_no)                 AS куплено_билетов,
                       SUM(t.price)                       AS сумма_расходов_руб
                FROM passenger p
                JOIN ticket t ON t.passenger_id = p.passenger_id
                GROUP BY p.passenger_id, p.last_name, p.first_name
                ORDER BY сумма_расходов_руб DESC
                LIMIT 5;
            """))

    # ──── Запрос 10 ────────────────────────────────────────────────────
    elif idx == 10:
        st.subheader("10. Рейсы, на которых остались свободные места")
        st.caption(
            "Фильтрация через `HAVING COUNT(ticket_no) < capacity`. "
            "Не включает отменённые рейсы."
        )
        if st.button("▶ Выполнить", key="q10"):
            show_result(query_df("""
                SELECT f.flight_id                            AS id_рейса,
                       f.flight_number                       AS номер_рейса,
                       f.city_from || ' → ' || f.city_to     AS направление,
                       f.depart_at                           AS вылет,
                       ac.capacity                           AS вместимость,
                       COUNT(t.ticket_no)                    AS продано,
                       ac.capacity - COUNT(t.ticket_no)      AS свободно
                FROM flight   f
                JOIN aircraft ac   ON ac.tail_number = f.tail_number
                LEFT JOIN ticket t ON t.flight_id    = f.flight_id
                WHERE f.status NOT IN ('отменён')
                GROUP BY f.flight_id, f.flight_number, f.city_from,
                         f.city_to, f.depart_at, ac.capacity
                HAVING COUNT(t.ticket_no) < ac.capacity
                ORDER BY f.depart_at;
            """))

    # ──── Запрос 11 ────────────────────────────────────────────────────
    elif idx == 11:
        st.subheader("11. Количество рейсов по статусам")
        st.caption("`GROUP BY status` + `COUNT(*)`. Простой агрегирующий запрос.")
        if st.button("▶ Выполнить", key="q11"):
            res = query_df("""
                SELECT status AS статус, COUNT(*) AS количество
                FROM flight
                GROUP BY status
                ORDER BY количество DESC;
            """)
            show_result(res)
            if not res.empty:
                st.bar_chart(res.set_index("статус")["количество"], height=220)

    # ──── Запрос 12 ────────────────────────────────────────────────────
    elif idx == 12:
        st.subheader("12. Пассажиры без отчества (иностранные граждане)")
        st.caption(
            "Фильтр `WHERE middle_name IS NULL`. "
            "В модели отчество допускает `NULL` для иностранцев."
        )
        if st.button("▶ Выполнить", key="q12"):
            show_result(query_df("""
                SELECT passenger_id AS id,
                       last_name    AS фамилия,
                       first_name   AS имя,
                       passport_no  AS паспорт,
                       phone        AS телефон
                FROM passenger
                WHERE middle_name IS NULL
                ORDER BY last_name;
            """))

    # ──── Запрос 13 ────────────────────────────────────────────────────
    elif idx == 13:
        st.subheader("13. Сотрудники без назначений на рейсы")
        st.caption(
            "Коррелированный подзапрос `NOT EXISTS`. "
            "Выявляет сотрудников, не задействованных ни на одном рейсе."
        )
        if st.button("▶ Выполнить", key="q13"):
            show_result(query_df("""
                SELECT e.employee_id                        AS табельный_номер,
                       e.last_name || ' ' || e.first_name  AS фио,
                       e.position                          AS должность,
                       e.hire_date                         AS дата_приёма
                FROM employee e
                WHERE NOT EXISTS (
                    SELECT 1 FROM crew_assignment ca
                    WHERE ca.employee_id = e.employee_id
                )
                ORDER BY e.last_name;
            """))

# ══════════════════════════════════════════════════════════════════════
#  ОТЧЁТЫ — вспомогательные функции
# ══════════════════════════════════════════════════════════════════════

def _report_flights() -> None:
    st.subheader("Отчёт по загрузке рейсов")
    st.caption(
        "Для каждого рейса: вместимость, продажи, процент загрузки и суммарная выручка. "
        "Агрегатные функции `COUNT`, `SUM`, `ROUND`."
    )
    if st.button("Сформировать", key="rep1"):
        res = query_df("""
            SELECT f.flight_number                                     AS номер_рейса,
                   f.city_from || ' → ' || f.city_to                   AS направление,
                   f.depart_at::DATE                                   AS дата,
                   f.status                                            AS статус,
                   ac.capacity                                         AS вместимость,
                   COUNT(t.ticket_no)                                  AS продано,
                   ROUND(COUNT(t.ticket_no)::NUMERIC /
                         ac.capacity * 100, 1)                         AS загрузка_pct,
                   COALESCE(SUM(t.price), 0)                           AS выручка_руб
            FROM flight   f
            JOIN aircraft ac   ON ac.tail_number = f.tail_number
            LEFT JOIN ticket t ON t.flight_id    = f.flight_id
            GROUP BY f.flight_id, f.flight_number, f.city_from,
                     f.city_to, f.depart_at, f.status, ac.capacity
            ORDER BY загрузка_pct DESC;
        """)
        if not res.empty:
            st.dataframe(res, width="stretch")
            st.markdown("**Загрузка рейсов, %**")
            st.bar_chart(
                res.set_index("номер_рейса")["загрузка_pct"].astype(float),
                height=280, color="#22c55e",
            )


def _report_employees() -> None:
    st.subheader("Отчёт по сотрудникам")
    st.caption(
        "ФИО, должность, стаж (вычисляется через `AGE`) и количество рейсов за период. "
        "`LEFT JOIN` — чтобы отображать и сотрудников без назначений."
    )
    c1, c2 = st.columns(2)
    d1 = c1.date_input("С",  value=date(2026, 1, 1),   key="rep2d1")
    d2 = c2.date_input("По", value=date.today(), key="rep2d2")
    if st.button("Сформировать", key="rep2"):
        res = query_df("""
            SELECT e.employee_id                                          AS табельный_номер,
                   TRIM(e.last_name || ' ' || e.first_name || ' ' ||
                        COALESCE(e.middle_name, ''))                      AS фио,
                   e.position                                             AS должность,
                   EXTRACT(YEAR FROM AGE(CURRENT_DATE, e.hire_date))::INT AS стаж_лет,
                   COUNT(f.flight_id)                                     AS рейсов_в_периоде
            FROM employee e
            LEFT JOIN crew_assignment ca ON ca.employee_id = e.employee_id
            LEFT JOIN flight f           ON f.flight_id    = ca.flight_id
                                        AND DATE(f.depart_at) BETWEEN %s AND %s
            GROUP BY e.employee_id, e.last_name, e.first_name,
                     e.middle_name, e.position, e.hire_date
            ORDER BY рейсов_в_периоде DESC, e.last_name;
        """, (d1, d2))
        if not res.empty:
            st.dataframe(res, width="stretch")


def _report_airlines() -> None:
    st.subheader("Отчёт по авиакомпаниям")
    st.caption(
        "Для каждой авиакомпании: парк самолётов, количество выполненных рейсов "
        "и суммарная выручка. `COUNT DISTINCT` + фильтр `FILTER (WHERE ...)`. "
        "Четыре таблицы: `airline → aircraft → flight → ticket`."
    )
    if st.button("Сформировать", key="rep3"):
        res = query_df("""
            SELECT al.iata_code                                            AS код_iata,
                   al.name                                                 AS авиакомпания,
                   al.country                                              AS страна,
                   COUNT(DISTINCT ac.tail_number)                          AS самолётов,
                   COUNT(DISTINCT f.flight_id)
                       FILTER (WHERE f.status = 'выполнен')               AS рейсов_выполнено,
                   COALESCE(SUM(t.price), 0)                               AS выручка_руб
            FROM airline al
            LEFT JOIN aircraft ac ON ac.iata_code  = al.iata_code
            LEFT JOIN flight   f  ON f.tail_number = ac.tail_number
            LEFT JOIN ticket   t  ON t.flight_id   = f.flight_id
            GROUP BY al.iata_code, al.name, al.country
            ORDER BY выручка_руб DESC;
        """)
        if not res.empty:
            st.dataframe(res, width="stretch")
            st.markdown("**Выручка по авиакомпаниям (руб.)**")
            st.bar_chart(
                res.set_index("авиакомпания")["выручка_руб"].astype(float),
                height=280, color="#6366f1",
            )


def page_reports() -> None:
    st.title("📊 Отчёты")
    st.caption("Сводные отчёты с группировкой, агрегацией и визуализацией данных.")

    report_defs = [("📈 Загрузка рейсов", _report_flights)]
    if role() != "Кассир":
        report_defs += [
            ("👨‍✈️ По сотрудникам",  _report_employees),
            ("✈️ По авиакомпаниям", _report_airlines),
        ]

    tabs = st.tabs([label for label, _ in report_defs])
    for widget, (_, render_fn) in zip(tabs, report_defs):
        with widget:
            render_fn()


# ══════════════════════════════════════════════════════════════════════
#  СТРАНИЦА: УПРАВЛЕНИЕ ДАННЫМИ
# ══════════════════════════════════════════════════════════════════════

def page_manage() -> None:
    st.title("✏️ Управление данными")
    st.caption("Доступные операции определяются вашей ролью.")

    # Формируем список вкладок динамически по роли
    tab_defs: list = []
    if is_dispatcher():
        tab_defs += [
            ("🛫 Добавить рейс",      _tab_add_flight),
            ("✏️ Статус рейса",        _tab_update_flight_status),
            ("👥 Назначить экипаж",    _tab_assign_crew),
        ]
    if is_cashier():
        tab_defs += [
            ("👤 Добавить пассажира", _tab_add_passenger),
            ("🎫 Продать билет",      _tab_add_ticket),
            ("📝 Изменить пассажира", _tab_update_passenger),
        ]
    if is_admin():
        tab_defs += [
            ("✈️ Авиакомпания",       _tab_add_airline),
            ("🛩️ Самолёт",            _tab_add_aircraft),
            ("👨‍✈️ Добавить сотрудника", _tab_add_employee),
        ]

    if not tab_defs:
        st.info("Управление данными недоступно для вашей роли.")
        return

    tabs = st.tabs([label for label, _ in tab_defs])
    for widget, (_, render_fn) in zip(tabs, tab_defs):
        with widget:
            render_fn()


# ──────────────────────────────────────────────────────────────────────
#  Вкладки: ДИСПЕТЧЕР
# ──────────────────────────────────────────────────────────────────────

def _tab_add_flight() -> None:
    st.subheader("🛫 Добавить новый рейс")
    aircrafts = query_df("SELECT tail_number, model FROM aircraft ORDER BY tail_number;")
    if aircrafts.empty:
        st.warning("Нет доступных самолётов. Сначала добавьте самолёт.")
        return
    ac_opts = {
        f"{r['tail_number']} ({r['model']})": r["tail_number"]
        for _, r in aircrafts.iterrows()
    }
    with st.form("form_add_flight"):
        c1, c2    = st.columns(2)
        flight_no = c1.text_input("Номер рейса *", placeholder="SU1234")
        ac_label  = c2.selectbox("Самолёт *", list(ac_opts.keys()))
        city_from = c1.text_input("Город отправления *")
        city_to   = c2.text_input("Город назначения *")
        dep_date  = c1.date_input("Дата вылета *", value=date.today())
        dep_time  = c1.time_input("Время вылета *", value=dtime(8, 0))
        arr_date  = c2.date_input("Дата прилёта *", value=date.today())
        arr_time  = c2.time_input("Время прилёта *", value=dtime(11, 0))
        submitted = st.form_submit_button("➕ Добавить рейс", type="primary")
        if submitted:
            if not all([flight_no, city_from, city_to]):
                st.error("Заполните все поля, отмеченные *")
            else:
                depart_at = datetime.combine(dep_date, dep_time)
                arrive_at = datetime.combine(arr_date, arr_time)
                if arr_date < dep_date:
                    st.error("Дата прилёта не может быть раньше даты вылета.")
                elif arr_date == dep_date and arr_time <= dep_time:
                    st.error("При совпадении дат время прилёта должно быть позже времени вылета.")
                elif arrive_at <= depart_at:
                    st.error("Время прилёта должно быть позже времени вылета.")
                else:
                    ok, err = run_cmd("""
                        INSERT INTO flight
                            (flight_number, city_from, city_to,
                             depart_at, arrive_at, tail_number)
                        VALUES (%s, %s, %s, %s, %s, %s);
                    """, (flight_no, city_from, city_to,
                          depart_at, arrive_at, ac_opts[ac_label]))
                    if ok:
                        st.success(f"✅ Рейс **{flight_no}** успешно добавлен!")
                    else:
                        st.error(f"❌ Ошибка: {err}")


def _tab_update_flight_status() -> None:
    st.subheader("✏️ Изменить статус рейса")
    flights = query_df("""
        SELECT flight_id, flight_number, city_from, city_to, status
        FROM flight ORDER BY depart_at DESC;
    """)
    if flights.empty:
        st.info("Нет рейсов в базе данных.")
        return
    f_opts = {
        f"[{r['flight_id']}] {r['flight_number']}  {r['city_from']} → {r['city_to']}  ({r['status']})": r["flight_id"]
        for _, r in flights.iterrows()
    }
    with st.form("form_upd_status"):
        f_label  = st.selectbox("Рейс", list(f_opts.keys()))
        new_stat = st.selectbox(
            "Новый статус",
            ["по расписанию", "задержан", "отменён", "выполнен"],
        )
        if st.form_submit_button("💾 Обновить статус", type="primary"):
            ok, err = run_cmd(
                "UPDATE flight SET status = %s WHERE flight_id = %s;",
                (new_stat, f_opts[f_label]),
            )
            if ok:
                st.success(f"✅ Статус изменён на «{new_stat}»")
            else:
                st.error(f"❌ {err}")


def _tab_assign_crew() -> None:
    st.subheader("👥 Назначить сотрудника на рейс")
    flights   = query_df(
        "SELECT flight_id, flight_number, city_from, city_to FROM flight ORDER BY depart_at DESC;"
    )
    employees = query_df(
        "SELECT employee_id, last_name, first_name, position FROM employee ORDER BY last_name;"
    )
    if flights.empty or employees.empty:
        st.warning("Нет доступных рейсов или сотрудников.")
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
        f_label   = st.selectbox("Рейс",      list(f_opts.keys()))
        e_label   = st.selectbox("Сотрудник", list(e_opts.keys()))
        crew_role = st.selectbox("Роль в экипаже *", CREW_ROLES)
        if st.form_submit_button("➕ Назначить", type="primary"):
            if not crew_role:
                st.error("Укажите роль в экипаже.")
            else:
                ok, err, affected = run_cmd("""
                    INSERT INTO crew_assignment (flight_id, employee_id, crew_role)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (flight_id, employee_id) DO NOTHING;
                """, (f_opts[f_label], e_opts[e_label], crew_role), return_rowcount=True)
                if ok and affected:
                    st.success("✅ Сотрудник успешно назначен на рейс!")
                elif ok:
                    st.warning("⚠️ Этот сотрудник уже назначен на данный рейс.")
                else:
                    st.error(f"❌ {err}")

    st.divider()
    st.subheader("🗑️ Снять сотрудника с рейса")
    assignments = query_df("""
        SELECT ca.flight_id, f.flight_number,
               e.last_name, e.first_name, e.employee_id, ca.crew_role
        FROM crew_assignment ca
        JOIN flight   f ON f.flight_id   = ca.flight_id
        JOIN employee e ON e.employee_id = ca.employee_id
        ORDER BY f.flight_number, e.last_name;
    """)
    if assignments.empty:
        st.info("Назначений пока нет.")
        return
    a_opts = {
        f"Рейс {r['flight_number']} — {r['last_name']} {r['first_name']} ({r['crew_role']})": (r["flight_id"], r["employee_id"])
        for _, r in assignments.iterrows()
    }
    a_label = st.selectbox("Назначение для удаления", list(a_opts.keys()))
    if st.button("🗑️ Удалить назначение", type="secondary"):
        fid, eid = a_opts[a_label]
        ok, err = run_cmd(
            "DELETE FROM crew_assignment WHERE flight_id = %s AND employee_id = %s;",
            (fid, eid),
        )
        if ok:
            st.success("✅ Назначение удалено.")
            st.rerun()
        else:
            st.error(f"❌ {err}")


# ──────────────────────────────────────────────────────────────────────
#  Вкладки: КАССИР
# ──────────────────────────────────────────────────────────────────────

def _fmt_phone(key: str) -> None:
    """Автоформат: +7 (XXX) XXX-XX-XX"""
    raw = st.session_state[key]
    digits = re.sub(r"\D", "", raw)
    # Убираем ведущую 7 или 8
    if digits.startswith(("7", "8")):
        digits = digits[1:]
    digits = digits[:10]

    if len(digits) == 0:
        result = ""
    elif len(digits) <= 3:
        result = f"+7 ({digits}"
    elif len(digits) <= 6:
        result = f"+7 ({digits[:3]}) {digits[3:]}"
    elif len(digits) <= 8:
        result = f"+7 ({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    else:
        result = f"+7 ({digits[:3]}) {digits[3:6]}-{digits[6:8]}-{digits[8:]}"

    st.session_state[key] = result


def _fmt_passport(key: str) -> None:
    """Автоформат паспорта РФ: XX XX XXXXXX (10 цифр)"""
    raw = st.session_state[key]
    digits = re.sub(r"\D", "", raw)
    digits = digits[:10]

    if len(digits) <= 2:
        result = digits
    elif len(digits) <= 4:
        result = f"{digits[:2]} {digits[2:]}"
    else:
        result = f"{digits[:2]} {digits[2:4]} {digits[4:]}"

    st.session_state[key] = result


def _fmt_ticket_no(key: str) -> None:
    """Маска номера билета: только цифры, ровно 13 знаков (формат IATA).

    Недостающие знаки дополняются нулями слева прямо в поле (видно в UI),
    лишние цифры сверх 13 отбрасываются. Пустое поле остаётся пустым.
    """
    digits = re.sub(r"\D", "", st.session_state[key])[:13]
    st.session_state[key] = digits.zfill(13) if digits else ""


def _fmt_iata(key: str) -> None:
    """Маска кода IATA: 2 алфавитно-цифровых символа (буквы/цифры), верхний регистр.

    Коды вида S7, U6 допустимы, поэтому цифры не вырезаются.
    """
    st.session_state[key] = re.sub(r"[^A-Za-z0-9]", "", st.session_state[key]).upper()[:2]


def _tab_add_passenger() -> None:
    st.subheader("👤 Зарегистрировать нового пассажира")

    # Инициализируем ключи в session_state при первом рендере
    for key in ("pax_phone", "pax_passport"):
        if key not in st.session_state:
            st.session_state[key] = ""

    # Отложенная очистка полей после успешного добавления:
    # сбрасываем ДО инстанцирования виджетов, иначе Streamlit бросит исключение.
    if st.session_state.get("pax_clear"):
        st.session_state["pax_phone"] = ""
        st.session_state["pax_passport"] = ""
        st.session_state["pax_clear"] = False

    c1, c2 = st.columns(2)
    last_name   = c1.text_input("Фамилия *")
    first_name  = c2.text_input("Имя *")
    middle_name = c1.text_input("Отчество (необязательно для иностранцев)")

    # Поле паспорта — с маской
    c1.text_input(
        "Номер паспорта *",
        key="pax_passport",
        placeholder="XX XX XXXXXX",
        on_change=_fmt_passport,
        args=("pax_passport",),
        help="Серия и номер паспорта РФ: XX XX XXXXXX",
    )

    birth_date = c1.date_input(
        "Дата рождения *",
        value=date(1990, 1, 1),
        min_value=date(1900, 1, 1),
        max_value=date.today(),
    )

    # Поле телефона — с маской
    c2.text_input(
        "Телефон *",
        key="pax_phone",
        placeholder="+7 (___) ___-__-__",
        on_change=_fmt_phone,
        args=("pax_phone",),
        help="Российский номер: +7 (XXX) XXX-XX-XX",
    )

    st.write("")  # небольшой отступ перед кнопкой
    if st.button("➕ Добавить пассажира", type="primary"):
        passport_no = st.session_state["pax_passport"]
        phone       = st.session_state["pax_phone"]

        # Валидация
        errors = []
        if not all([last_name, first_name]):
            errors.append("Заполните Фамилию и Имя.")
        if len(re.sub(r"\D", "", passport_no)) != 10:
            errors.append("Номер паспорта должен содержать 10 цифр (XX XX XXXXXX).")
        if len(re.sub(r"\D", "", phone)) != 11:
            errors.append("Телефон должен содержать 11 цифр (+7 и 10 цифр номера).")

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
                passport_no, birth_date, phone,
            ))
            if ok:
                # Сбрасываем маскированные поля на следующем прогоне (см. pax_clear выше)
                st.session_state["pax_clear"] = True
                st.success(f"✅ Пассажир **{last_name} {first_name}** добавлен!")
                st.rerun()
            else:
                st.error(f"❌ Ошибка: {err}")


def _tab_add_ticket() -> None:
    st.subheader("🎫 Продать билет")
    st.caption(
        "Продажа доступна на рейсы, которые ещё не вылетели; задержанные рейсы "
        "остаются доступными и после исходного времени вылета. Отменённые и "
        "выполненные рейсы в списке не показываются."
    )

    # Инициализация и отложенная очистка поля номера билета (см. pax_clear)
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
        WHERE f.status NOT IN ('отменён', 'выполнен')
          AND (f.depart_at > NOW() OR f.status = 'задержан')
        GROUP BY f.flight_id, f.flight_number, f.city_from,
                 f.city_to, f.depart_at, ac.capacity
        HAVING ac.capacity - COUNT(t.ticket_no) > 0
        ORDER BY f.depart_at;
    """)

    if passengers.empty:
        st.warning("Нет зарегистрированных пассажиров. Сначала добавьте пассажира.")
        return
    if avail_flights.empty:
        st.warning("Нет доступных рейсов со свободными местами.")
        return

    p_opts = {
        f"[{r['passenger_id']}] {r['last_name']} {r['first_name']}  (паспорт: {r['passport_no']})": r["passenger_id"]
        for _, r in passengers.iterrows()
    }
    f_opts = {
        f"[{r['flight_id']}] {r['flight_number']}  {r['city_from']} → {r['city_to']}  ({int(r['free_seats'])} св. мест)": r["flight_id"]
        for _, r in avail_flights.iterrows()
    }

    # Виджеты вне st.form — чтобы маска номера билета срабатывала «вживую»
    c1, c2     = st.columns(2)
    c1.text_input(
        "Номер билета *",
        key="tkt_no",
        max_chars=13,
        placeholder="0000000000000",
        on_change=_fmt_ticket_no,
        args=("tkt_no",),
        help="13 цифр (формат IATA). Недостающие знаки дополнятся нулями слева.",
    )
    p_label    = c2.selectbox("Пассажир *",  list(p_opts.keys()))
    f_label    = c1.selectbox("Рейс *",      list(f_opts.keys()))
    seat_no    = c2.text_input("Место *", placeholder="12A")
    svc_class  = c1.selectbox("Класс", ["эконом", "бизнес", "первый"])
    price      = c2.number_input(
        "Цена (руб.) *", min_value=1.0, step=500.0, value=5000.0, format="%.2f"
    )
    purch_date = c1.date_input("Дата покупки", value=date.today())

    if st.button("💳 Продать билет", type="primary"):
        ticket_no = st.session_state["tkt_no"]
        if not ticket_no or not seat_no:
            st.error("Заполните все обязательные поля (*)")
        elif len(ticket_no) != 13:
            st.error("Номер билета должен содержать ровно 13 цифр.")
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
                st.success(f"✅ Билет **{ticket_no}** успешно продан!")
                st.rerun()
            else:
                st.error(f"❌ Ошибка: {err}")

    # ── Отмена (удаление) билета ──────────────────────────────────────
    st.divider()
    st.subheader("🗑️ Отменить билет")
    sold = query_df("""
        SELECT t.ticket_no, t.seat_no, t.price,
               p.last_name, p.first_name, f.flight_number
        FROM ticket t
        JOIN passenger p ON p.passenger_id = t.passenger_id
        JOIN flight    f ON f.flight_id    = t.flight_id
        ORDER BY t.ticket_no;
    """)
    if sold.empty:
        st.info("Проданных билетов пока нет.")
        return
    t_opts = {
        f"№ {r['ticket_no']} · рейс {r['flight_number']} · место {r['seat_no']} · "
        f"{r['last_name']} {r['first_name']} ({r['price']} руб.)": r["ticket_no"]
        for _, r in sold.iterrows()
    }
    t_label = st.selectbox("Билет для отмены", list(t_opts.keys()))
    if st.button("🗑️ Отменить билет", type="secondary"):
        ok, err = run_cmd(
            "DELETE FROM ticket WHERE ticket_no = %s;",
            (t_opts[t_label],),
        )
        if ok:
            st.success("✅ Билет отменён.")
            st.rerun()
        else:
            st.error(f"❌ {err}")


def _tab_update_passenger() -> None:
    st.subheader("📝 Изменить данные пассажира")
    st.caption("Кассир может изменить только телефон и номер паспорта.")

    passengers = query_df("""
        SELECT passenger_id, last_name, first_name, passport_no, phone
        FROM passenger ORDER BY last_name;
    """)
    if passengers.empty:
        st.info("Нет зарегистрированных пассажиров.")
        return

    p_dict = {
        f"[{r['passenger_id']}] {r['last_name']} {r['first_name']}  (паспорт: {r['passport_no']})": r
        for _, r in passengers.iterrows()
    }
    p_label = st.selectbox("Выберите пассажира", list(p_dict.keys()))
    pdata   = p_dict[p_label]

    with st.form("form_upd_passenger"):
        new_phone    = st.text_input("Телефон",        value=str(pdata["phone"]))
        new_passport = st.text_input("Номер паспорта", value=str(pdata["passport_no"]))
        if st.form_submit_button("💾 Сохранить изменения", type="primary"):
            # Та же валидация, что и при добавлении пассажира
            errors = []
            if len(re.sub(r"\D", "", new_passport)) != 10:
                errors.append("Номер паспорта должен содержать 10 цифр (XX XX XXXXXX).")
            if len(re.sub(r"\D", "", new_phone)) != 11:
                errors.append("Телефон должен содержать 11 цифр (+7 и 10 цифр номера).")

            if errors:
                for e in errors:
                    st.error(e)
            else:
                ok, err = run_cmd("""
                    UPDATE passenger
                       SET phone = %s, passport_no = %s
                     WHERE passenger_id = %s;
                """, (new_phone, new_passport, int(pdata["passenger_id"])))
                if ok:
                    st.success("✅ Данные пассажира обновлены!")
                else:
                    st.error(f"❌ {err}")


# ──────────────────────────────────────────────────────────────────────
#  Вкладки: АДМИНИСТРАТОР
# ──────────────────────────────────────────────────────────────────────

def _tab_add_airline() -> None:
    st.subheader("✈️ Добавить авиакомпанию")

    if "air_iata" not in st.session_state:
        st.session_state["air_iata"] = ""

    # Виджеты вне st.form — чтобы маска кода IATA срабатывала «вживую»
    c1, c2  = st.columns(2)
    c1.text_input(
        "Код IATA (2 буквы) *",
        key="air_iata",
        placeholder="SU",
        on_change=_fmt_iata,
        args=("air_iata",),
        help="Ровно 2 латинские буквы. Лишние символы убираются автоматически.",
    )
    name    = c2.text_input("Название авиакомпании *")
    country = st.selectbox("Страна регистрации *", COUNTRIES)
    if country == OTHER_COUNTRY:
        country = st.text_input("Укажите страну *").strip()

    if st.button("➕ Добавить", type="primary"):
        iata = st.session_state["air_iata"]
        if not all([iata, name, country]):
            st.error("Заполните все обязательные поля (*)")
        elif len(iata) != 2:
            st.error("Код IATA должен состоять ровно из 2 букв.")
        else:
            ok, err = run_cmd(
                "INSERT INTO airline (iata_code, name, country) VALUES (%s, %s, %s);",
                (iata, name, country),
            )
            if ok:
                st.success(f"✅ Авиакомпания **{name}** ({iata}) добавлена!")
            else:
                st.error(f"❌ {err}")

    st.divider()
    st.caption("Текущий список авиакомпаний:")
    airlines = query_df("SELECT * FROM airline ORDER BY name;")
    st.dataframe(airlines, width="stretch")

    # ── Удаление авиакомпании ─────────────────────────────────────────
    st.subheader("🗑️ Удалить авиакомпанию")
    if airlines.empty:
        st.info("Авиакомпаний пока нет.")
        return
    al_opts = {
        f"{r['name']} ({r['iata_code']})": r["iata_code"]
        for _, r in airlines.iterrows()
    }
    al_label = st.selectbox("Авиакомпания для удаления", list(al_opts.keys()))
    if st.button("🗑️ Удалить авиакомпанию", type="secondary"):
        ok, err = run_cmd(
            "DELETE FROM airline WHERE iata_code = %s;",
            (al_opts[al_label],),
        )
        if ok:
            st.success("✅ Авиакомпания удалена.")
            st.rerun()
        else:
            st.error(
                "❌ Не удалось удалить: к авиакомпании привязаны самолёты. "
                "Сначала удалите или перепривяжите её самолёты.\n\n"
                f"Детали: {err}"
            )


def _tab_add_aircraft() -> None:
    st.subheader("🛩️ Добавить самолёт")
    airlines = query_df("SELECT iata_code, name FROM airline ORDER BY name;")
    if airlines.empty:
        st.warning("Нет авиакомпаний. Сначала добавьте авиакомпанию.")
        return
    al_opts = {
        f"{r['name']} ({r['iata_code']})": r["iata_code"]
        for _, r in airlines.iterrows()
    }
    with st.form("form_add_aircraft"):
        c1, c2   = st.columns(2)
        tail     = c1.text_input("Бортовой номер *", placeholder="RA-12345")
        model    = c2.text_input("Модель *",         placeholder="Boeing 737-800")
        capacity = c1.number_input(
            "Вместимость (мест) *", min_value=1, max_value=853, value=150, step=1
        )
        year     = c2.number_input(
            "Год выпуска *",
            min_value=1950, max_value=date.today().year,
            value=2015, step=1,
        )
        al_label = st.selectbox("Авиакомпания *", list(al_opts.keys()))
        if st.form_submit_button("➕ Добавить самолёт", type="primary"):
            if not all([tail, model]):
                st.error("Заполните все обязательные поля (*)")
            else:
                ok, err = run_cmd("""
                    INSERT INTO aircraft (tail_number, model, capacity, year_built, iata_code)
                    VALUES (%s, %s, %s, %s, %s);
                """, (tail, model, capacity, year, al_opts[al_label]))
                if ok:
                    st.success(f"✅ Самолёт **{tail}** ({model}) добавлен!")
                else:
                    st.error(f"❌ {err}")

    st.divider()
    st.caption("Текущий парк воздушных судов:")
    aircrafts = query_df("SELECT * FROM aircraft ORDER BY tail_number;")
    st.dataframe(aircrafts, width="stretch")

    # ── Удаление самолёта ─────────────────────────────────────────────
    st.subheader("🗑️ Удалить самолёт")
    if aircrafts.empty:
        st.info("Самолётов пока нет.")
        return
    ac_del_opts = {
        f"{r['tail_number']} ({r['model']})": r["tail_number"]
        for _, r in aircrafts.iterrows()
    }
    ac_del_label = st.selectbox("Самолёт для удаления", list(ac_del_opts.keys()))
    if st.button("🗑️ Удалить самолёт", type="secondary"):
        ok, err = run_cmd(
            "DELETE FROM aircraft WHERE tail_number = %s;",
            (ac_del_opts[ac_del_label],),
        )
        if ok:
            st.success("✅ Самолёт удалён.")
            st.rerun()
        else:
            st.error(
                "❌ Не удалось удалить: на самолёт назначены рейсы. "
                "Сначала удалите или перепривяжите связанные рейсы.\n\n"
                f"Детали: {err}"
            )


# Допустимые должности сотрудника (строго по chk_position в схеме)
EMPLOYEE_POSITIONS = ["пилот", "второй пилот", "бортпроводник"]


def _tab_add_employee() -> None:
    st.subheader("👨‍✈️ Зарегистрировать нового сотрудника")
    st.caption(
        "Регистрация члена экипажа. Табельный номер — 6-значное число (100000–999999), "
        "должность — из утверждённого списка."
    )
    with st.form("form_add_employee"):
        c1, c2      = st.columns(2)
        employee_id = c1.number_input(
            "Табельный номер *",
            min_value=100000, max_value=999999, value=100000, step=1,
            help="6-значный табельный номер (100000–999999).",
        )
        position    = c2.selectbox("Должность *", EMPLOYEE_POSITIONS)
        last_name   = c1.text_input("Фамилия *")
        first_name  = c2.text_input("Имя *")
        middle_name = c1.text_input("Отчество (необязательно)")
        hire_date   = c2.date_input(
            "Дата приёма *",
            value=date.today(),
            min_value=date(1950, 1, 1),
            max_value=date.today(),
        )
        if st.form_submit_button("➕ Добавить сотрудника", type="primary"):
            if not all([last_name, first_name]):
                st.error("Заполните Фамилию и Имя.")
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
                        f"✅ Сотрудник **{last_name} {first_name}** "
                        f"(таб. № {int(employee_id)}) добавлен!"
                    )
                else:
                    st.error(
                        "❌ Не удалось добавить сотрудника. "
                        "Возможно, табельный номер уже занят.\n\n"
                        f"Детали: {err}"
                    )

    st.divider()
    st.caption("Текущий список сотрудников:")
    st.dataframe(
        query_df("SELECT * FROM employee ORDER BY last_name;"),
        width="stretch",
    )


# ══════════════════════════════════════════════════════════════════════
#  СТРАНИЦА: БЕЗОПАСНОСТЬ (только Администратор)
# ══════════════════════════════════════════════════════════════════════

def page_security() -> None:
    st.title("🔐 Безопасность базы данных")
    if not is_admin():
        st.error("🚫 Доступ запрещён. Требуется роль Администратора.")
        return

    st.markdown(
        "Безопасность реализована средствами **PostgreSQL**: "
        "ролевая модель доступа на уровне БД. "
        "Принцип **минимальных привилегий** — каждый пользователь "
        "получает только права, необходимые для выполнения рабочих обязанностей."
    )
    st.divider()

    # Таблица прав
    perms = pd.DataFrame({
        "Пользователь":  ["admin_user",     "dispatcher_user",                       "cashier_user"],
        "Роль":          ["Администратор",   "Диспетчер",                             "Кассир"],
        "SELECT":        ["Все таблицы",     "Все таблицы",                           "flight, passenger, ticket, aircraft"],
        "INSERT":        ["Все таблицы",     "flight, crew_assignment",               "passenger, ticket"],
        "UPDATE":        ["Все таблицы",     "flight, aircraft, crew_assignment",     "passenger (phone, passport_no)"],
        "DELETE":        ["Все таблицы",     "crew_assignment",                       "ticket"],
        "Особые права":  ["CREATEDB CREATEROLE", "—",                                "—"],
    })
    st.dataframe(perms, width="stretch", hide_index=True)

    st.divider()
    with st.expander("📄 Просмотр кода: 02_users.sql"):
        st.code("""
-- ═══════════════════════════════════════════════════════
--  02_users.sql — Создание пользователей и назначение прав
-- ═══════════════════════════════════════════════════════

-- ── Администратор ──────────────────────────────────────
CREATE USER admin_user WITH PASSWORD 'admin_pass_2024' CREATEDB CREATEROLE;
GRANT ALL PRIVILEGES ON ALL TABLES    IN SCHEMA public TO admin_user;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO admin_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT ALL ON TABLES    TO admin_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT ALL ON SEQUENCES TO admin_user;

-- ── Диспетчер ──────────────────────────────────────────
CREATE USER dispatcher_user WITH PASSWORD 'dispatcher_pass_2024';
-- Читать может всё
GRANT SELECT ON ALL TABLES IN SCHEMA public TO dispatcher_user;
-- Управление рейсами и экипажем
GRANT INSERT, UPDATE, DELETE ON flight          TO dispatcher_user;
GRANT INSERT, UPDATE, DELETE ON crew_assignment TO dispatcher_user;
GRANT UPDATE                 ON aircraft        TO dispatcher_user;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO dispatcher_user;

-- ── Кассир ─────────────────────────────────────────────
CREATE USER cashier_user WITH PASSWORD 'cashier_pass_2024';
-- Чтение: рейсы, пассажиры, билеты + самолёты (для JOIN-ов в запросах и отчётах)
GRANT SELECT ON flight, passenger, ticket, aircraft TO cashier_user;
GRANT INSERT ON passenger, ticket         TO cashier_user;
-- Отмена билетов
GRANT DELETE ON ticket                    TO cashier_user;
-- Только телефон и паспорт пассажира
GRANT UPDATE (phone, passport_no) ON passenger TO cashier_user;
GRANT USAGE, SELECT ON SEQUENCE
    passenger_passenger_id_seq TO cashier_user;
        """, language="sql")

    st.divider()
    st.subheader("🔍 Проверка текущих привилегий")
    if st.button("Запросить привилегии из information_schema", key="check_privs"):
        result = query_df("""
            SELECT grantee        AS пользователь,
                   table_name     AS таблица,
                   privilege_type AS привилегия
            FROM information_schema.role_table_grants
            WHERE grantee IN ('admin_user', 'dispatcher_user', 'cashier_user')
            ORDER BY grantee, table_name, privilege_type;
        """)
        if not result.empty:
            st.dataframe(result, width="stretch")
        else:
            st.info(
                "Привилегии не найдены или у текущего сеанса недостаточно прав "
                "для просмотра `information_schema.role_table_grants`."
            )

    st.divider()
    st.subheader("🛡️ Дополнительные меры защиты")
    st.markdown("""
    - **Триггер** `trg_check_seat_availability` — при попытке продать билет сверх вместимости
      самолёта операция отклоняется с сообщением об ошибке.
    - **Ограничение `CHECK`** на статус рейса: допускаются только `'по расписанию'`,
      `'задержан'`, `'отменён'`, `'выполнен'`.
    - **`UNIQUE (flight_id, seat_no)`** в таблице `ticket` — одно место на рейсе
      нельзя продать дважды.
    - **`UNIQUE passport_no`** в таблице `passenger` — дублирующиеся паспорта недопустимы.
    - **Контейнеризация** через Docker — БД изолирована от основной ОС.
    """)


# ══════════════════════════════════════════════════════════════════════
#  ТОЧКА ВХОДА
# ══════════════════════════════════════════════════════════════════════

def main() -> None:
    # Если пользователь не вошёл — показываем форму входа
    if "role" not in st.session_state:
        page_login()
        return

    page = sidebar_nav()

    dispatch = {
        "🏠 Главная":      page_home,
        "📋 Таблицы":      page_tables,
        "🔍 Запросы":      page_queries,
        "📊 Отчёты":       page_reports,
        "✏️ Управление":   page_manage,
        "🔐 Безопасность": page_security,
    }
    dispatch.get(page, page_home)()


if __name__ == "__main__":
    main()