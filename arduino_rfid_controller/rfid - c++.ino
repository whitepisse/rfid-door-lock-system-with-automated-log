#include <SPI.h>
#include <MFRC522.h>
#include <Wire.h>
#include <LiquidCrystal_I2C.h>


const int SS_PIN = 10;
const int RST_PIN = 9;
const int RELAY_PIN = 7;
int GREEN_PIN = 4;
int RED_PIN = 3;
int YELLOW_PIN = 2;
int SENSOR_PIN = 6;
const int BUZZER_PIN = 5;


MFRC522 rfid(SS_PIN, RST_PIN);
LiquidCrystal_I2C lcd(0x27, 16, 2); 

String lastUID = "";
unsigned long lastPrint = 0;

IR sensor variables
unsigned long unlockStart = 0;
int entryCount = 0;
bool unlocked = false;
bool sensorTriggered = false;
unsigned long lastSensorTime = 0;
const unsigned long SENSOR_DEBOUNCE = 500;

void setup() {
  Serial.begin(115200);
  SPI.begin();
  rfid.PCD_Init();

  pinMode(RELAY_PIN, OUTPUT);
  digitalWrite(RELAY_PIN, LOW);

  pinMode(GREEN_PIN, OUTPUT);
  digitalWrite(GREEN_PIN, LOW);

  pinMode(RED_PIN, OUTPUT);
  digitalWrite(RED_PIN, LOW);

    pinMode(YELLOW_PIN, OUTPUT);
  digitalWrite(YELLOW_PIN, HIGH);

  pinMode(BUZZER_PIN, OUTPUT);
  digitalWrite(BUZZER_PIN, LOW);

  pinMode(SENSOR_PIN, INPUT);

  lcd.init();
  lcd.backlight();
  lcd.clear();
  lcd.setCursor(0,0);
  lcd.print("Please scan your");
  lcd.setCursor(0,1);
  lcd.print("card");

}

String uidToHexString(MFRC522::Uid &uid) {
  String s = "";
  for (byte i = 0; i < uid.size; i++) {
    if (uid.uidByte[i] < 0x10) s += "0";
    s += String(uid.uidByte[i], HEX);
  }
  s.toUpperCase();
  return s;
}

void signalSuccess(int duration=3000) {
  digitalWrite(GREEN_PIN, HIGH);
  delay(500);
  digitalWrite(BUZZER_PIN, LOW);
  digitalWrite(GREEN_PIN, LOW);
  digitalWrite(YELLOW_PIN, HIGH);


 
}

void signalFailure(int duration=300) {
  digitalWrite(BUZZER_PIN, HIGH);
  digitalWrite(RED_PIN, HIGH);
  delay(300);
  digitalWrite(BUZZER_PIN, LOW);
  digitalWrite(RED_PIN, LOW);
  digitalWrite(YELLOW_PIN, HIGH);
}

void handleSerialCommand(String line) {
  line.trim();
  if (line.length() == 0) return;

  if (line.startsWith("STUDENT:")) {
    String payload = line.substring(8);
    int comma = payload.indexOf(',');
    String id = (comma >= 0) ? payload.substring(0, comma) : payload;
    String action = (comma >= 0) ? payload.substring(comma+1) : "";
    id.trim(); action.trim();

    // Display
    lcd.clear();
    lcd.setCursor(0,0);
    lcd.print("Name:"); lcd.print(id);
    lcd.setCursor(0,1);
    if (action.equalsIgnoreCase("IN")) {
      lcd.print("Logged in");
    } else if (action.equalsIgnoreCase("OUT")) {
      lcd.print("Logged out");
    } else {
      lcd.print(action);
    }

    // Unlock door
    unlockStart = millis();
    entryCount = 0;
    unlocked = true;
    sensorTriggered = false;
    digitalWrite(RELAY_PIN, HIGH);
    digitalWrite(BUZZER_PIN, HIGH);
    delay(500);
    digitalWrite(BUZZER_PIN, LOW);
    digitalWrite(GREEN_PIN, HIGH);

    Serial.print("ACK:STUDENT:"); Serial.println(id + "," + action);
  }
  else if (line.startsWith("UID:")) {
    String u = line.substring(4);
    u.trim();
    lcd.clear();
    lcd.setCursor(0,0);
    lcd.print("UID:"); lcd.print(u.substring(0,6));
    lcd.setCursor(0,1);
    lcd.print("Forwarded");
    Serial.print("ACK:UID:"); Serial.println(u);
  }
  else if (line.equalsIgnoreCase("LOCK")) {
    digitalWrite(RELAY_PIN, HIGH);
    lcd.clear();
    lcd.setCursor(0,0);
    lcd.print("UNLOCKED");
    lcd.setCursor(0,1);
    lcd.print("Manual LOCK");
    Serial.println("ACK:LOCK");
  }
  else if (line.equalsIgnoreCase("UNLOCK")) {
    digitalWrite(RELAY_PIN, LOW);
    lcd.clear();
    lcd.setCursor(0,0);
    lcd.print("LOCKED");
    lcd.setCursor(0,1);
    lcd.print("Manual UNLOCK");
    Serial.println("ACK:UNLOCK");
  }
  else if (line.equalsIgnoreCase("FAIL")) {
    signalFailure(300);
    lcd.clear();
    lcd.setCursor(0,0);
    lcd.print("Invalid UID");
    lcd.setCursor(0,1);
    lcd.print("Access Denied");
    Serial.println("ACK:FAIL");
  }
  else {
    Serial.print("ERR:UNKNOWN:"); Serial.println(line);
  }
}

void loop() {
  if (rfid.PICC_IsNewCardPresent() && rfid.PICC_ReadCardSerial()) {
    String u = uidToHexString(rfid.uid);
    if (u.length() > 0) {
      if (u != lastUID || millis() - lastPrint > 1500) {
        lastUID = u;
        lastPrint = millis();

        Serial.print("UID:");
        Serial.println(u);

        lcd.clear();
        lcd.setCursor(0,0);
        lcd.print("Card:");
        lcd.print(u.substring(0,6));
        lcd.setCursor(0,1);
        lcd.print("Sent to host");
      }
    }
    rfid.PICC_HaltA();
    rfid.PCD_StopCrypto1();
  }

  while (Serial.available()) {
    String line = Serial.readStringUntil('\n');
    handleSerialCommand(line);
  }

  if (unlocked) {
    unsigned long now = millis();
    if (now - unlockStart < 5000) {
      int sensorState = digitalRead(SENSOR_PIN);
      if (sensorState == LOW && !sensorTriggered && (now - lastSensorTime > SENSOR_DEBOUNCE)) {
        entryCount++;
        sensorTriggered = true;
        lastSensorTime = now;
        if (entryCount > 1) {
          digitalWrite(BUZZER_PIN, HIGH);
          delay(2000);
          digitalWrite(BUZZER_PIN, LOW);
        }
      } else if (sensorState == HIGH) {
        sensorTriggered = false;
      }
    } else {
      unlocked = false;
      digitalWrite(RELAY_PIN, LOW);
      digitalWrite(GREEN_PIN, LOW);
      digitalWrite(YELLOW_PIN, HIGH);
    }
  }

  delay(10);
}

