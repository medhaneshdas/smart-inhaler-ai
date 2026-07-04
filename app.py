import os
from exporter import generate_patient_report
from io import BytesIO
import hashlib
import smtplib
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders

from notification import AlertSystem

import streamlit as st
import pandas as pd
import numpy as np
import requests

import plotly.express as px
import plotly.graph_objects as go

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

from whatsapp import send_whatsapp_message

from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors
import joblib

# ───────────────────────────────────────────────────────────
# Config
# ───────────────────────────────────────────────────────────
load_dotenv()

st.set_page_config(
    page_title="Smart Inhaler Dashboard",
    page_icon="💨",
    layout="wide",
    initial_sidebar_state="expanded"
)

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:YOUR_PASSWORD@localhost:5432/smart_inhaler"
)
engine = create_engine(DATABASE_URL, future=True)
Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

# ───────────────────────────────────────────────────────────
# Session state
# ───────────────────────────────────────────────────────────
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "patient_id" not in st.session_state:
    st.session_state.patient_id = None
if "patient_name" not in st.session_state:
    st.session_state.patient_name = ""
if "onboarded" not in st.session_state:
    st.session_state.onboarded = False
if "dark_mode" not in st.session_state:
    st.session_state.dark_mode = False

# ───────────────────────────────────────────────────────────
# Helpers (Auth & DB)
# ───────────────────────────────────────────────────────────
def hash_password(password: str) -> str:
    # demo-grade hashing; consider salted hashing (bcrypt/argon2) for production
    return hashlib.sha256(password.encode()).hexdigest()

def authenticate_user(username: str, password: str):
    session = Session()
    try:
        res = session.execute(
            text("""
                SELECT id, name, onboarded
                FROM patients
                WHERE username = :u AND password_hash = :p
            """),
            {"u": username, "p": hash_password(password)}
        ).first()
        return res  # Row or None
    finally:
        session.close()

def register_user(username, password, name, age, asthma_severity, doctor_contact, doctor_phone):
    session = Session()
    try:
        session.execute(
            text("""
                INSERT INTO patients
                (username, password_hash, name, age, asthma_severity, doctor_contact, doctor_phone ,onboarded, created_at)
                VALUES (:username, :password_hash, :name, :age, :severity, :doctor, :doctor_phone, FALSE, NOW())
            """),
            {
                "username": username,
                "password_hash": hash_password(password),
                "name": name,
                "age": age,
                "severity": asthma_severity,
                "doctor": doctor_contact,
                "doctor_phone": doctor_phone,
            }
        )
        session.commit()
        return True
    except Exception as e:
        st.error(f"Registration error: {e}")
        session.rollback()
        return False
    finally:
        session.close()

def mark_onboarded(patient_id: int):
    session = Session()
    try:
        session.execute(
            text("UPDATE patients SET onboarded = TRUE WHERE id = :pid"),
            {"pid": patient_id}
        )
        session.commit()
    finally:
        session.close()

def get_patient_data(patient_id: int):
    session = Session()
    try:
        row = session.execute(
            text("SELECT * FROM patients WHERE id = :pid"),
            {"pid": patient_id}
        ).mappings().first()
        return row  # dict-like row (None if not found)
    finally:
        session.close()

# ---- New helper: bind device to patient ----
def bind_device_to_patient(device_id: str, patient_id: int) -> bool:
    """
    Bind (or rebind) a device MAC to a patient id.
    Uses ON CONFLICT to update existing mapping.
    Returns True on success, False on failure (and shows Streamlit error).
    """
    session = Session()
    try:
        session.execute(
            text("""
                INSERT INTO devices (device_id, patient_id, created_at)
                VALUES (:d, :p, NOW())
                ON CONFLICT (device_id) DO UPDATE SET patient_id = EXCLUDED.patient_id
            """),
            {"d": device_id, "p": int(patient_id)}
        )
        session.commit()
        return True
    except Exception as e:
        session.rollback()
        st.error(f"Failed to bind device: {e}")
        return False
    finally:
        session.close()
# --------------------------------------------

def get_usage_data(patient_id: int, days: int = 30) -> pd.DataFrame:
    """
    Correct Postgres interval binding using make_interval.
    Force timestamps to be timezone-aware (UTC) to avoid tz-naive/aware comparisons.
    """
    session = Session()
    try:
        res = session.execute(
            text("""
                SELECT id, patient_id, timestamp, doses_left, flow_rate, pressure, quality, motion, gas, temperature
                FROM inhaler_usage
                WHERE patient_id = :pid
                  AND timestamp >= NOW() - make_interval(days => :days)
                ORDER BY timestamp DESC
            """),
            {"pid": patient_id, "days": int(days)}
        ).mappings().all()

        if not res:
            return pd.DataFrame()

        df = pd.DataFrame(res)
        # ✅ make timestamp tz-aware (UTC)
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        return df
    finally:
        session.close()

# ───────────────────────────────────────────────────────────
# ML helpers (load + feature building + predict)
# ───────────────────────────────────────────────────────────
def load_ml_artifacts():
    """
    Loads classifier, feature column order, and optional risk model.
    Returns: (model, feature_columns, risk_model)
    """
    try:
        model = joblib.load("ml_model/model.pkl")
        feature_columns = joblib.load("ml_model/feature_columns.pkl")
    except Exception:
        return None, None, None

    try:
        risk_model = joblib.load("ml_model/risk_model.pkl")
    except Exception:
        risk_model = None

    return model, feature_columns, risk_model

def _build_features_for_inference(df: pd.DataFrame, feature_columns: list[str]) -> pd.DataFrame:
    """
    Build/patch columns so they match the training feature set.
    Works for both 'simple' (flow_rate, pressure, motion, gas) and 'full' feature sets.
    """
    df = df.copy()

    if "timestamp" in df.columns and not pd.api.types.is_datetime64_any_dtype(df["timestamp"]):
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")

    # Time-derived features if needed
    if "hour_of_day" in feature_columns:
        df["hour_of_day"] = df["timestamp"].dt.hour if "timestamp" in df.columns else 0
    if "day_of_week" in feature_columns:
        df["day_of_week"] = df["timestamp"].dt.dayofweek if "timestamp" in df.columns else 0
    if "is_weekend" in feature_columns:
        if "day_of_week" not in df.columns:
            df["day_of_week"] = df["timestamp"].dt.dayofweek if "timestamp" in df.columns else 0
        df["is_weekend"] = df["day_of_week"].isin([5, 6]).astype(int)
    if "is_night" in feature_columns:
        if "hour_of_day" not in df.columns:
            df["hour_of_day"] = df["timestamp"].dt.hour if "timestamp" in df.columns else 0
        df["is_night"] = df["hour_of_day"].isin(list(range(0, 6)) + [22, 23]).astype(int)

    # time_since_last_use if needed (approximate per patient)
    if "time_since_last_use" in feature_columns:
        if "patient_id" in df.columns and "timestamp" in df.columns:
            df = df.sort_values(["patient_id", "timestamp"])
            ts_diff = df.groupby("patient_id")["timestamp"].diff().dt.total_seconds() / 3600.0
            df["time_since_last_use"] = ts_diff.fillna(24.0).clip(lower=0.0, upper=168.0)
            df = df.sort_index()
        else:
            df["time_since_last_use"] = 24.0

    # Percent remaining + flags if needed
    if "doses_percent_remaining" in feature_columns:
        base = df.get("doses_left", pd.Series(0, index=df.index))
        df["doses_percent_remaining"] = (base.astype(float) / 200.0 * 100.0).clip(0, 100)
    if "low_dose_warning" in feature_columns:
        df["low_dose_warning"] = (df.get("doses_left", 0).astype(float) < 20).astype(int)
    if "motion_stable" in feature_columns:
        df["motion_stable"] = (df.get("motion", 0).astype(float) < 0.2).astype(int)
    if "gas_normal" in feature_columns:
        df["gas_normal"] = (df.get("gas", 0).astype(float) < 150).astype(int)
    if "pressure_normal" in feature_columns:
        p = df.get("pressure", 0).astype(float)
        df["pressure_normal"] = ((p > 980) & (p < 1050)).astype(int)

    # Severity encoding if needed
    if "severity_encoded" in feature_columns:
        sev_map = {"Mild": 1, "Moderate": 2, "Severe": 3}
        df["severity_encoded"] = df.get("asthma_severity", "").map(sev_map).fillna(2).astype(int)

    # Ensure all required columns exist and are numeric
    for c in feature_columns:
        if c not in df.columns:
            df[c] = 0
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)

    # Final reindex to exact training order
    X = df.reindex(columns=feature_columns)
    return X

def predict_usage(model, feature_columns, usage_df, risk_model=None):
    """
    Returns:
      - correct_prob: np.array of P(correct usage) if model supports predict_proba (else None)
      - y_pred: class predictions (0/1) from classifier
      - risk_pred: optional risk scores (0..1) if risk_model provided; else None
    """
    if model is None or feature_columns is None or usage_df is None or usage_df.empty:
        return None, None, None

    X = _build_features_for_inference(usage_df, feature_columns)

    # Probabilities
    if hasattr(model, "predict_proba"):
        try:
            correct_prob = model.predict_proba(X)[:, 1]
        except Exception:
            correct_prob = None
    else:
        correct_prob = None

    # Class predictions
    try:
        y_pred = model.predict(X)
    except Exception:
        y_pred = None

    # Risk predictions (optional)
    if risk_model is not None:
        try:
            risk_pred = risk_model.predict(X).clip(0, 1)
        except Exception:
            risk_pred = None
    else:
        risk_pred = None

    return correct_prob, y_pred, risk_pred

# ───────────────────────────────────────────────────────────
# Email & PDF helpers
# ───────────────────────────────────────────────────────────
def send_email_report(patient_email, doctor_email, subject, body, pdf_buffer=None):
    try:
        smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
        smtp_port = int(os.getenv("SMTP_PORT", 587))
        smtp_user = os.getenv("SMTP_USER")
        smtp_password = os.getenv("SMTP_PASSWORD")

        msg = MIMEMultipart()
        msg["From"] = smtp_user
        msg["To"] = doctor_email
        msg["Subject"] = subject

        msg.attach(MIMEText(body, "plain"))

        # 📎 Attach PDF
        if pdf_buffer:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(pdf_buffer)
            encoders.encode_base64(part)
            part.add_header("Content-Disposition", "attachment; filename=report.pdf")
            msg.attach(part)

        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.send_message(msg)
        server.quit()

        return True

    except Exception as e:
        st.error(f"Email error: {e}")
        return False

def generate_pdf_report(patient_data, usage_df: pd.DataFrame) -> BytesIO:
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    elements = []
    styles = getSampleStyleSheet()

    # Title
    title = Paragraph(f"<b>Smart Inhaler Report - {patient_data['name']}</b>", styles["Title"])
    elements.append(title)
    elements.append(Spacer(1, 12))

    # Patient info
    info = Paragraph(
        f"Age: {patient_data['age']} | Severity: {patient_data['asthma_severity']}",
        styles["Normal"]
    )
    elements.append(info)
    elements.append(Spacer(1, 12))

    # Usage table
    table_data = [["Timestamp", "Doses Left", "Flow Rate", "Quality"]]
    for _, row in usage_df.head(20).iterrows():
        table_data.append([
            row["timestamp"].strftime("%Y-%m-%d %H:%M:%S"),
            str(row.get("doses_left", "")),
            f"{row.get('flow_rate', 0):.2f}",
            str(row.get("quality", "")),
        ])

    table = Table(table_data)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 12),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 12),
        ("GRID", (0, 0), (-1, -1), 1, colors.black),
    ]))
    elements.append(table)

    doc.build(elements)
    buffer.seek(0)
    return buffer

# ───────────────────────────────────────────────────────────
# UI Pages
# ───────────────────────────────────────────────────────────
def login_page():
    st.title("🫁 Smart Inhaler for Asthma Patients")

    tab1, tab2 = st.tabs(["Login", "Register"])

    # ---------------- LOGIN ----------------
    with tab1:
        st.subheader("Login")
        username = st.text_input("Username", key="login_username")
        password = st.text_input("Password", type="password", key="login_password")

        if st.button("Login", width="stretch"):
            user = authenticate_user(username, password)
            if user:
                st.session_state.logged_in = True
                st.session_state.patient_id = user[0]
                st.session_state.patient_name = user[1]
                st.session_state.onboarded = user[2]
                st.rerun()
            else:
                st.error("Invalid credentials")

    # ---------------- REGISTER ----------------
    with tab2:
        st.subheader("Register New Patient")

        new_username = st.text_input("Username", key="reg_username")
        new_password = st.text_input("Password", type="password", key="reg_password")
        name = st.text_input("Full Name")
        age = st.number_input("Age", min_value=1, max_value=120, value=25)
        asthma_severity = st.selectbox("Asthma Severity", ["Mild", "Moderate", "Severe"])
        doctor_contact = st.text_input("Email")
        doctor_phone = st.text_input("WhatsApp Number (+91...)")

        if st.button("Register", width="stretch"):

            if not (new_username and new_password and name and doctor_contact):
                st.warning("Please fill all fields")
                return

            success = register_user(
                new_username,
                new_password,
                name,
                age,
                asthma_severity,
                doctor_contact,
                doctor_phone
            )

            if success:
                # AUTO LOGIN AFTER REGISTRATION
                user = authenticate_user(new_username, new_password)

                if user:
                    st.success("Registration successful!")

                    st.session_state.logged_in = True
                    st.session_state.patient_id = user[0]
                    st.session_state.patient_name = user[1]
                    st.session_state.onboarded = False  # go to onboarding

                    st.rerun()
                else:
                    st.error("Auto login failed")
            else:
                st.error("Registration failed")

def onboarding_page():
    st.title("Welcome to Smart Inhaler! 🌟")
    st.markdown("""
    ## Understanding Asthma & Your Smart Inhaler

    **What is Asthma?**  
    - Airway inflammation  
    - Bronchoconstriction  
    - Excess mucus  

    **Common Triggers**  
    - Allergens, smoke, pollution, exercise, cold air, stress

    **How Your Smart Inhaler Helps**  
    1. Tracks usage  
    2. Technique quality assessment  
    3. Predictive alerts  
    4. Doctor reports

    **Proper Technique**  
    1. Shake well → breathe out completely  
    2. Mouthpiece in → press → breathe in slowly & deeply  
    3. Hold 10s → breathe out slowly
    """)
    if st.button("Complete Onboarding", use_container_width=True):
        mark_onboarded(st.session_state.patient_id)
        st.session_state.onboarded = True
        st.rerun()

latest = {}
def dashboard():
    latest = {}

    st.title(f"Welcome, {st.session_state.patient_name}! 💨")
    alert_system = AlertSystem()
    placeholder = st.empty()

    if "device_mac" in st.session_state:
        st.success(f"Connected to device: {st.session_state.device_mac}")

    with placeholder.container():
        st.info("Loading dashboard... ⏳")

    # SIDEBAR (UNIFIED)
    with st.sidebar:
        st.header("🔌 Device")

        device_mac = st.text_input(
            "Device MAC",
            value=st.session_state.get("device_mac", "")
        )

        if st.button("Pair Device"):
            if device_mac:
                success = bind_device_to_patient(device_mac, st.session_state.patient_id)

                if success:
                    st.success("Device paired successfully!")

                    #mark onboarding complete
                    mark_onboarded(st.session_state.patient_id)

                    st.session_state.onboarded = True

                    st.session_state.device_mac = device_mac    

                    st.rerun()
                else:
                    st.error("Device pairing failed")

        st.divider()

        use_api = st.toggle("Use Live API (ESP32)", True)
        days_filter = st.selectbox("Time Range", [7, 14, 30, 90], index=2)

        # ✅ SHOW DETECTED MAC (AUTO)
        
        st.divider()


        if st.button("Logout"):
            st.session_state.logged_in = False
            st.rerun()

    # -------------------------
    # LOAD DATA (API / DB)
    # -------------------------
    if use_api:
        try:
            API = "http://localhost:8000"

            with st.spinner("Loading live data... ⏳"):
                latest = requests.get(f"{API}/patient/{st.session_state.patient_id}/latest").json()
                history = requests.get(f"{API}/patient/{st.session_state.patient_id}/history").json()


            usage_df = pd.DataFrame(history)
            usage_df["timestamp"] = pd.to_datetime(usage_df["timestamp"])

            placeholder.empty()

        except:
            placeholder.empty()
            st.error("API not reachable")
            return
    else:
        with st.spinner("Loading database data..."):
            usage_df = get_usage_data(st.session_state.patient_id, days_filter)

        if usage_df.empty:
            placeholder.empty()
            st.warning("No data available")
            return

        latest = usage_df.iloc[0]

        placeholder.empty()

    st.sidebar.text_input(
        "📡 Detected Device MAC",
        value=latest.get("device_id", "Not detected") if isinstance(latest, dict) else "Not detected",
        disabled=True
    )


    # REALTIME AUTO REFRESH (FIXED)
    if "last_timestamp" not in st.session_state:
        st.session_state.last_timestamp = None

    current_time = str(latest.get("timestamp")) if isinstance(latest, dict) else str(latest["timestamp"])

    # ✅ Smart refresh (when new data comes)
    if st.session_state.last_timestamp != current_time:
        st.session_state.last_timestamp = current_time
        st.rerun()
    

    # -------------------------
    # KPI
    # -------------------------
    st.markdown("## 📊 Live Health Overview")

    k1, k2, k3, k4 = st.columns(4)

    k1.metric("💨 Flow Rate", f"{latest['flow_rate']:.1f}")
    k2.metric("🧪 Gas", f"{latest['gas']:.1f}")
    k3.metric("🌡 Temperature", f"{latest['temperature']:.1f}")
    k4.metric("💊 Doses Left", int(latest["doses_left"]))

    # -------------------------
    # ALERTS
    # -------------------------
    st.markdown("## 🚨 Alerts")
    patient = get_patient_data(st.session_state.patient_id)
    
    if latest["gas"] > 60:
        st.error("Dangerous Gas Level!")

        patient = get_patient_data(st.session_state.patient_id)
        with st.spinner("Sending WhatsApp alert... 📱"):
            send_whatsapp_message(
                patient["doctor_phone"],  # doctor's phone number
                f"""
            🚨 Smart Inhaler Alert

            Patient: {patient['name']}
            Gas Level: {latest['gas']}

            Immediate attention required!
            """
        )
    elif latest["gas"] > 30:
        st.warning("Moderate Gas Level")
        
    else:
        st.success("Safe Air Quality")

    if latest["motion"] > 2:
        st.warning("Improper usage detected!")

    patient = get_patient_data(st.session_state.patient_id)

    alert_system.check_and_send_alerts(
        latest_data=latest,
        patient=patient,
        session_state=st.session_state
    )

    # -------------------------
    # GAUGE + DAILY TREND
    # -------------------------
    st.markdown("## 🧪 Air Quality & Usage")

    c1, c2, c3 = st.columns(3)

    with c1:
        fig = go.Figure(go.Indicator(
            mode="gauge+number",
            value=latest["gas"],
            gauge={
                'axis': {'range': [0, 200]},
                'steps': [
                    {'range': [0, 50], 'color': "green"},
                    {'range': [50, 100], 'color': "yellow"},
                    {'range': [100, 200], 'color': "red"}
                ]
            }
        ))
        st.plotly_chart(fig, use_container_width=True)

    with c2:
        daily_counts = usage_df.groupby(usage_df["timestamp"].dt.date).size()
        fig2 = px.line(x=daily_counts.index, y=daily_counts.values)
        st.plotly_chart(fig2, use_container_width=True)

    # -------------------------
    # SENSOR ANALYTICS
    # -------------------------
    st.markdown("## 📈 Sensor Analytics")

    g1, g2 = st.columns(2)

    with g1:
        st.plotly_chart(px.line(usage_df, x="timestamp", y="flow_rate"), use_container_width=True)

    with g2:
        st.plotly_chart(px.line(usage_df, x="timestamp", y="temperature"), use_container_width=True)

    st.plotly_chart(px.line(usage_df, x="timestamp", y="motion"), use_container_width=True)

    # -------------------------
    # AI / ML INSIGHTS
    # -------------------------
    st.markdown("## 🤖 AI Insights")

    model, feature_columns, risk_model = load_ml_artifacts()

    if model:
        correct_prob, y_pred, risk_pred = predict_usage(model, feature_columns, usage_df)

        c1, c2, c3 = st.columns(3)

        with c1:
            if correct_prob is not None:
                st.metric("Correct Usage", f"{np.mean(correct_prob)*100:.1f}%")

        with c2:
            if y_pred is not None:
                st.metric("Predicted Correct", f"{np.mean(y_pred)*100:.1f}%")

        with c3:
            if risk_pred is not None:
                risk = np.mean(risk_pred)
                level = "Low" if risk < 0.3 else "Medium" if risk < 0.7 else "High"
                st.metric("Risk Level", level)

                if level == "High":
                    st.error("⚠️ High risk detected!")

                    alert_system.check_and_send_alerts(
                        latest_data=latest,
                        patient=patient,
                        session_state=st.session_state,
                        risk_level="High"
                    )

    else:
        st.info("ML model not loaded")

    # -------------------------
    # STATS
    # -------------------------
    st.markdown("## 📊 Statistics")

    st.write(f"Total Uses: {len(usage_df)}")
    st.write(f"Avg Flow Rate: {usage_df['flow_rate'].mean():.2f}")
    st.write(f"Doses Remaining: {latest['doses_left']}")

    # -------------------------
    # TABLE
    # -------------------------
    st.markdown("## 📋 Recent Usage")

    st.dataframe(usage_df.head(20), use_container_width=True)

    # -------------------------
    # EXPORT
    # -------------------------
    st.markdown("## 📤 Export & Reports")

    c1, c2, c3 = st.columns(3)

    with c1:
        st.download_button(
            label="📥 Download CSV",
            data=usage_df.to_csv(index=False),
            file_name="inhaler_data.csv",
            mime="text/csv",
            use_container_width=True
        )

    with c2:
        patient = get_patient_data(st.session_state.patient_id)
        
        pdf_buffer = generate_pdf_report(patient, usage_df)

        st.download_button(
            label="📄 Download PDF",
            data=pdf_buffer,
            file_name="inhaler_report.pdf",
            mime="application/pdf",
            use_container_width=True
        )

    with c3:
        if st.button(label="📨 Send Report to Doctor",
                     use_container_width=True):
            with st.spinner("Generating report & sending email... 📄📧"):
                patient = get_patient_data(st.session_state.patient_id)

                pdf_buffer = generate_patient_report(patient, usage_df)

                send_email_report(
                    None,
                    patient.get("doctor_contact"),
                    "Smart Inhaler Full Report",
                    f"""
        Patient Name: {patient['name']}
        Age: {patient['age']}
        Severity: {patient['asthma_severity']}

        Report attached.
        """,
                pdf_buffer
            )

            st.success("Report sent successfully!")
   

# ───────────────────────────────────────────────────────────
# App entry
# ───────────────────────────────────────────────────────────
def main():
    if not st.session_state.logged_in:
        login_page()
    elif not st.session_state.onboarded:
        onboarding_page()
    else:
        dashboard()

if __name__ == "__main__":
    main()
