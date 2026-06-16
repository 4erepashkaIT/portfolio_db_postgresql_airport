-- ------------------------------------------------------------
-- 1. AIRLINE
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS airline (
    iata_code   CHAR(2)         PRIMARY KEY,                         -- 'NZ', 'QF', 'SQ'
    name        VARCHAR(100)    NOT NULL,
    country     VARCHAR(60)     NOT NULL
);

-- ------------------------------------------------------------
-- 2. AIRCRAFT
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS aircraft (
    tail_number VARCHAR(10)     PRIMARY KEY,                         -- 'ZK-NZE'
    model       VARCHAR(50)     NOT NULL,
    capacity    SMALLINT        NOT NULL,
    year_built  SMALLINT        NOT NULL,
    iata_code   CHAR(2)         NOT NULL REFERENCES airline(iata_code)
                                    ON UPDATE CASCADE
                                    ON DELETE RESTRICT,

    CONSTRAINT chk_capacity    CHECK (capacity > 0),
    -- Static bound: a CHECK must not depend on non-immutable functions
    -- (CURRENT_DATE) — that breaks dump/restore and silently drifts each year.
    -- The 2100 upper bound is a sanity limit; "not from the future" is enforced
    -- by the application (year max_value = date.today().year).
    CONSTRAINT chk_year_built  CHECK (year_built BETWEEN 1950 AND 2100)
);

-- ------------------------------------------------------------
-- 3. FLIGHT
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS flight (
    flight_id       SERIAL          PRIMARY KEY,
    flight_number   VARCHAR(10)     NOT NULL,                        -- 'NZ0101'
    city_from       VARCHAR(80)     NOT NULL,
    city_to         VARCHAR(80)     NOT NULL,
    depart_at       TIMESTAMP       NOT NULL,
    arrive_at       TIMESTAMP       NOT NULL,
    status          VARCHAR(15)     NOT NULL DEFAULT 'scheduled',
    tail_number     VARCHAR(10)     NOT NULL REFERENCES aircraft(tail_number)
                                        ON UPDATE CASCADE
                                        ON DELETE RESTRICT,

    CONSTRAINT chk_flight_time   CHECK (arrive_at > depart_at),
    CONSTRAINT chk_flight_status CHECK (status IN (
                                    'scheduled', 'delayed',
                                    'cancelled', 'completed')),
    -- Single-hub airport: every flight must depart from or arrive at Auckland.
    CONSTRAINT chk_airport_hub   CHECK (city_from = 'Auckland'
                                     OR city_to   = 'Auckland')
);

-- ------------------------------------------------------------
-- 4. PASSENGER
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS passenger (
    passenger_id    SERIAL          PRIMARY KEY,
    last_name       VARCHAR(50)     NOT NULL,
    first_name      VARCHAR(50)     NOT NULL,
    middle_name     VARCHAR(50),                                     -- middle name is optional
    passport_no     VARCHAR(20)     NOT NULL UNIQUE,
    birth_date      DATE            NOT NULL,
    phone           VARCHAR(20)     NOT NULL
);

-- ------------------------------------------------------------
-- 5. TICKET
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
    CONSTRAINT chk_service_class CHECK (service_class IN ('economy', 'business', 'first')),
    CONSTRAINT uq_seat_flight    UNIQUE (flight_id, seat_no)         -- one seat — one passenger
);

-- ------------------------------------------------------------
-- 6. EMPLOYEE
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS employee (
    employee_id     INTEGER         PRIMARY KEY,                     -- 6-digit staff number
    last_name       VARCHAR(50)     NOT NULL,
    first_name      VARCHAR(50)     NOT NULL,
    middle_name     VARCHAR(50),
    position        VARCHAR(20)     NOT NULL,
    hire_date       DATE            NOT NULL,

    CONSTRAINT chk_employee_id  CHECK (employee_id BETWEEN 100000 AND 999999),
    CONSTRAINT chk_position     CHECK (position IN (
                                    'pilot', 'co-pilot', 'flight attendant'))
);

-- ------------------------------------------------------------
-- 7. CREW ASSIGNMENT (M:N junction table)
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
    -- Aircraft capacity for this flight.
    -- FOR UPDATE OF f locks the flight row: concurrent ticket inserts for the
    -- same flight are serialized, otherwise two parallel transactions could
    -- both pass the check and oversell beyond capacity.
    SELECT a.capacity INTO v_capacity
    FROM flight f
    JOIN aircraft a ON a.tail_number = f.tail_number
    WHERE f.flight_id = NEW.flight_id
    FOR UPDATE OF f;

    SELECT COUNT(*) INTO v_sold
    FROM ticket
    WHERE flight_id = NEW.flight_id;

    IF v_sold >= v_capacity THEN
        RAISE EXCEPTION
            'No seats available on flight % (capacity: %, sold: %)',
            NEW.flight_id, v_capacity, v_sold;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_check_seat_availability
BEFORE INSERT ON ticket
FOR EACH ROW EXECUTE FUNCTION check_seat_availability();
