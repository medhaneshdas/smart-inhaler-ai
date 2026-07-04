/*
 * ═══════════════════════════════════════════════════════════════
 *           SMART INHALER FOR ASTHMA PATIENTS
 *           ESP32 Complete Code with Manual MPU6050
 * ═══════════════════════════════════════════════════════════════
 * 
 * Features:
 * - Manual MPU6050 initialization (more reliable)
 * - BMP180 pressure & temperature sensor
 * - MQ2 gas sensor
 * - WiFi connectivity
 * - REST API data transmission
 * - Audio/Visual feedback
 * - Automatic retry logic
 * - Comprehensive error handling
 * 
 * Hardware Connections:
 * - MPU6050: VCC→3.3V, GND→GND, SDA→GPIO21, SCL→GPIO22
 * - BMP180:  VCC→3.3V, GND→GND, SDA→GPIO21, SCL→GPIO22
 * - MQ2:     VCC→5V, GND→GND, AOUT→GPIO34
 * - Button:  One side→GPIO32, Other side→GND
 * - LED:     Anode→GPIO2, Cathode→GND (through 220Ω resistor)
 * - Buzzer:  Positive→GPIO25, Negative→GND
 * 
 * FIXES APPLIED:
 * - WHO_AM_I check relaxed to accept any non-zero response
 * - Wire.requestFrom() calls explicitly cast to avoid ESP32 overload bug
 * - MPU6050 initialized before BMP180 to avoid I2C bus conflicts
 * - Increased delays for more stable I2C communication
 * - Added WHO_AM_I debug print for easier troubleshooting
 * 
 * Author: Smart Inhaler Team
 * Version: 2.1.0
 * Date: 2025-01-08
 */

#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <Wire.h>
#include <Adafruit_BMP085.h>

// ═══════════════════════════════════════════════════════════════
// CONFIGURATION - UPDATE THESE VALUES
// ═══════════════════════════════════════════════════════════════
const char* WIFI_SSID     = "wifi_name";
const char* WIFI_PASSWORD = "wifi_password";
// Change this to your own FastAPI server address
const char* SERVER_URL = "http://10.x.x.x:8000/inhaler/usage";  // ⚠️ UPDATE WITH YOUR IP

// Hardware Pin Definitions
const int BUZZER_PIN     = 25;
const int MQ2_ANALOG_PIN = 34;
const int BUTTON_PIN     = 32;
const int LED_PIN        = 2;
const int SDA_PIN        = 21;
const int SCL_PIN        = 22;

// MPU6050 I2C Address & Registers
#define MPU6050_ADDR         0x68
#define MPU6050_PWR_MGMT_1   0x6B
#define MPU6050_ACCEL_XOUT_H 0x3B
#define MPU6050_WHO_AM_I     0x75

// ═══════════════════════════════════════════════════════════════
// GLOBAL VARIABLES
// ═══════════════════════════════════════════════════════════════
Adafruit_BMP085 bmp;

int dosesLeft = 100;
bool inhalerUsed = false;
bool mpuAvailable = false;
bool bmpAvailable = false;

unsigned long lastUseTime = 0;
const unsigned long DEBOUNCE_DELAY = 2000; // 2 seconds

// ═══════════════════════════════════════════════════════════════
// FUNCTION DECLARATIONS
// ═══════════════════════════════════════════════════════════════
void connectWiFi();
void scanI2CDevices();
void initSensors();
bool mpu6050_manual_init();
void read_mpu6050_manual(float &motion);
void sendInhalerData();
void sendViaREST(float flowRate, float pressure, float motion, float gas, String quality, float temperature, float humidity);
void provideFeedback(String quality);
void blinkLED(int times, int delayMs = 200);

// ═══════════════════════════════════════════════════════════════
// SETUP
// ═══════════════════════════════════════════════════════════════
void setup() {
  Serial.begin(115200);
  delay(1000);
  
  Serial.println("\n==================================================");
  Serial.println("    SMART INHALER SYSTEM - ESP32 v2.1");
  Serial.println("==================================================\n");

  // Configure Pins
  pinMode(BUZZER_PIN, OUTPUT);
  pinMode(BUTTON_PIN, INPUT_PULLUP);
  pinMode(LED_PIN, OUTPUT);
  pinMode(MQ2_ANALOG_PIN, INPUT);

  // Initial LED blink
  blinkLED(3, 100);

  // ── FIX: Initialize I2C with a clean start and generous settle time ──
  Wire.begin(SDA_PIN, SCL_PIN);
  Wire.setClock(100000); // 100 kHz - slower, more reliable for shared bus
  delay(200);            // Allow all I2C devices to power up fully

  Serial.println("🔍 Scanning I2C Bus...");
  scanI2CDevices();
  
  // ── FIX: initSensors() now initializes MPU6050 FIRST, BMP180 SECOND ──
  Serial.println("\n📡 Initializing Sensors...");
  initSensors();

  Serial.println("\n📶 Connecting to WiFi...");
  connectWiFi();

  Serial.println("\n==================================================");
  Serial.println("✅ SYSTEM READY");
  Serial.println("Press the button to log inhaler usage");
  Serial.println("==================================================\n");
  
  blinkLED(2, 500);
}

// ═══════════════════════════════════════════════════════════════
// MAIN LOOP
// ═══════════════════════════════════════════════════════════════
void loop() {
  // Check WiFi connection
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("⚠️  WiFi disconnected. Reconnecting...");
    connectWiFi();
  }

  // Button press detection with debounce
  if (digitalRead(BUTTON_PIN) == LOW && !inhalerUsed) {
    unsigned long currentTime = millis();
    
    if (currentTime - lastUseTime > DEBOUNCE_DELAY) {
      inhalerUsed = true;
      lastUseTime = currentTime;
      
      digitalWrite(LED_PIN, HIGH);
      Serial.println("\n🔵 BUTTON PRESSED - Recording Usage...\n");
      
      sendInhalerData();
      
      digitalWrite(LED_PIN, LOW);
    }
  }

  // Reset flag when button released
  if (digitalRead(BUTTON_PIN) == HIGH) {
    inhalerUsed = false;
  }

  delay(50);
}

// ═══════════════════════════════════════════════════════════════
// I2C SCANNER
// ═══════════════════════════════════════════════════════════════
void scanI2CDevices() {
  byte error, address;
  int devicesFound = 0;

  Serial.println("Scanning I2C addresses (0x00 - 0x7F)...");
  
  for (address = 1; address < 127; address++) {
    Wire.beginTransmission(address);
    error = Wire.endTransmission();

    if (error == 0) {
      Serial.print("✅ I2C device found at 0x");
      if (address < 16) Serial.print("0");
      Serial.print(address, HEX);
      
      if (address == 0x68 || address == 0x69) Serial.print(" (MPU6050)");
      if (address == 0x77) Serial.print(" (BMP180)");
      
      Serial.println();
      devicesFound++;
    }
  }

  if (devicesFound == 0) {
    Serial.println("❌ No I2C devices found!");
    Serial.println("   Check wiring: SDA→GPIO21, SCL→GPIO22, VCC→3.3V, GND→GND");
  } else {
    Serial.printf("Found %d I2C device(s)\n", devicesFound);
  }
}

// ═══════════════════════════════════════════════════════════════
// MPU6050 MANUAL INITIALIZATION  ← FIXED
// ═══════════════════════════════════════════════════════════════
bool mpu6050_manual_init() {
  // Step 1: Wake up MPU6050 (it starts in sleep mode by default)
  Wire.beginTransmission(MPU6050_ADDR);
  Wire.write(MPU6050_PWR_MGMT_1);
  Wire.write(0x00); // Clear sleep bit → wake up
  byte error = Wire.endTransmission();
  
  if (error != 0) {
    Serial.printf("   I2C transmission error: %d\n", error);
    return false;
  }
  
  // ── FIX: Increased delay from 100ms to 150ms for stable wake-up ──
  delay(150);
  
  // Step 2: Read WHO_AM_I register to verify communication
  Wire.beginTransmission(MPU6050_ADDR);
  Wire.write(MPU6050_WHO_AM_I);
  Wire.endTransmission(false); // Repeated start (don't release bus)
  
  // ── FIX: Explicit uint8_t casts to avoid ESP32 Wire overload ambiguity ──
  Wire.requestFrom((uint8_t)MPU6050_ADDR, (uint8_t)1, (uint8_t)true);
  
  if (Wire.available()) {
    byte whoAmI = Wire.read();
    
    // ── FIX: Print the actual WHO_AM_I value for debugging ──
    Serial.printf("   WHO_AM_I register = 0x%02X\n", whoAmI);
    
    // ── FIX: Accept ANY non-zero response instead of only 0x68/0x72 ──
    // Different MPU6050 chip revisions return different values:
    // 0x68 = standard MPU6050
    // 0x72 = some variants
    // 0x98 = some Chinese clone modules
    // 0x70 = some other variants
    // Checking != 0x00 is safest — if the device responds, it's working.
    if (whoAmI != 0x00) {
      return true;
    } else {
      Serial.println("   WHO_AM_I returned 0x00 — possible wiring issue");
      return false;
    }
  }
  
  Serial.println("   No response from WHO_AM_I register");
  return false;
}

// ═══════════════════════════════════════════════════════════════
// READ MPU6050 MANUALLY  ← FIXED
// ═══════════════════════════════════════════════════════════════
void read_mpu6050_manual(float &motion) {
  Wire.beginTransmission(MPU6050_ADDR);
  Wire.write(MPU6050_ACCEL_XOUT_H);
  Wire.endTransmission(false); // Repeated start

  // ── FIX: Explicit uint8_t casts to avoid ESP32 Wire overload ambiguity ──
  Wire.requestFrom((uint8_t)MPU6050_ADDR, (uint8_t)6, (uint8_t)true);

  // Safety check — ensure we received all 6 bytes
  if (Wire.available() < 6) {
    Serial.println("⚠️  MPU6050 read failed — insufficient bytes received");
    motion = 0.0f;
    return;
  }

  int16_t ax = (Wire.read() << 8) | Wire.read();
  int16_t ay = (Wire.read() << 8) | Wire.read();
  int16_t az = (Wire.read() << 8) | Wire.read();
  
  // Convert to m/s² (scale factor for ±2g range is 16384 LSB/g)
  float ax_ms2 = ax / 16384.0f * 9.81f;
  float ay_ms2 = ay / 16384.0f * 9.81f;
  float az_ms2 = az / 16384.0f * 9.81f;
  
  // Calculate total acceleration magnitude
  float accel_mag = sqrt(ax_ms2 * ax_ms2 + ay_ms2 * ay_ms2 + az_ms2 * az_ms2);
  
  // Motion = deviation from gravity (0 = perfectly still, >0 = moving)
  motion = abs(accel_mag - 9.81f);
}

// ═══════════════════════════════════════════════════════════════
// SENSOR INITIALIZATION  ← FIXED ORDER: MPU6050 FIRST, BMP SECOND
// ═══════════════════════════════════════════════════════════════
void initSensors() {

  // ── FIX: Always initialize MPU6050 FIRST ──
  // BMP180 library does its own I2C operations during begin(),
  // which can interfere if MPU6050 hasn't settled yet.
  Serial.print("Initializing MPU6050 (Manual I2C)... ");
  Serial.println(); // newline so sub-messages appear cleanly below
  
  // ── FIX: Fresh Wire.begin before MPU to reset any stuck I2C state ──
  Wire.begin(SDA_PIN, SCL_PIN);
  Wire.setClock(100000);
  delay(200);
  
  if (mpu6050_manual_init()) {
    Serial.println("✅ MPU6050 OK (Manual Mode)");
    mpuAvailable = true;
  } else {
    Serial.println("❌ MPU6050 NOT FOUND");
    Serial.println("   Possible issues:");
    Serial.println("   1. Wiring: VCC→3.3V (NOT 5V!), GND→GND");
    Serial.println("   2. I2C pins: SDA→GPIO21, SCL→GPIO22");
    Serial.println("   3. Check WHO_AM_I value printed above");
    Serial.println("   4. Try holding AD0 pin LOW (forces address 0x68)");
    Serial.println("   System continues without motion detection");
    mpuAvailable = false;
  }

  // ── FIX: Gap between sensor inits to avoid I2C bus collision ──
  delay(200);

  // BMP180 initialization SECOND
  Serial.print("Initializing BMP180... ");
  if (bmp.begin()) {
    Serial.println("✅ BMP180 OK");
    bmpAvailable = true;
  } else {
    Serial.println("❌ BMP180 NOT FOUND");
    bmpAvailable = false;
  }
}

// ═══════════════════════════════════════════════════════════════
// WIFI CONNECTION
// ═══════════════════════════════════════════════════════════════
void connectWiFi() {
  Serial.printf("Connecting to: %s\n", WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 40) {
    Serial.print(".");
    delay(500);
    attempts++;
  }

  Serial.println();

  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("❌ WiFi Connection FAILED");
    Serial.println("   Check SSID and password");
    blinkLED(5, 100);
    return;
  }

  Serial.println("✅ WiFi Connected!");
  Serial.println("─────────────────────────────────");
  Serial.printf("   IP Address:  %s\n", WiFi.localIP().toString().c_str());
  Serial.printf("   Gateway:     %s\n", WiFi.gatewayIP().toString().c_str());
  Serial.printf("   Subnet:      %s\n", WiFi.subnetMask().toString().c_str());
  Serial.printf("   MAC Address: %s\n", WiFi.macAddress().c_str());
  Serial.printf("   RSSI:        %d dBm\n", WiFi.RSSI());
  Serial.println("─────────────────────────────────");
}

// ═══════════════════════════════════════════════════════════════
// SEND INHALER DATA
// ═══════════════════════════════════════════════════════════════
void sendInhalerData() {
  Serial.println("╔═══════════════════════════════════════════╗");
  Serial.println("║     INHALER USE DETECTED                  ║");
  Serial.println("╚═══════════════════════════════════════════╝");

  // Read Motion (manual I2C if available)
  float motion = 0.0f;
  if (mpuAvailable) {
    read_mpu6050_manual(motion);
    Serial.printf("📊 Motion:      %.2f m/s² (Manual I2C)\n", motion);
  } else {
    motion = 0.2f; // Default low motion value
    Serial.println("📊 Motion:      N/A (sensor offline)");
  }

  // Read Pressure & Temperature (if BMP180 available)
  float pressure    = 0.0f;
  float temperature = 0.0f;
  
  if (bmpAvailable) {
    pressure    = bmp.readPressure() / 100.0f; // Pa → hPa
    temperature = bmp.readTemperature();
    Serial.printf("📊 Pressure:    %.2f hPa\n", pressure);
    Serial.printf("📊 Temperature: %.2f °C\n", temperature);
  } else {
    pressure    = 1013.25f;
    temperature = 22.0f;
    Serial.println("📊 Pressure:    1013.25 hPa (estimated)");
    Serial.println("📊 Temperature: 22.0 °C (estimated)");
  }

  // Read Gas Sensor (MQ2)
  float gasRaw = analogRead(MQ2_ANALOG_PIN);
  float gas    = (gasRaw / 4095.0f) * 500.0f;
  Serial.printf("📊 Gas (MQ2):   %.2f ppm (raw: %.0f)\n", gas, gasRaw);

  // Calculate Flow Rate (simulated based on motion)
  float baseFlow = random(30, 60);
  float flowRate = baseFlow + (motion * 5.0f);
  flowRate = constrain(flowRate, 0.0f, 100.0f);
  Serial.printf("📊 Flow Rate:   %.2f L/min\n", flowRate);

  // Humidity (simulated)
  float humidity = 55.0f + random(-10, 10);
  Serial.printf("📊 Humidity:    %.2f %%\n", humidity);

  // Determine Quality
  String quality;
  if (flowRate > 40 && motion < 0.5 && gas < 150) {
    quality = "Good";
  } else if (flowRate > 30 && motion < 1.0) {
    quality = "Fair";
  } else if (flowRate > 20) {
    quality = "Poor";
  } else {
    quality = "Missed";
  }
  
  Serial.printf("📊 Quality:     %s\n", quality.c_str());
  Serial.printf("📊 Doses Left:  %d\n", dosesLeft);
  Serial.println("───────────────────────────────────────────");

  // Send to server
  sendViaREST(flowRate, pressure, motion, gas, quality, temperature, humidity);

  // Decrease dose counter
  dosesLeft = max(0, dosesLeft - 1);

  // Provide feedback
  provideFeedback(quality);

  Serial.println("╚═══════════════════════════════════════════╝\n");
}

// ═══════════════════════════════════════════════════════════════
// SEND VIA REST API
// ═══════════════════════════════════════════════════════════════
void sendViaREST(float flowRate, float pressure, float motion,
                 float gas, String quality, float temperature, float humidity) {

  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("❌ WiFi not connected. Cannot send data.");
    blinkLED(5, 100);
    return;
  }

  WiFiClient client;
  HTTPClient http;
  http.setTimeout(10000);

  // Build JSON payload
  StaticJsonDocument<768> doc;
  doc["device_id"]   = WiFi.macAddress();
  doc["doses_left"]  = dosesLeft;
  doc["flow_rate"]   = flowRate;
  doc["pressure"]    = pressure;
  doc["quality"]     = quality;
  doc["motion"]      = motion;
  doc["gas"]         = gas;
  doc["temperature"] = temperature;
  doc["humidity"]    = humidity;

  String jsonString;
  serializeJson(doc, jsonString);

  Serial.println("📤 Sending to Server:");
  Serial.println("   URL: " + String(SERVER_URL));
  Serial.println("   Payload: " + jsonString);

  // Retry logic
  const int MAX_RETRIES = 3;
  int attempt  = 0;
  int httpCode = -1;

  while (attempt < MAX_RETRIES) {
    attempt++;
    
    if (!http.begin(client, SERVER_URL)) {
      Serial.println("❌ HTTP connection failed");
      break;
    }

    http.addHeader("Content-Type", "application/json");
    httpCode = http.POST(jsonString);

    if (httpCode > 0) {
      Serial.printf("✅ HTTP Response: %d\n", httpCode);
      
      if (httpCode == 200 || httpCode == 201) {
        String response = http.getString();
        Serial.println("📥 Server Response:");
        Serial.println(response);
        
        // Parse response
        StaticJsonDocument<512> responseDoc;
        DeserializationError error = deserializeJson(responseDoc, response);
        
        if (!error) {
          if (responseDoc.containsKey("usage_id")) {
            int usageId = responseDoc["usage_id"];
            Serial.printf("💾 Usage ID: %d\n", usageId);
          }
        }
        
        blinkLED(2, 200);
        http.end();
        return;
      }
    } else {
      Serial.printf("❌ POST failed (attempt %d/%d): %s\n", 
                    attempt, MAX_RETRIES,
                    http.errorToString(httpCode).c_str());
    }

    http.end();
    
    if (attempt < MAX_RETRIES) {
      Serial.printf("   Retrying in %d seconds...\n", attempt);
      delay(1000 * attempt);
    }
  }

  if (httpCode <= 0) {
    Serial.println("⚠️  All POST attempts failed!");
    Serial.println("   Check:");
    Serial.println("   1. Is FastAPI server running? (python esp32_server.py)");
    Serial.println("   2. Is SERVER_URL correct?");
    Serial.println("   3. Are both on same WiFi network?");
    blinkLED(10, 50);
  }
}

// ═══════════════════════════════════════════════════════════════
// USER FEEDBACK
// ═══════════════════════════════════════════════════════════════
void provideFeedback(String quality) {
  if (quality == "Good") {
    // Good usage: 3 short beeps
    for (int i = 0; i < 3; i++) {
      tone(BUZZER_PIN, 1000, 100);
      delay(150);
    }
    blinkLED(3, 100);
  } 
  else if (quality == "Fair") {
    // Fair usage: 2 medium beeps
    for (int i = 0; i < 2; i++) {
      tone(BUZZER_PIN, 800, 200);
      delay(300);
    }
    blinkLED(2, 300);
  } 
  else {
    // Poor/Missed: 3 long beeps
    for (int i = 0; i < 3; i++) {
      tone(BUZZER_PIN, 500, 400);
      delay(500);
    }
    blinkLED(5, 100);
  }
}

// ═══════════════════════════════════════════════════════════════
// UTILITY FUNCTIONS
// ═══════════════════════════════════════════════════════════════
void blinkLED(int times, int delayMs) {
  for (int i = 0; i < times; i++) {
    digitalWrite(LED_PIN, HIGH);
    delay(delayMs);
    digitalWrite(LED_PIN, LOW);
    delay(delayMs);
  }
}
