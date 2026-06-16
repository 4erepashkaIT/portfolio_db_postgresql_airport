-- ============================================================
-- Create users
-- ============================================================
CREATE USER admin_user      WITH PASSWORD 'admin_pass_2024'      CREATEDB CREATEROLE;
CREATE USER dispatcher_user WITH PASSWORD 'dispatcher_pass_2024';
CREATE USER cashier_user    WITH PASSWORD 'cashier_pass_2024';

-- ============================================================
-- ADMINISTRATOR — full access
-- ============================================================
GRANT ALL PRIVILEGES ON DATABASE airport_db        TO admin_user;
GRANT ALL PRIVILEGES ON ALL TABLES    IN SCHEMA public TO admin_user;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO admin_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT ALL ON TABLES    TO admin_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT ALL ON SEQUENCES TO admin_user;

-- ============================================================
-- DISPATCHER
-- ============================================================
GRANT SELECT ON ALL TABLES IN SCHEMA public TO dispatcher_user;

GRANT INSERT, UPDATE, DELETE ON TABLE flight          TO dispatcher_user;
GRANT INSERT, UPDATE, DELETE ON TABLE crew_assignment TO dispatcher_user;
GRANT UPDATE                 ON TABLE aircraft        TO dispatcher_user;
GRANT USAGE, SELECT ON SEQUENCE flight_flight_id_seq  TO dispatcher_user;

-- ============================================================
-- CASHIER
-- ============================================================
-- Read: flights, passengers, tickets + aircraft (needed for JOINs in queries 4, 7, 10 and reports)
GRANT SELECT ON TABLE flight     TO cashier_user;
GRANT SELECT ON TABLE passenger  TO cashier_user;
GRANT SELECT ON TABLE ticket     TO cashier_user;
GRANT SELECT ON TABLE aircraft   TO cashier_user;

-- Write: new passengers and tickets
GRANT INSERT ON TABLE passenger  TO cashier_user;
GRANT INSERT ON TABLE ticket     TO cashier_user;

-- Cancel tickets (delete)
GRANT DELETE ON TABLE ticket     TO cashier_user;

-- Update only a passenger's phone and passport
GRANT UPDATE (phone, passport_no) ON TABLE passenger TO cashier_user;

-- Sequence for the passenger_id auto-increment
GRANT USAGE, SELECT ON SEQUENCE passenger_passenger_id_seq TO cashier_user;
