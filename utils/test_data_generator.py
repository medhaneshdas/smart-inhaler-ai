"""
Test Data Generator for Smart Inhaler System
Generates synthetic inhaler usage data for testing and demonstration
"""

import requests
import random
import time
from datetime import datetime, timedelta
import json

# Configuration
API_URL = "http://localhost:8000/inhaler/usage"
PATIENT_ID = 1
NUM_RECORDS = 50
DELAY_BETWEEN_REQUESTS = 0.5  # seconds

def generate_inhaler_data():
    """Generate realistic synthetic inhaler usage data"""
    
    # Realistic ranges for sensor values
    flow_rate = random.uniform(25.0, 75.0)  # L/min
    pressure = random.uniform(1000.0, 1020.0)  # hPa
    motion = random.uniform(0.05, 0.8)  # m/s²
    gas = random.uniform(80.0, 180.0)  # ppm
    temperature = random.uniform(18.0, 28.0)  # °C
    
    # Determine quality based on sensor readings
    if flow_rate > 45 and motion < 0.3 and gas < 140:
        quality = "Good"
    elif flow_rate > 35 and motion < 0.5:
        quality = "Fair"
    elif flow_rate > 25:
        quality = "Poor"
    else:
        quality = "Missed"
    
    # Generate timestamp (random time in last 30 days)
    days_ago = random.randint(0, 30)
    hours_ago = random.randint(0, 23)
    timestamp = datetime.now() - timedelta(days=days_ago, hours=hours_ago)
    
    return {
        "patient_id": PATIENT_ID,
        "timestamp": timestamp.isoformat(),
        "doses_left": random.randint(20, 100),
        "flow_rate": round(flow_rate, 2),
        "pressure": round(pressure, 2),
        "quality": quality,
        "motion": round(motion, 3),
        "gas": round(gas, 2),
        "temperature": round(temperature, 1)
    }

def send_data(data):
    """Send data to FastAPI server"""
    try:
        response = requests.post(API_URL, json=data, timeout=5)
        if response.status_code == 200:
            print(f"✅ Record {data['timestamp'][:19]} - Quality: {data['quality']}")
            return True
        else:
            print(f"❌ Error {response.status_code}: {response.text}")
            return False
    except requests.exceptions.ConnectionError:
        print("❌ Connection error. Is the server running?")
        return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

def main():
    """Main execution"""
    print("=" * 60)
    print("Smart Inhaler Test Data Generator")
    print("=" * 60)
    print(f"Generating {NUM_RECORDS} records for Patient ID: {PATIENT_ID}")
    print(f"Target API: {API_URL}")
    print("=" * 60)
    print()
    
    successful = 0
    failed = 0
    
    for i in range(NUM_RECORDS):
        data = generate_inhaler_data()
        
        if send_data(data):
            successful += 1
        else:
            failed += 1
        
        time.sleep(DELAY_BETWEEN_REQUESTS)
    
    print()
    print("=" * 60)
    print(f"Generation Complete!")
    print(f"✅ Successful: {successful}")
    print(f"❌ Failed: {failed}")
    print("=" * 60)
    
    # Save sample data to JSON file
    sample_data = [generate_inhaler_data() for _ in range(10)]
    with open('sample_data.json', 'w') as f:
        json.dump(sample_data, f, indent=2)
    print("\n📁 Sample data saved to: sample_data.json")

if __name__ == "__main__":
    main()