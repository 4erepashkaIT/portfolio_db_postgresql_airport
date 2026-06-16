-- ------------------------------------------------------------
-- AIRLINES (6 rows) — carriers serving Auckland (AKL)
-- ------------------------------------------------------------
INSERT INTO airline (iata_code, name, country) VALUES
    ('NZ', 'Air New Zealand',     'New Zealand'),
    ('QF', 'Qantas',              'Australia'),
    ('SQ', 'Singapore Airlines',  'Singapore'),
    ('EK', 'Emirates',            'United Arab Emirates'),
    ('CX', 'Cathay Pacific',      'Hong Kong'),
    ('FJ', 'Fiji Airways',        'Fiji');

-- ------------------------------------------------------------
-- AIRCRAFT (8 rows)
-- ------------------------------------------------------------
INSERT INTO aircraft (tail_number, model, capacity, year_built, iata_code) VALUES
    ('ZK-NZE', 'Boeing 787-9',         302, 2018, 'NZ'),
    ('ZK-OXA', 'Airbus A320neo',       168, 2021, 'NZ'),
    ('VH-OQA', 'Airbus A380-800',      485, 2014, 'QF'),
    ('VH-ZNJ', 'Boeing 787-9',         236, 2019, 'QF'),
    ('9V-SMF', 'Airbus A350-900',      303, 2017, 'SQ'),
    ('A6-EOA', 'Airbus A380-800',      489, 2015, 'EK'),
    ('B-LJA',  'Boeing 777-300ER',     368, 2016, 'CX'),
    ('DQ-FAI', 'Boeing 737-800',       170, 2016, 'FJ');

-- ------------------------------------------------------------
-- FLIGHTS (10 rows) — every flight departs from or arrives at Auckland
-- ------------------------------------------------------------
INSERT INTO flight (flight_number, city_from, city_to,
                    depart_at, arrive_at, status, tail_number) VALUES
    -- Completed flights — in the past (May 2026)
    ('NZ0247', 'Auckland',  'Sydney',
     '2026-05-10 09:00', '2026-05-10 12:40', 'completed',  'ZK-NZE'),
    ('NZ0246', 'Sydney',    'Auckland',
     '2026-05-12 14:00', '2026-05-12 19:35', 'completed',  'ZK-NZE'),
    ('NZ8021', 'Auckland',  'Wellington',
     '2026-05-15 07:00', '2026-05-15 08:05', 'completed',  'ZK-OXA'),
    ('QF0162', 'Auckland',  'Melbourne',
     '2026-05-20 16:00', '2026-05-20 18:05', 'completed',  'VH-OQA'),
    -- Cancelled flight — recent past (within the reporting period)
    ('CX0198', 'Auckland',  'Hong Kong',
     '2026-06-02 23:55', '2026-06-03 07:30', 'cancelled',  'B-LJA'),
    -- Delayed flight — around the current date (16 Jun 2026)
    ('QF0144', 'Melbourne', 'Auckland',
     '2026-06-16 10:00', '2026-06-16 13:50', 'delayed',    'VH-ZNJ'),
    -- Scheduled flights — in the future (July 2026)
    ('SQ0285', 'Singapore', 'Auckland',
     '2026-07-03 23:30', '2026-07-04 13:00', 'scheduled',  '9V-SMF'),
    ('EK0450', 'Auckland',  'Dubai',
     '2026-07-05 22:15', '2026-07-06 16:00', 'scheduled',  'A6-EOA'),
    ('FJ0410', 'Nadi',      'Auckland',
     '2026-07-08 12:00', '2026-07-08 15:05', 'scheduled',  'DQ-FAI'),
    ('NZ0005', 'Auckland',  'Los Angeles',
     '2026-07-10 19:30', '2026-07-11 11:00', 'scheduled',  'ZK-NZE');

-- ------------------------------------------------------------
-- PASSENGERS (10 rows)
-- ------------------------------------------------------------
INSERT INTO passenger (last_name, first_name, middle_name,
                        passport_no, birth_date, phone) VALUES
    ('Smith',    'James',     'Andrew',  'PA123456',  '1990-05-14', '+64 21 555 0143'),
    ('Wang',     'Li',        NULL,      'E12345678', '1985-11-03', '+86 138 0013 8000'),
    ('Patel',    'Arjun',     'Raj',     'M9876543',  '1995-07-22', '+91 98765 43210'),
    ('Johnson',  'Emily',     'Rose',    'P4455667',  '1988-02-18', '+1 415 555 0199'),
    ('Tanaka',   'Hiroshi',   NULL,      'TK7788990', '1975-09-30', '+81 90 1234 5678'),
    ('Mueller',  'Anna',      'Marie',   'C0FF3344',  '2000-12-05', '+49 151 23456789'),
    ('Brown',    'Oliver',    'John',    'GBR556677', '1980-06-25', '+44 7700 900123'),
    ('Nguyen',   'Mai',       NULL,      'VN334455',  '1998-08-17', '+84 90 123 4567'),
    ('Garcia',   'Sofia',     'Isabel',  'ESP998877', '1993-03-11', '+34 612 345 678'),
    ('Williams', 'Charlotte', 'Grace',   'AU112233',  '1970-01-09', '+61 4 1234 5678');

-- ------------------------------------------------------------
-- TICKETS (12 rows) — prices in USD
-- ------------------------------------------------------------
INSERT INTO ticket (ticket_no, seat_no, service_class,
                     price, purchase_date, passenger_id, flight_id) VALUES
    -- Tickets on completed flights (departed May 2026), bought in April–May
    ('0001234567890', '12A', 'economy',   280.00, '2026-04-25', 1,  1),
    ('0001234567891', '12B', 'economy',   280.00, '2026-04-25', 2,  1),
    ('0001234567892', '2A',  'business', 1200.00, '2026-04-20', 3,  1),
    ('0001234567893', '15C', 'economy',   260.00, '2026-04-28', 4,  2),
    ('0001234567894', '8D',  'economy',    95.00, '2026-04-30', 5,  3),
    ('0001234567895', '22E', 'economy',   110.00, '2026-05-01', 6,  3),
    ('0001234567896', '20A', 'economy',   320.00, '2026-05-05', 10, 4),
    -- Tickets on scheduled flights (depart July 2026), bought in May–June
    ('0001234567897', '3A',  'first',    9800.00, '2026-05-15', 7,  7),
    ('0001234567898', '10B', 'economy',  1150.00, '2026-05-22', 8,  7),
    ('0001234567899', '5C',  'business', 4200.00, '2026-05-18', 9,  8),
    ('0001234567900', '14B', 'economy',   480.00, '2026-06-01', 1,  9),
    ('0001234567901', '7A',  'business', 3600.00, '2026-06-01', 3, 10);

-- ------------------------------------------------------------
-- EMPLOYEES (8 rows)
-- ------------------------------------------------------------
INSERT INTO employee (employee_id, last_name, first_name, middle_name,
                       position, hire_date) VALUES
    (100001, 'Thompson', 'Michael', 'James',   'pilot',            '2010-03-15'),
    (100002, 'Anderson', 'David',   NULL,      'co-pilot',         '2015-07-01'),
    (100003, 'Lee',      'Grace',   NULL,      'flight attendant', '2018-09-10'),
    (100004, 'Wilson',   'Robert',  'Charles', 'pilot',            '2008-05-20'),
    (100005, 'Martin',   'Sophie',  NULL,      'flight attendant', '2020-02-14'),
    (100006, 'Taylor',   'Daniel',  'Mark',    'co-pilot',         '2017-11-03'),
    (100007, 'Harris',   'Emma',    NULL,      'flight attendant', '2019-06-22'),
    (100008, 'Clark',    'Ethan',   NULL,      'pilot',            '2012-08-30');

-- ------------------------------------------------------------
-- CREW ASSIGNMENTS (10 rows)
-- ------------------------------------------------------------
INSERT INTO crew_assignment (flight_id, employee_id, crew_role) VALUES
    (1, 100001, 'captain'),
    (1, 100002, 'first officer'),
    (1, 100003, 'senior flight attendant'),
    (2, 100001, 'captain'),
    (2, 100006, 'first officer'),
    (3, 100004, 'captain'),
    (3, 100005, 'flight attendant'),
    (3, 100007, 'flight attendant'),
    (7, 100004, 'captain'),
    (7, 100002, 'first officer');
