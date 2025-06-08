import os
import sys
import json
from dotenv import load_dotenv
from google.generativeai import configure, GenerativeModel
from datetime import date, datetime

# Load Gemini API key
load_dotenv()
configure(api_key=os.getenv("GOOGLE_API_KEY"))
model = GenerativeModel("gemini-1.5-flash")

# 1. Load the raw input JSON file
def load_input_json(file_path):
    with open(file_path, "r") as f:
        return json.load(f)

# 2. Define your full DB schema
def get_db_schema_text():
    return """
TABLE: allergies (allergy_id:int, patient_id:int, substance:varchar, severity:varchar)
TABLE: appointments (appointment_id:int, patient_id:int, doctor_id:int, appointment_date:date, appointment_time:time, status:tinyint)
TABLE: doctors (doctor_id:int, full_name:varchar, specialization:varchar, experience_years:int, email:varchar, phone:varchar, hospital_affiliation:varchar, available_days:varchar, available_slots:json)
TABLE: medical_history (history_id:int, patient_id:int, condition:varchar, diagnosis_date:date, notes:text, is_chronic:tinyint)
TABLE: medications (id:int, patient_id:int, medication_name:varchar, dosage:varchar, start_date:date, end_date:date)
TABLE: patients (patient_id:int, full_name:varchar, age:int, gender:varchar, email:varchar, phone:varchar, address:text, DOB:date)
TABLE: surgeries (surgery_id:int, patient_id:int, procedure_name:varchar, surgery_date:date, hospital_name:varchar)
TABLE: symptoms (symptom_id:int, patient_id:int, symptom_description:text, severity:varchar, duration:varchar, recorded_at:datetime)
"""

# 3. Build Gemini-compatible prompt
def build_prompt(raw_data):
    schema = get_db_schema_text()
    return f"""
You are an expert medical data mapper.

Given this database schema:

{schema}

And the following patient intake JSON:

{json.dumps(raw_data, indent=2)}

Map the data to this format, following valid table-column mappings only:

[
  {{
    "table": "patients",
    "columns": {{
      "full_name": "...",
      "age": ...,
      ...
    }}
  }},
  {{
    "table": "symptoms",
    "records": [
      {{
        "symptom_description": "...",
        "severity": "...",
        ...
      }},
      ...
    ]
  }}
]

Skip unrelated or unknown fields. Output valid JSON only.
"""

def date_serializer(obj):
    """Custom JSON serializer for handling dates"""
    if isinstance(obj, (date, datetime)):
        return obj.strftime("%Y-%m-%d")
    raise TypeError(f"Type {type(obj)} not serializable")

def parse_date(date_str):
    """Parse a date string or date object into YYYY-MM-DD format"""
    if isinstance(date_str, (date, datetime)):
        return date_str.strftime("%Y-%m-%d")
    elif isinstance(date_str, str):
        # Try different date formats
        formats = [
            "%Y-%m-%d",
            "%d/%m/%Y",
            "%m/%d/%Y",
            "%Y/%m/%d",
            "%d-%m-%Y",
            "%m-%d-%Y"
        ]
        for fmt in formats:
            try:
                return datetime.strptime(date_str, fmt).strftime("%Y-%m-%d")
            except ValueError:
                continue
        
        # Check if it's a Python date object string representation
        if "datetime.date" in date_str:
            try:
                # Extract year, month, day from string like "datetime.date(2003, 12, 13)"
                parts = date_str.split("(")[1].split(")")[0].split(",")
                year = int(parts[0])
                month = int(parts[1])
                day = int(parts[2])
                return date(year, month, day).strftime("%Y-%m-%d")
            except:
                pass
    return date_str

def summarize_medical_text(text, max_length=200):
    """Use LLM to create a concise medical summary"""
    try:
        if not text or len(str(text)) <= max_length:
            return text
            
        prompt = f"""
Summarize the following medical information concisely (maximum {max_length} characters) while preserving all important medical details:

{text}

Keep it professional and medically accurate. Include key symptoms, severity, and duration if mentioned.
"""
        response = model.generate_content(prompt)
        summary = response.text.strip()
        return summary[:max_length]
    except Exception as e:
        print(f"Warning: Error summarizing text: {str(e)}")
        return str(text)[:max_length]

def get_mapped_output(input_json):
    """Maps the collected information to the database schema"""
    try:
        patient_data = input_json.get("patient_data", {})
        mapped_output = []
        
        # Handle patient data
        patient_columns = {
            "full_name": patient_data.get("full_name", ""),
            "email": patient_data.get("email", ""),
            "phone": patient_data.get("phone", ""),
            "DOB": patient_data.get("DOB", ""),
            "gender": patient_data.get("gender", ""),
            "address": patient_data.get("address", "")
        }
        # Remove empty values
        patient_columns = {k: v for k, v in patient_columns.items() if v}
        if patient_columns:
            mapped_output.append({
                "table": "patients",
                "columns": patient_columns
            })

        # Handle symptoms
        symptoms_records = []
        
        # Process current symptoms
        current_symptoms = patient_data.get("current_symptoms", [])
        if isinstance(current_symptoms, list):
            for symptom in current_symptoms:
                if isinstance(symptom, dict):
                    symptoms_records.append({
                        "symptom_description": summarize_medical_text(symptom.get("description", "not specified")),
                        "severity": symptom.get("severity", "not specified"),
                        "duration": symptom.get("duration", "not specified")
                    })
                else:
                    symptoms_records.append({
                        "symptom_description": summarize_medical_text(str(symptom)),
                        "severity": "not specified",
                        "duration": "not specified"
                    })
        elif current_symptoms:  # Handle string input
            symptoms_records.append({
                "symptom_description": summarize_medical_text(str(current_symptoms)),
                "severity": "not specified",
                "duration": "not specified"
            })

        # Add specialist recommendations
        if "specialist_recommendations" in input_json:
            recommendations = input_json["specialist_recommendations"]
            specialists = recommendations.get("specialists", [])
            rationale = recommendations.get("rationale", "")
            if specialists or rationale:
                notes = []
                if specialists:
                    notes.append("Recommended Specialists:")
                    notes.extend([f"- {s}" for s in specialists[:3]])  # Limit to top 3 specialists
                if rationale:
                    notes.append("Rationale:")
                    notes.append(summarize_medical_text(rationale, 150))  # Shorter summary for rationale
                symptoms_records.append({
                    "symptom_description": summarize_medical_text("\n".join(notes)),
                    "severity": "info",
                    "duration": "N/A"
                })

        # Add appointment and doctor details
        if "selected_doctor" in patient_data and "appointment" in patient_data:
            doctor = patient_data["selected_doctor"]
            appt = patient_data["appointment"]
            
            # Add appointment record
            mapped_output.append({
                "table": "appointments",
                "columns": {
                    "doctor_id": doctor.get("doctor_id"),
                    "appointment_date": appt.get("date"),
                    "appointment_time": appt.get("time"),
                    "status": 1  # 1 for scheduled
                }
            })
            
            # Add appointment notes to symptoms
            appt_notes = [
                "Appointment Details:",
                f"Doctor: Dr. {doctor.get('name', '')}",
                f"Specialization: {doctor.get('specialization', '')}",
                f"Hospital: {doctor.get('hospital', '')}",
                f"Date: {appt.get('date', '')}",
                f"Time: {appt.get('time', '')}"
            ]
            symptoms_records.append({
                "symptom_description": summarize_medical_text("\n".join(appt_notes)),
                "severity": "info",
                "duration": "N/A"
            })

        # Add symptoms records if any exist
        if symptoms_records:
            mapped_output.append({
                "table": "symptoms",
                "records": symptoms_records
            })

        return mapped_output
    except Exception as e:
        raise Exception(f"Error mapping data: {str(e)}")

# 5. Main driver
def main():
    if len(sys.argv) < 2:
        print(" Please provide the input JSON file as an argument.")
        print(" Example: python mapping.py final_patient_summary.json")
        return

    input_file = sys.argv[1]
    output_file = "mapped_output.json"

    try:
        raw_data = load_input_json(input_file)
    except FileNotFoundError:
        print(f" File not found: {input_file}")
        return
    except json.JSONDecodeError as e:
        print(f" Invalid JSON in input file: {str(e)}")
        return

    print(" Sending data to Gemini for mapping...")
    mapped_data = get_mapped_output(raw_data)

    if not mapped_data:
        print(" ❌ No valid mapped data generated")
        return

    try:
        with open(output_file, "w") as f:
            json.dump(mapped_data, f, indent=2)
        print(f" ✅ Mapped output saved to: {output_file}")
        print(f" 📝 Generated {len(mapped_data)} table mappings")
    except Exception as e:
        print(f" ❌ Error saving mapped output: {str(e)}")

if __name__ == "__main__":
    # Test the mapping
    test_input = {
        "patient_data": {
            "full_name": "Test Patient",
            "DOB": "datetime.date(2003, 12, 13)",
            "email": "test@example.com"
        }
    }
    result = get_mapped_output(test_input)
    print(json.dumps(result, indent=2, default=date_serializer))
