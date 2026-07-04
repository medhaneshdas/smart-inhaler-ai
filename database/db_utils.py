"""
Database utility functions for Smart Inhaler system
Provides SQLAlchemy models and helper functions
"""

from __future__ import annotations

import os
import subprocess
from datetime import datetime, timedelta
from typing import Generator, Optional, Dict, Any, List, Tuple

from dotenv import load_dotenv
from sqlalchemy import (
    create_engine, Column, Integer, String, Float, Boolean, DateTime, ForeignKey, text, func
)
from sqlalchemy.orm import sessionmaker, relationship, declarative_base, Session

load_dotenv()

# ───────────────────────────────────────────────────────────
# Database connection
# ───────────────────────────────────────────────────────────
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:YOUR_PASSWORD@localhost:5432/smart_inhaler")
engine = create_engine(DATABASE_URL, echo=False, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

# ───────────────────────────────────────────────────────────
# SQLAlchemy Models
# ───────────────────────────────────────────────────────────
class Patient(Base):
    __tablename__ = "patients"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    name = Column(String(100), nullable=False)
    age = Column(Integer)
    asthma_severity = Column(String(20))
    doctor_contact = Column(String(255))
    doctor_phone = Column(String(20))
    onboarded = Column(Boolean, default=False)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    usage_records = relationship(
        "InhalerUsage", back_populates="patient", cascade="all, delete-orphan"
    )


class InhalerUsage(Base):
    __tablename__ = "inhaler_usage"

    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False, index=True)
    timestamp = Column(DateTime, default=func.now(), nullable=False, index=True)
    doses_left = Column(Integer)
    flow_rate = Column(Float)
    pressure = Column(Float)
    quality = Column(String(20))
    motion = Column(Float)
    gas = Column(Float)
    temperature = Column(Float, default=25.0)
    created_at = Column(DateTime, default=func.now())

    # Relationships
    patient = relationship("Patient", back_populates="usage_records")
    predictions = relationship(
        "MLPrediction", back_populates="usage", cascade="all, delete-orphan"
    )


class MLPrediction(Base):
    __tablename__ = "ml_predictions"

    id = Column(Integer, primary_key=True, index=True)
    usage_id = Column(Integer, ForeignKey("inhaler_usage.id"), nullable=False, index=True)
    correct_usage = Column(Boolean)
    correct_usage_probability = Column(Float)
    risk_score = Column(Float)
    risk_level = Column(String(20))
    created_at = Column(DateTime, default=func.now())

    # Relationships
    usage = relationship("InhalerUsage", back_populates="predictions")

# ───────────────────────────────────────────────────────────
# Database session management
# ───────────────────────────────────────────────────────────
def get_db() -> Generator[Session, None, None]:
    """Dependency for getting database session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db() -> None:
    """Initialize database - create all tables"""
    Base.metadata.create_all(bind=engine)
    print("✅ Database tables created successfully")

def drop_db() -> None:
    """Drop all tables - USE WITH CAUTION"""
    Base.metadata.drop_all(bind=engine)
    print("⚠️ All database tables dropped")

# ───────────────────────────────────────────────────────────
# Helper functions
# ───────────────────────────────────────────────────────────
def create_patient(
    db: Session,
    username: str,
    password_hash: str,
    name: str,
    age: int,
    severity: str,
    doctor_contact: str,
    doctor_phone: str,
) -> Patient:
    """Create new patient"""
    patient = Patient(
        username=username,
        password_hash=password_hash,
        name=name,
        age=age,
        asthma_severity=severity,
        doctor_contact=doctor_contact,
        doctor_phone=doctor_phone,
        onboarded=False,
    )
    db.add(patient)
    db.commit()
    db.refresh(patient)
    return patient

def get_patient_by_username(db: Session, username: str) -> Optional[Patient]:
    return db.query(Patient).filter(Patient.username == username).first()

def get_patient_by_id(db: Session, patient_id: int) -> Optional[Patient]:
    return db.query(Patient).filter(Patient.id == patient_id).first()

def create_usage_record(
    db: Session,
    patient_id: int,
    doses_left: int,
    flow_rate: float,
    pressure: float,
    quality: str,
    motion: float,
    gas: float,
    temperature: float = 25.0,
) -> InhalerUsage:
    """Create new inhaler usage record"""
    usage = InhalerUsage(
        patient_id=patient_id,
        doses_left=doses_left,
        flow_rate=flow_rate,
        pressure=pressure,
        quality=quality,
        motion=motion,
        gas=gas,
        temperature=temperature,
    )
    db.add(usage)
    db.commit()
    db.refresh(usage)
    return usage

def get_patient_usage(db: Session, patient_id: int, limit: int = 100) -> List[InhalerUsage]:
    return (
        db.query(InhalerUsage)
        .filter(InhalerUsage.patient_id == patient_id)
        .order_by(InhalerUsage.timestamp.desc())
        .limit(limit)
        .all()
    )

def get_usage_stats(db: Session, patient_id: int) -> Dict[str, Any]:
    """
    Returns:
      - total_uses: count of records
      - avg_flow_rate: average flow
      - doses_remaining: latest doses_left (more useful than minimum)
      - last_use: latest timestamp
      - quality_breakdown: dict of counts per quality
    """
    stats = (
        db.query(
            func.count(InhalerUsage.id).label("total_uses"),
            func.avg(InhalerUsage.flow_rate).label("avg_flow_rate"),
            func.max(InhalerUsage.timestamp).label("last_use"),
        )
        .filter(InhalerUsage.patient_id == patient_id)
        .first()
    )

    # latest doses_left
    latest = (
        db.query(InhalerUsage.doses_left)
        .filter(InhalerUsage.patient_id == patient_id)
        .order_by(InhalerUsage.timestamp.desc())
        .limit(1)
        .first()
    )
    doses_remaining = latest[0] if latest and latest[0] is not None else 0

    quality_counts = (
        db.query(InhalerUsage.quality, func.count(InhalerUsage.id))
        .filter(InhalerUsage.patient_id == patient_id)
        .group_by(InhalerUsage.quality)
        .all()
    )

    return {
        "total_uses": int(stats.total_uses or 0),
        "avg_flow_rate": round(float(stats.avg_flow_rate or 0), 2),
        "doses_remaining": int(doses_remaining),
        "last_use": stats.last_use,
        "quality_breakdown": dict(quality_counts),
    }

def create_ml_prediction(
    db: Session,
    usage_id: int,
    correct_usage: bool,
    correct_prob: float,
    risk_score: float,
) -> MLPrediction:
    """Create ML prediction record with derived risk_level"""
    if risk_score < 0.3:
        risk_level = "Low"
    elif risk_score < 0.7:
        risk_level = "Medium"
    else:
        risk_level = "High"

    prediction = MLPrediction(
        usage_id=usage_id,
        correct_usage=correct_usage,
        correct_usage_probability=correct_prob,
        risk_score=risk_score,
        risk_level=risk_level,
    )
    db.add(prediction)
    db.commit()
    db.refresh(prediction)
    return prediction

def get_recent_predictions(db: Session, patient_id: int, limit: int = 10) -> List[MLPrediction]:
    return (
        db.query(MLPrediction)
        .join(InhalerUsage)
        .filter(InhalerUsage.patient_id == patient_id)
        .order_by(MLPrediction.created_at.desc())
        .limit(limit)
        .all()
    )

# ───────────────────────────────────────────────────────────
# Maintenance / Admin
# ───────────────────────────────────────────────────────────
def backup_database(output_file: str = "backup.sql") -> None:
    """Backup database to SQL file using pg_dump"""
    db_url = os.getenv("DATABASE_URL", "")
    if not db_url:
        raise RuntimeError("DATABASE_URL not set")

    # Prefer passing as --dbname to avoid shell parsing issues.
    cmd = ["pg_dump", f"--dbname={db_url}"]
    with open(output_file, "wb") as f:
        subprocess.run(cmd, stdout=f, check=True)
    print(f"✅ Database backed up to {output_file}")

def restore_database(input_file: str = "backup.sql") -> None:
    """Restore database from SQL file using psql"""
    db_url = os.getenv("DATABASE_URL", "")
    if not db_url:
        raise RuntimeError("DATABASE_URL not set")

    cmd = ["psql", f"--dbname={db_url}", "-f", input_file]
    subprocess.run(cmd, check=True)
    print(f"✅ Database restored from {input_file}")

def validate_usage_data(data: Dict[str, Any]) -> List[str]:
    """Validate inhaler usage data"""
    errors: List[str] = []

    fr = float(data.get("flow_rate", 0))
    if fr < 0 or fr > 100:
        errors.append("Flow rate must be between 0 and 100 L/min")

    dl = int(data.get("doses_left", 0))
    if dl < 0 or dl > 200:
        errors.append("Doses left must be between 0 and 200")

    valid_qualities = ["Good", "Fair", "Poor", "Missed"]
    if data.get("quality") not in valid_qualities:
        errors.append(f"Quality must be one of {valid_qualities}")

    pr = float(data.get("pressure", 0))
    if pr < 900 or pr > 1100:
        errors.append("Pressure value seems unrealistic")

    return errors

def cleanup_old_records(db: Session, days: int = 90) -> int:
    """Delete records older than specified days"""
    cutoff_date = datetime.now() - timedelta(days=days)
    deleted = (
        db.query(InhalerUsage)
        .filter(InhalerUsage.timestamp < cutoff_date)
        .delete(synchronize_session=False)
    )
    db.commit()
    print(f"✅ Deleted {deleted} records older than {days} days")
    return int(deleted)

def optimize_database() -> None:
    """
    Run VACUUM ANALYZE with autocommit.
    VACUUM cannot run inside a normal transaction.
    """
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.execute(text("VACUUM ANALYZE"))
    print("✅ Database optimized")

# ───────────────────────────────────────────────────────────
# Usage example and testing
# ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("Smart Inhaler Database Utilities")
    print("=" * 50)

    # Initialize database
    init_db()

    # Create test session
    db = SessionLocal()
    try:
        from hashlib import sha256

        password_hash = sha256("testpass".encode()).hexdigest()

        patient = create_patient(
            db,
            username="test_user",
            password_hash=password_hash,
            name="Test User",
            age=30,
            severity="Moderate",
            doctor_contact="doctor@test.com",
            doctor_phone="+911234567890"
        )
        print(f"✅ Created patient: {patient.name} (ID: {patient.id})")

        usage = create_usage_record(
            db,
            patient_id=patient.id,
            doses_left=95,
            flow_rate=45.5,
            pressure=1013.25,
            quality="Good",
            motion=0.15,
            gas=120.5,
        )
        print(f"✅ Created usage record (ID: {usage.id})")

        stats = get_usage_stats(db, patient.id)
        print(f"✅ Stats: {stats}")

        optimize_database()

    except Exception as e:
        print(f"❌ Error: {e}")
        db.rollback()
    finally:
        db.close()

    print("=" * 50)
    print("Database utilities ready to use!")
