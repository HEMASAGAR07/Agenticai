import pymysql
from datetime import datetime, timedelta
import json
from dotenv import load_dotenv
import os

load_dotenv()

db_config = {
    "host": os.getenv("DB_HOST"),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
    "database": os.getenv("DB_NAME"),
    "port": int(os.getenv("DB_PORT", 3306))
}

def parse_available_days(days_str):
    days_str = days_str.strip().lower()
    day_map = {
        "mon": "Monday",
        "tue": "Tuesday",
        "wed": "Wednesday",
        "thu": "Thursday",
        "fri": "Friday",
        "sat": "Saturday",
        "sun": "Sunday"
    }
    if "-" in days_str:
        start, end = [d.strip() for d in days_str.split("-")]
        keys = list(day_map.keys())
        start_idx = keys.index(start)
        end_idx = keys.index(end)
        if end_idx < start_idx:
            end_idx += 7
        result = []
        for i in range(start_idx, end_idx + 1):
            key = keys[i % 7]
            result.append(day_map[key])
        return result
    else:
        parts = [d.strip() for d in days_str.split(",")]
        return [day_map.get(p, "") for p in parts if p in day_map]

def get_patient_id_by_email(cursor, email):
    cursor.execute("SELECT patient_id FROM patients WHERE email = %s", (email,))
    result = cursor.fetchone()
    return result['patient_id'] if result else None

def book_appointment_from_json(json_file_path="final_patient_summary.json"):
    with open(json_file_path) as f:
        data = json.load(f)

    recommended_specialists = data.get("recommended_specialist", [])
    patient_email = data["patient_data"].get("email")

    if not patient_email:
        raise ValueError("Patient email not found in JSON.")

    conn = pymysql.connect(**db_config)
    cursor = conn.cursor()

    try:
        patient_id = get_patient_id_by_email(cursor, patient_email)
        if not patient_id:
            raise ValueError(f"Patient with email {patient_email} not found in database.")

        for specialist in recommended_specialists:
            cursor.execute("SELECT * FROM doctors WHERE specialization = %s", (specialist,))
            doctors = cursor.fetchall()
            if not doctors:
                continue

            for doctor in doctors:
                available_days = parse_available_days(doctor["available_days"])
                try:
                    available_slots = json.loads(doctor["available_slots"])
                except Exception as e:
                    continue

                for i in range(7):
                    check_date = datetime.today() + timedelta(days=i)
                    weekday = check_date.strftime('%A')

                    if weekday in available_days:
                        for slot in available_slots:
                            slot_time = slot if len(slot) == 8 else slot + ":00"

                            cursor.execute("""
                                SELECT 1 FROM appointments
                                WHERE doctor_id = %s AND appointment_date = %s AND appointment_time = %s
                            """, (doctor["doctor_id"], check_date.date(), slot_time))

                            if not cursor.fetchone():
                                cursor.execute("""
                                    INSERT INTO appointments 
                                    (patient_id, doctor_id, appointment_date, appointment_time, status)
                                    VALUES (%s, %s, %s, %s, %s)
                                """, (
                                    patient_id, doctor["doctor_id"], check_date.date(), slot_time, 1
                                ))
                                conn.commit()
                                return f"Appointment booked with Dr. {doctor['full_name']} on {check_date.date()} at {slot_time}"
        return "No available slots found for any recommended specialist in the next 7 days."
    finally:
        cursor.close()
        conn.close()

# Only run main if script is run directly
if _name_ == "_main_":
    print(book_appointment_from_json())
