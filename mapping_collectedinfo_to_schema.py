import os
import sys
import json
from dotenv import load_dotenv
from google.generativeai import configure, GenerativeModel

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

# 4. Call Gemini
def get_mapped_output(raw_data):
    prompt = build_prompt(raw_data)
    model = GenerativeModel("gemini-1.5-flash")
    response = model.generate_content(prompt)

    content = response.text.strip()

    # Remove markdown code block markers if present
    if content.startswith("```"):
        content = content.split("```")[1].strip()
        if content.startswith("json"):
            content = content[len("json"):].strip()
    return content

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

    print(" Sending data to Gemini for mapping...")
    mapped_json_str = get_mapped_output(raw_data)

    try:
        mapped_json = json.loads(mapped_json_str)
    except json.JSONDecodeError:
        print(" LLM response is not valid JSON. Here's the raw text:")
        print(mapped_json_str)
        return

    with open(output_file, "w") as f:
        json.dump(mapped_json, f, indent=2)

    print(f" Mapped output saved to: {output_file}")

if __name__ == "__main__":
    main()
