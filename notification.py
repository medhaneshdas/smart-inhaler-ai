import os
import smtplib
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart


class NotificationManager:
    def __init__(self):
        self.smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
        self.smtp_port = int(os.getenv("SMTP_PORT", 587))
        self.smtp_user = os.getenv("SMTP_USER")
        self.smtp_password = os.getenv("SMTP_PASSWORD")

    def send_email(self, to_email, subject, message):
        try:
            if not self.smtp_user or not self.smtp_password:
                print("❌ Email config missing")
                return False

            msg = MIMEMultipart()
            msg["From"] = self.smtp_user
            msg["To"] = to_email
            msg["Subject"] = subject
            msg.attach(MIMEText(message, "plain"))

            server = smtplib.SMTP(self.smtp_server, self.smtp_port)
            server.starttls()
            server.login(self.smtp_user, self.smtp_password)
            server.send_message(msg)
            server.quit()

            return True

        except Exception as e:
            print("❌ Email Error:", e)
            return False


# 🔥 SMART ALERT ENGINE
class AlertSystem:
    def __init__(self):
        self.notifier = NotificationManager()

    def should_send_alert(self, session_state, cooldown_minutes=10):
        now = datetime.now()

        if "last_alert_time" not in session_state:
            session_state.last_alert_time = datetime.min

        if now - session_state.last_alert_time > timedelta(minutes=cooldown_minutes):
            session_state.last_alert_time = now
            return True

        return False

    def check_and_send_alerts(self, latest_data, patient, session_state, risk_level=None):
        doctor_email = patient.get("doctor_contact")
        name = patient.get("name")

        # 🚨 GAS ALERT
        if latest_data["gas"] > 100:
            if self.should_send_alert(session_state):
                self.notifier.send_email(
                    doctor_email,
                    "🚨 Emergency Alert - Smart Inhaler",
                    f"Patient {name} exposed to dangerous gas level: {latest_data['gas']}"
                )

        # ⚠️ MOTION ALERT
        if latest_data["motion"] > 2:
            if self.should_send_alert(session_state):
                self.notifier.send_email(
                    doctor_email,
                    "⚠️ Improper Usage Alert",
                    f"Patient {name} is using inhaler incorrectly."
                )

        # 🤖 ML RISK ALERT
        if risk_level == "High":
            if self.should_send_alert(session_state):
                self.notifier.send_email(
                    doctor_email,
                    "🚨 High Risk Alert",
                    f"Patient {name} is at HIGH RISK based on AI prediction."
                )