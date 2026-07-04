-- Smart Inhaler Database Schema (PostgreSQL 12+)
-- Idempotent: safe to run multiple times

BEGIN;

-- ─────────────────────────────────────────────────────────
-- Drop dependent objects first (views, triggers, functions)
-- ─────────────────────────────────────────────────────────
DROP VIEW IF EXISTS recent_inhaler_activity;
DROP VIEW IF EXISTS patient_dashboard_summary;

DROP TRIGGER IF EXISTS update_patients_updated_at ON patients;
DROP FUNCTION IF EXISTS update_updated_at_column();

-- ─────────────────────────────────────────────────────────
-- Drop tables (order matters due to FKs)
-- ─────────────────────────────────────────────────────────
DROP TABLE IF EXISTS ml_predictions CASCADE;
DROP TABLE IF EXISTS inhaler_usage CASCADE;
DROP TABLE IF EXISTS patients CASCADE;

-- ─────────────────────────────────────────────────────────
-- Base tables
-- ─────────────────────────────────────────────────────────

CREATE TABLE patients (
    id              SERIAL PRIMARY KEY,
    username        VARCHAR(50) UNIQUE NOT NULL,
    password_hash   VARCHAR(255) NOT NULL,
    name            VARCHAR(100) NOT NULL,
    age             INTEGER CHECK (age > 0 AND age < 150),
    asthma_severity VARCHAR(20) CHECK (asthma_severity IN ('Mild', 'Moderate', 'Severe')),
    doctor_contact  VARCHAR(255),
    onboarded       BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE inhaler_usage (
    id          SERIAL PRIMARY KEY,
    patient_id  INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    "timestamp" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    doses_left  INTEGER CHECK (doses_left >= 0 AND doses_left <= 200),
    flow_rate   DOUBLE PRECISION CHECK (flow_rate >= 0 AND flow_rate <= 100),
    pressure    DOUBLE PRECISION,  -- hPa
    quality     VARCHAR(20) CHECK (quality IN ('Good', 'Fair', 'Poor', 'Missed')),
    motion      DOUBLE PRECISION,
    gas         DOUBLE PRECISION,
    temperature DOUBLE PRECISION DEFAULT 25.0,
    created_at  TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE ml_predictions (
    id                           SERIAL PRIMARY KEY,
    usage_id                     INTEGER NOT NULL REFERENCES inhaler_usage(id) ON DELETE CASCADE,
    correct_usage                BOOLEAN,
    correct_usage_probability    DOUBLE PRECISION CHECK (correct_usage_probability >= 0 AND correct_usage_probability <= 1),
    risk_score                   DOUBLE PRECISION CHECK (risk_score >= 0 AND risk_score <= 1),
    risk_level                   VARCHAR(20) CHECK (risk_level IN ('Low', 'Medium', 'High')),
    created_at                   TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- ─────────────────────────────────────────────────────────
-- Indexes
-- ─────────────────────────────────────────────────────────
CREATE INDEX idx_patients_username ON patients(username);

CREATE INDEX idx_inhaler_usage_patient_id ON inhaler_usage(patient_id);
CREATE INDEX idx_inhaler_usage_timestamp ON inhaler_usage("timestamp");
CREATE INDEX idx_inhaler_usage_patient_timestamp ON inhaler_usage(patient_id, "timestamp" DESC);

CREATE INDEX idx_ml_predictions_usage_id ON ml_predictions(usage_id);

-- ─────────────────────────────────────────────────────────
-- Trigger to auto-update updated_at
-- ─────────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER update_patients_updated_at
BEFORE UPDATE ON patients
FOR EACH ROW
EXECUTE FUNCTION update_updated_at_column();

-- ─────────────────────────────────────────────────────────
-- Sample data
-- Password hashes are SHA256 of noted plaintext for demo only
-- ─────────────────────────────────────────────────────────
INSERT INTO patients (username, password_hash, name, age, asthma_severity, doctor_contact, onboarded)
VALUES 
    ('demo_patient', 'ef92b778bafe771e89245b89ecbc08a44a4e166c06659911881f383d4473e94f', 'Demo Patient', 35, 'Moderate', 'doctor@example.com', TRUE),
    ('john_doe',     '5e884898da28047151d0e56f8dc6292773603d0d6aabbdd62a11ef721d1542d8', 'John Doe',     42, 'Severe',   'doctor@hospital.com', TRUE),
    ('jane_smith',   '6ca13d52ca70c883e0f0bb101e425a89e8624de51db2d2392593af6a84118090', 'Jane Smith',   28, 'Mild',     'health@clinic.com',   FALSE);

-- Note: 'password' for demo_patient/john_doe; 'abc123' for jane_smith

INSERT INTO inhaler_usage (patient_id, "timestamp", doses_left, flow_rate, pressure, quality, motion, gas, temperature)
VALUES 
    (1, NOW() - INTERVAL '1 hour',  95, 45.5, 1013.25, 'Good',  0.15, 120.5, 24.6),
    (1, NOW() - INTERVAL '8 hours', 96, 42.0, 1012.80, 'Fair',  0.25, 125.0, 25.1),
    (1, NOW() - INTERVAL '16 hours',97, 38.5, 1014.10, 'Poor',  0.40, 130.0, 24.9),
    (1, NOW() - INTERVAL '24 hours',98, 48.0, 1013.50, 'Good',  0.12, 118.0, 24.7),
    (1, NOW() - INTERVAL '32 hours',99, 44.5, 1012.95, 'Good',  0.18, 122.0, 25.0),
    (2, NOW() - INTERVAL '2 hours', 78, 50.0, 1015.20, 'Good',  0.10, 115.0, 24.3),
    (2, NOW() - INTERVAL '10 hours',79, 35.0, 1014.50, 'Poor',  0.45, 135.0, 24.1),
    (2, NOW() - INTERVAL '18 hours',80, 46.5, 1013.80, 'Fair',  0.22, 128.0, 24.8);

INSERT INTO ml_predictions (usage_id, correct_usage, correct_usage_probability, risk_score, risk_level)
VALUES 
    (1, TRUE,  0.92, 0.15, 'Low'),
    (2, TRUE,  0.78, 0.35, 'Medium'),
    (3, FALSE, 0.45, 0.65, 'High'),
    (4, TRUE,  0.88, 0.20, 'Low'),
    (5, TRUE,  0.85, 0.25, 'Low'),
    (6, TRUE,  0.95, 0.10, 'Low'),
    (7, FALSE, 0.40, 0.70, 'High'),
    (8, TRUE,  0.80, 0.30, 'Medium');

-- ─────────────────────────────────────────────────────────
-- Views
-- ─────────────────────────────────────────────────────────

-- Dashboard summary:
-- doses_remaining should reflect the latest usage record, not MIN.
-- We use DISTINCT ON to pick the latest doses_left per patient.
CREATE OR REPLACE VIEW patient_dashboard_summary AS
WITH latest AS (
    SELECT DISTINCT ON (u.patient_id)
           u.patient_id, u.doses_left, u."timestamp"
    FROM inhaler_usage u
    ORDER BY u.patient_id, u."timestamp" DESC
)
SELECT 
    p.id AS patient_id,
    p.name,
    p.asthma_severity,
    COUNT(u.id)                    AS total_uses,
    MAX(u."timestamp")             AS last_use,
    AVG(u.flow_rate)               AS avg_flow_rate,
    l.doses_left                   AS doses_remaining,
    SUM(CASE WHEN u.quality = 'Good' THEN 1 ELSE 0 END)        AS good_quality_count,
    SUM(CASE WHEN u.quality IN ('Poor','Missed') THEN 1 ELSE 0 END) AS poor_quality_count,
    AVG(m.risk_score)              AS avg_risk_score
FROM patients p
LEFT JOIN inhaler_usage u ON p.id = u.patient_id
LEFT JOIN ml_predictions m ON u.id = m.usage_id
LEFT JOIN latest l ON l.patient_id = p.id
GROUP BY p.id, p.name, p.asthma_severity, l.doses_left;

-- Recent activity (include temperature for completeness)
CREATE OR REPLACE VIEW recent_inhaler_activity AS
SELECT 
    u.id,
    p.name AS patient_name,
    u."timestamp",
    u.doses_left,
    u.flow_rate,
    u.pressure,
    u.quality,
    u.motion,
    u.gas,
    u.temperature,
    m.correct_usage,
    m.risk_score,
    m.risk_level
FROM inhaler_usage u
JOIN patients p ON u.patient_id = p.id
LEFT JOIN ml_predictions m ON u.id = m.usage_id
ORDER BY u."timestamp" DESC
LIMIT 100;

-- ─────────────────────────────────────────────────────────
-- Verification
-- ─────────────────────────────────────────────────────────
SELECT 'Database schema created successfully!' AS status;
SELECT COUNT(*) AS patient_count FROM patients;
SELECT COUNT(*) AS usage_count FROM inhaler_usage;
SELECT COUNT(*) AS prediction_count FROM ml_predictions;

SELECT * FROM patient_dashboard_summary;
SELECT * FROM recent_inhaler_activity LIMIT 5;

COMMIT;

SELECT * FROM inhaler_usage WHERE id = 10;

-- who are the patients?
SELECT id, username, name FROM patients ORDER BY id;

-- where did the ESP32 write?
SELECT patient_id, COUNT(*) 
FROM inhaler_usage 
GROUP BY patient_id ORDER BY patient_id;

-- latest few rows
SELECT id, patient_id, "timestamp", flow_rate, quality
FROM inhaler_usage
ORDER BY id DESC
LIMIT 5;

UPDATE inhaler_usage
SET patient_id = 3
WHERE id = (SELECT max(id) FROM inhaler_usage);

SELECT id, username, name FROM patients ORDER BY id DESC;

CREATE TABLE IF NOT EXISTS devices (
  device_id TEXT PRIMARY KEY,
  patient_id INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_devices_patient ON devices(patient_id);

