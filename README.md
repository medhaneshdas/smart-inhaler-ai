# Smart Inhaler AI

An IoT-based Smart Inhaler system that combines **ESP32**, **FastAPI**, **PostgreSQL**, **Machine Learning**, and **Streamlit** to monitor inhaler usage, analyze patient data, and provide real-time insights for asthma management.

---

## Project Overview

Smart Inhaler AI is designed to improve asthma management by collecting sensor data from an ESP32-powered inhaler, storing the data in a PostgreSQL database, and using Machine Learning to assess inhaler usage quality and potential health risks. A Streamlit dashboard enables healthcare providers and patients to monitor inhaler usage, visualize historical trends, and generate reports.

---

## Features

* Real-time inhaler usage monitoring
* ESP32-based IoT device integration
* FastAPI REST API for data communication
* PostgreSQL database for secure data storage
* Machine Learning-based risk prediction
* Interactive Streamlit dashboard
* Patient usage history visualization
* PDF report generation
* WhatsApp notification support
* Sensor-based health monitoring

---

## System Architecture

```text
ESP32 Smart Inhaler
        │
        ▼
 FastAPI REST API
        │
        ▼
 PostgreSQL Database
        │
        ▼
 Machine Learning Model
        │
        ▼
 Streamlit Dashboard
        │
        ├── Patient Monitoring
        ├── Data Visualization
        ├── Risk Prediction
        ├── PDF Reports
        └── WhatsApp Notifications
```

---

## Hardware Components

* ESP32 DevKit V1
* MPU6050 Motion Sensor
* BMP180 Pressure Sensor
* MQ-2 Gas Sensor
* HW611 Sensor

---

## Software Stack

### Frontend

* Streamlit

### Backend

* Python
* FastAPI

### Database

* PostgreSQL

### Machine Learning

* Scikit-Learn
* Joblib

### Communication

* REST API
* Wi-Fi

### Notifications

* Twilio WhatsApp API
* SMTP Email Notifications

---

## Project Structure

```text
smart-inhaler-ai/

├── app.py
├── esp32_server.py
├── exporter.py
├── notification.py
├── whatsapp.py
├── requirements.txt
├── setup.sh
├── README.md
├── .env.example
├── .gitignore
│
├── arduino/
│   └── esp32_smart_inhaler/
│       └── esp32_smart_inhaler.ino
│
├── database/
│   ├── db_utils.py
│   └── schema.sql
│
├── ml_model/
│   ├── train_model.py
│   ├── model.pkl
│   ├── risk_model.pkl
│   └── feature_columns.pkl
│
└── utils/
    └── test_data_generator.py
```

---

# Installation and Setup

## 1. Clone the Repository

```bash
git clone https://github.com/medhaneshdas/smart-inhaler-ai.git

cd smart-inhaler-ai
```

---

## 2. Create a Virtual Environment

```bash
python -m venv venv
```

---

## 3. Activate the Virtual Environment

### Windows

```bash
venv\Scripts\activate
```

### Linux / macOS

```bash
source venv/bin/activate
```

---

## 4. Install Dependencies

```bash
pip install -r requirements.txt
```

---

# Environment Variables

Create a `.env` file in the project root.

Example:

```env
# PostgreSQL
DATABASE_URL=postgresql://postgres:YOUR_PASSWORD@localhost:5432/smart_inhaler

# Twilio WhatsApp
TWILIO_ACCOUNT_SID=YOUR_TWILIO_ACCOUNT_SID
TWILIO_AUTH_TOKEN=YOUR_TWILIO_AUTH_TOKEN
TWILIO_PHONE_NUMBER=YOUR_TWILIO_PHONE_NUMBER

# Email (SMTP)
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=YOUR_EMAIL@gmail.com
SMTP_PASSWORD=YOUR_GMAIL_APP_PASSWORD
```

> **Important**
>
> * Never upload your `.env` file to GitHub.
> * Replace all placeholder values with your own credentials.
> * Use a Gmail **App Password** instead of your normal Gmail password.

---

# Database Setup

Create a PostgreSQL database named:

```text
smart_inhaler
```

Execute the SQL schema to create the required tables.

Using **psql**:

```bash
psql -U postgres -d smart_inhaler -f database/schema.sql
```

Or execute `database/schema.sql` using **pgAdmin** or any PostgreSQL client.

---

## Twilio WhatsApp Setup

This project supports WhatsApp notifications using the Twilio WhatsApp API.

### Step 1: Create a Twilio Account

1. Sign up for a Twilio account.
2. Verify your phone number.
3. Enable the Twilio WhatsApp Sandbox (or configure a production WhatsApp sender).

### Step 2: Get Your Credentials

From your Twilio Console, obtain:

* Account SID
* Auth Token
* Twilio WhatsApp Number (or Sandbox Number)

### Step 3: Configure the `.env` File

```env
TWILIO_ACCOUNT_SID=YOUR_TWILIO_ACCOUNT_SID
TWILIO_AUTH_TOKEN=YOUR_TWILIO_AUTH_TOKEN
TWILIO_PHONE_NUMBER=whatsapp:+14155238886
```

Replace the placeholder values with your own Twilio credentials.

### Step 4: Install the Required Package

```bash
pip install twilio
```

### Step 5: Sending a WhatsApp Message

```python
from twilio.rest import Client
import os

client = Client(
    os.getenv("TWILIO_ACCOUNT_SID"),
    os.getenv("TWILIO_AUTH_TOKEN")
)

message = client.messages.create(
    from_=os.getenv("TWILIO_PHONE_NUMBER"),
    body="Smart Inhaler Alert: Patient requires attention.",
    to="whatsapp:+91XXXXXXXXXX"
)

print(message.sid)
```

### Notes

* Phone numbers must include the country code.
* For the Twilio Sandbox, the recipient must first join the sandbox.
* Never hardcode Twilio credentials inside your Python source code.
* Store all credentials in the `.env` file.


# Train the Machine Learning Models

Before running the application, generate the trained Machine Learning models.

Run:

```bash
python ml_model/train_model.py
```

This generates the following files inside the `ml_model` directory:

* `model.pkl`
* `risk_model.pkl`
* `feature_columns.pkl`

These files are required before starting the application.

---

# Configure the ESP32

Open:

```text
arduino/esp32_smart_inhaler/esp32_smart_inhaler.ino
```

Update the following values:

* Wi-Fi SSID
* Wi-Fi Password
* FastAPI Server URL

Example:

```cpp
const char* ssid = "YOUR_WIFI_NAME";
const char* password = "YOUR_WIFI_PASSWORD";

const char* SERVER_URL = "http://YOUR_SERVER_IP:8000/inhaler/usage";
```

Upload the sketch to the ESP32 using the Arduino IDE.

---

# Run the Application

## Start the FastAPI Server

```bash
python esp32_server.py
```

The FastAPI server receives sensor data from the ESP32 and stores it in PostgreSQL.

---

## Start the Streamlit Dashboard

Open a new terminal and run:

```bash
streamlit run app.py
```

---

# Project Execution Order

Follow these steps in order:

1. Clone the repository.
2. Install Python dependencies.
3. Create the `.env` file.
4. Create the PostgreSQL database.
5. Execute `database/schema.sql`.
6. Run `python ml_model/train_model.py`.
7. Configure and upload the Arduino code to the ESP32.
8. Start the FastAPI server.
9. Launch the Streamlit dashboard.
10. Power on the ESP32 to begin sending live sensor data.

---

## Machine Learning

The project uses Scikit-Learn models to:

* Predict inhaler usage quality
* Analyze sensor readings
* Estimate patient risk
* Support healthcare monitoring

---

## Database

The application stores:

* Patient information
* Sensor readings
* Inhaler usage history
* Machine Learning predictions
* Timestamped records

---

## Future Improvements

* TinyML deployment on ESP32
* MQTT communication
* BLE support
* Mobile application
* Doctor portal
* Cloud deployment
* AI-powered health recommendations

---

## Skills Demonstrated

* Internet of Things (IoT)
* Embedded Systems
* Python Development
* FastAPI
* REST API Development
* PostgreSQL
* Streamlit
* Machine Learning
* Scikit-Learn
* Data Visualization
* Sensor Integration
* Healthcare Analytics

---

## Author

**Dhanesh Das**

Aspiring AI Engineer | Machine Learning Enthusiast | IoT Developer

**GitHub:** https://github.com/medhaneshdas

---

## License

This project is licensed under the MIT License.
