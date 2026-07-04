# esp32_server.py

from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session as DBSession
from datetime import datetime
import os
from dotenv import load_dotenv
import logging
from typing import Optional

# 🔥 ML (safe optional)
import joblib
import numpy as np

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("smart-inhaler")

app = FastAPI(title="Smart Inhaler ESP32 Server", version="2.0.0")

# ---------------------------
# CORS
# ---------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------
# DATABASE
# ---------------------------
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:YOUR_PASSWORD@localhost:5432/smart_inhaler"
)

engine = create_engine(DATABASE_URL, future=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ---------------------------
# STARTUP: ensure devices table
# ---------------------------
@app.on_event("startup")
def startup_create_devices_table():
    try:
        with engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS devices (
                    device_id TEXT PRIMARY KEY,
                    patient_id INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
                    created_at TIMESTAMPTZ DEFAULT now()
                );
            """))
        logger.info("Devices table ready")
    except Exception as e:
        logger.error(f"Startup error: {e}")

# ---------------------------
# MODELS
# ---------------------------
class InhalerUsageData(BaseModel):
    patient_id: Optional[int] = None
    device_id: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    doses_left: int = Field(ge=0, le=200)
    flow_rate: float = Field(ge=0.0, le=100.0)
    pressure: float
    quality: str
    motion: float
    gas: float
    temperature: float = 25.0

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "device_id": "AA:BB:CC:DD:EE:FF",
                "doses_left": 95,
                "flow_rate": 45.5,
                "pressure": 1013.2,
                "quality": "Good",
                "motion": 0.2,
                "gas": 120.0,
                "temperature": 24.5
            }
        }
    )

class DeviceHealthCheck(BaseModel):
    device_id: str
    battery_level: float
    signal_strength: int
    firmware_version: str

# ---------------------------
# ROOT + HEALTH
# ---------------------------
@app.get("/")
def root():
    return {"status": "running", "version": "2.0.0"}

@app.get("/health")
def health():
    return {"status": "ok"}

# ---------------------------
# 🔥 MAIN ESP32 ENDPOINT
# ---------------------------
@app.post("/inhaler/usage")
def receive_inhaler_data(data: InhalerUsageData, request: Request, db: DBSession = Depends(get_db)):
    try:
        print("DEVICE RECEIVED:", data.device_id)
        # Validate quality
        valid_qualities = {"Good", "Fair", "Poor", "Missed"}
        if data.quality not in valid_qualities:
            raise HTTPException(400, "Invalid quality")

        logger.info(f"Data from {request.client.host}: {data.model_dump()}")

        # ---------------------------
        # DEVICE → PATIENT MAPPING
        # ---------------------------
        resolved_patient_id = None

        if data.device_id:
            row = db.execute(
                text("SELECT patient_id FROM devices WHERE device_id=:d"),
                {"d": data.device_id}
            ).fetchone()

            if row:
                resolved_patient_id = row[0]

        if resolved_patient_id is None and data.patient_id and data.device_id:
            db.execute(
                text("INSERT INTO devices (device_id, patient_id) VALUES (:d, :p)"),
                {"d": data.device_id, "p": data.patient_id}
            )
            db.commit()
            resolved_patient_id = data.patient_id

        if resolved_patient_id is None:
            raise HTTPException(400, "Device not paired")

        # ---------------------------
        # INSERT DATA
        # ---------------------------
        result = db.execute(text("""
            INSERT INTO inhaler_usage
            (patient_id, timestamp, doses_left, flow_rate, pressure, quality, motion, gas, temperature)
            VALUES
            (:pid, :ts, :dl, :fr, :pr, :q, :m, :g, :t)
            RETURNING id
        """), {
            "pid": resolved_patient_id,
            "ts": data.timestamp,
            "dl": data.doses_left,
            "fr": data.flow_rate,
            "pr": data.pressure,
            "q": data.quality,
            "m": data.motion,
            "g": data.gas,
            "t": data.temperature
        })

        usage_id = result.scalar()
        db.commit()

        # ---------------------------
        # 🔥 ML (SAFE)
        # ---------------------------
        try:
            model = joblib.load("ml_model/model.pkl")
            features = np.array([[data.flow_rate, data.pressure, data.motion, data.gas]])
            pred = model.predict(features)[0]
            logger.info(f"ML Prediction: {pred}")
        except Exception:
            pass

        return {"status": "success", "usage_id": usage_id}

    except Exception as e:
        db.rollback()
        logger.error(e)
        raise HTTPException(500, str(e))

# ---------------------------
# DEVICE HEALTH
# ---------------------------
@app.post("/device/health")
def device_health(health: DeviceHealthCheck):
    return {"status": "ok"}

# ---------------------------
# 🔥 LATEST
# ---------------------------
@app.get("/patient/{patient_id}/latest")
def latest(patient_id: int, db: DBSession = Depends(get_db)):
    row = db.execute(text("""
        SELECT *
        FROM inhaler_usage
        WHERE patient_id=:pid
        ORDER BY timestamp DESC
        LIMIT 1
    """), {"pid": patient_id}).mappings().first()

    if not row:
        raise HTTPException(404, "No data")

    return dict(row)

# ---------------------------
# 🔥 HISTORY
# ---------------------------
@app.get("/patient/{patient_id}/history")
def history(patient_id: int, db: DBSession = Depends(get_db)):
    rows = db.execute(text("""
        SELECT *
        FROM inhaler_usage
        WHERE patient_id=:pid
        ORDER BY timestamp DESC
        LIMIT 200
    """), {"pid": patient_id}).mappings().all()

    return [dict(r) for r in rows]

# ---------------------------
# 🔥 STATS
# ---------------------------
@app.get("/patient/{patient_id}/stats")
def stats(patient_id: int, db: DBSession = Depends(get_db)):
    row = db.execute(text("""
        SELECT COUNT(*) as total,
               AVG(flow_rate) as avg_flow
        FROM inhaler_usage
        WHERE patient_id=:pid
    """), {"pid": patient_id}).mappings().first()

    latest = db.execute(text("""
        SELECT doses_left
        FROM inhaler_usage
        WHERE patient_id=:pid
        ORDER BY timestamp DESC
        LIMIT 1
    """), {"pid": patient_id}).fetchone()

    return {
        "total_uses": row["total"] or 0,
        "avg_flow_rate": float(row["avg_flow"] or 0),
        "doses_remaining": latest[0] if latest else 0
    }

# ---------------------------
# RUN
# ---------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
