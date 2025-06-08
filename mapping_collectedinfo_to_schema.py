import os
import sys
import json
from dotenv import load_dotenv
from google.generativeai import configure, GenerativeModel
from datetime import date, datetime

# Load Gemini API key
load_dotenv()
configure(api_key=os.getenv("GEMINI_API_KEY"))

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
TABLE: symptoms (symptom_id:int, patient_id:int, symptom_description:varchar, severity:varchar, duration:varchar, recorded_at:datetime)
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
        return obj.isoformat()
    raise TypeError(f"Type {type(obj)} not serializable")

def get_mapped_output(input_json):
    """Maps the collected information to the database schema"""
    try:
        patient_data = input_json.get("patient_data", {})
        
        # Convert any date strings to proper format
        if "DOB" in patient_data and patient_data["DOB"]:
            try:
                if isinstance(patient_data["DOB"], str):
                    # Try to parse the date string
                    dob = datetime.strptime(patient_data["DOB"], "%Y-%m-%d").date()
                    patient_data["DOB"] = dob.isoformat()
            except ValueError:
                # If date parsing fails, keep the original string
                pass
        
        # Handle surgery dates if present
        if "previous_surgeries" in patient_data:
            surgeries = patient_data["previous_surgeries"]
            if isinstance(surgeries, list):
                for surgery in surgeries:
                    if isinstance(surgery, dict) and "surgery_date" in surgery:
                        try:
                            if isinstance(surgery["surgery_date"], str):
                                surgery_date = datetime.strptime(surgery["surgery_date"], "%Y-%m-%d").date()
                                surgery["surgery_date"] = surgery_date.isoformat()
                        except ValueError:
                            pass

        # Create the mapped output
        mapped_output = {
            "patient_info": {
                "name": patient_data.get("full_name", ""),
                "email": patient_data.get("email", ""),
                "phone": patient_data.get("phone", ""),
                "dob": patient_data.get("DOB", ""),
                "gender": patient_data.get("gender", ""),
                "address": patient_data.get("address", "")
            },
            "medical_history": {
                "previous_symptoms": patient_data.get("previous_symptoms", []),
                "previous_medications": patient_data.get("previous_medications", []),
                "previous_allergies": patient_data.get("previous_allergies", []),
                "previous_surgeries": patient_data.get("previous_surgeries", [])
            },
            "current_symptoms": patient_data.get("current_symptoms", []),
            "other_concerns": patient_data.get("other_concerns", ""),
            "additional_notes": patient_data.get("additional_notes", ""),
            "status": "mapped"
        }
        
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
    main()
