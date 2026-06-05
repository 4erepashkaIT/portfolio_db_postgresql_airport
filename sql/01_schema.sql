-- ------------------------------------------------------------
-- 1. АВИАКОМПАНИЯ
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS airline (
    iata_code   CHAR(2)         PRIMARY KEY,                         -- 'SU', 'S7', 'U6'
    name        VARCHAR(100)    NOT NULL,
    country     VARCHAR(60)     NOT NULL
);

-- ------------------------------------------------------------
-- 2. САМОЛЁТ
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS aircraft (
    tail_number VARCHAR(10)     PRIMARY KEY,                         -- 'VP-BWA'
    model       VARCHAR(50)     NOT NULL,
    capacity    SMALLINT        NOT NULL,
    year_built  SMALLINT        NOT NULL,
    iata_code   CHAR(2)         NOT NULL REFERENCES airline(iata_code)
                                    ON UPDATE CASCADE
                                    ON DELETE RESTRICT,

    CONSTRAINT chk_capacity    CHECK (capacity > 0),
    -- Статичная граница: CHECK не должен зависеть от неизменяемых функций
    -- (CURRENT_DATE) — это ломает dump/restore и молча «плывёт» каждый год.
    -- Верхняя граница 2100 — санитарный предел; «не из будущего» проверяет
    -- приложение (year max_value = date.today().year).
    CONSTRAINT chk_year_built  CHECK (year_built BETWEEN 1950 AND 2100)
);

-- ------------------------------------------------------------
-- 3. РЕЙС
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS flight (
    flight_id       SERIAL          PRIMARY KEY,
    flight_number   VARCHAR(10)     NOT NULL,                        -- 'SU1234'
    city_from       VARCHAR(80)     NOT NULL,
    city_to         VARCHAR(80)     NOT NULL,
    depart_at       TIMESTAMP       NOT NULL,
    arrive_at       TIMESTAMP       NOT NULL,
    status          VARCHAR(15)     NOT NULL DEFAULT 'по расписанию',
    tail_number     VARCHAR(10)     NOT NULL REFERENCES aircraft(tail_number)
                                        ON UPDATE CASCADE
                                        ON DELETE RESTRICT,

    CONSTRAINT chk_flight_time   CHECK (arrive_at > depart_at),
    CONSTRAINT chk_flight_status CHECK (status IN (
                                    'по расписанию', 'задержан',
                                    'отменён',        'выполнен'))
);

-- ------------------------------------------------------------
-- 4. ПАССАЖИР
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS passenger (
    passenger_id    SERIAL          PRIMARY KEY,
    last_name       VARCHAR(50)     NOT NULL,
    first_name      VARCHAR(50)     NOT NULL,
    middle_name     VARCHAR(50),                                     -- отчество необязательно
    passport_no     VARCHAR(20)     NOT NULL UNIQUE,
    birth_date      DATE            NOT NULL,
    phone           VARCHAR(20)     NOT NULL
);

-- ------------------------------------------------------------
-- 5. БИЛЕТ
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ticket (
    ticket_no       VARCHAR(20)     PRIMARY KEY,                     -- '2982401838278'
    seat_no         VARCHAR(5)      NOT NULL,                        -- '12A'
    service_class   VARCHAR(10)     NOT NULL,
    price           NUMERIC(10, 2)  NOT NULL,
    purchase_date   DATE            NOT NULL,
    passenger_id    INTEGER         NOT NULL REFERENCES passenger(passenger_id)
                                        ON UPDATE CASCADE
                                        ON DELETE RESTRICT,
    flight_id       INTEGER         NOT NULL REFERENCES flight(flight_id)
                                        ON UPDATE CASCADE
                                        ON DELETE RESTRICT,

    CONSTRAINT chk_ticket_price  CHECK (price > 0),
    CONSTRAINT chk_service_class CHECK (service_class IN ('эконом', 'бизнес', 'первый')),
    CONSTRAINT uq_seat_flight    UNIQUE (flight_id, seat_no)         -- одно место — один пассажир
);

-- ------------------------------------------------------------
-- 6. СОТРУДНИК
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS employee (
    employee_id     INTEGER         PRIMARY KEY,                     -- 6-значный табельный №
    last_name       VARCHAR(50)     NOT NULL,
    first_name      VARCHAR(50)     NOT NULL,
    middle_name     VARCHAR(50),
    position        VARCHAR(20)     NOT NULL,
    hire_date       DATE            NOT NULL,

    CONSTRAINT chk_employee_id  CHECK (employee_id BETWEEN 100000 AND 999999),
    CONSTRAINT chk_position     CHECK (position IN (
                                    'пилот', 'второй пилот', 'бортпроводник'))
);

-- ------------------------------------------------------------
-- 7. НАЗНАЧЕНИЕ НА РЕЙС (связующая таблица M:M)
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS crew_assignment (
    flight_id       INTEGER     NOT NULL REFERENCES flight(flight_id)
                                    ON UPDATE CASCADE
                                    ON DELETE CASCADE,
    employee_id     INTEGER     NOT NULL REFERENCES employee(employee_id)
                                    ON UPDATE CASCADE
                                    ON DELETE CASCADE,
    crew_role       VARCHAR(50) NOT NULL,

    PRIMARY KEY (flight_id, employee_id)
);

CREATE OR REPLACE FUNCTION check_seat_availability()
RETURNS TRIGGER AS $$
DECLARE
    v_capacity   INTEGER;
    v_sold       INTEGER;
BEGIN
    -- Вместимость самолёта для данного рейса.
    -- FOR UPDATE OF f блокирует строку рейса: одновременные вставки билетов
    -- на один рейс сериализуются, иначе две параллельные транзакции могли бы
    -- обе пройти проверку и привести к перепродаже сверх вместимости.
    SELECT a.capacity INTO v_capacity
    FROM flight f
    JOIN aircraft a ON a.tail_number = f.tail_number
    WHERE f.flight_id = NEW.flight_id
    FOR UPDATE OF f;

    -- Количество уже проданных билетов
    SELECT COUNT(*) INTO v_sold
    FROM ticket
    WHERE flight_id = NEW.flight_id;

    IF v_sold >= v_capacity THEN
        RAISE EXCEPTION
            'Нет свободных мест на рейс % (вместимость: %, продано: %)',
            NEW.flight_id, v_capacity, v_sold;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_check_seat_availability
BEFORE INSERT ON ticket
FOR EACH ROW EXECUTE FUNCTION check_seat_availability();