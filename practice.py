import os
import json
import streamlit as st
from dotenv import load_dotenv
import google.generativeai as genai
import mapping_collectedinfo_to_schema  # <-- Add this import at the top
import mysql.connector
import subprocess
import pymysql
from inserting_JSON_to_DB import db_config,insert_data_from_mapped_json
from booking import book_appointment_from_json



# Load environment variables
load_dotenv()
api_key = os.getenv("GOOGLE_API_KEY")
if not api_key:
    raise ValueError("Missing API key. Set GOOGLE_API_KEY in .env")

# Initialize Gemini model
genai.configure(api_key=api_key)
model = genai.GenerativeModel("gemini-1.5-flash")


# Extract JSON from model response
def extract_json(text):
    try:
        start = text.find('{')
        end = text.rfind('}') + 1
        if start != -1 and end != -1:
            return json.loads(text[start:end])
    except Exception as e:
        st.error(f"❌ JSON Parsing error: {e}")
    return {}


def dynamic_medical_intake():
    # Using session state to store conversation & patient_data across reruns
    if "intake_history" not in st.session_state:
        st.session_state.intake_history = []
    if "intake_response" not in st.session_state:
        st.session_state.intake_response = None
    if "patient_data" not in st.session_state:
        st.session_state.patient_data = {}

    if st.session_state.intake_response is None:
        intro = """
You are an intelligent medical intake assistant.

Your job is to collect all necessary health details step-by-step, one question at a time. You must also evaluate each answer and ensure it's valid.

🔍 Your behavior should follow these rules:
- Do NOT ask all questions upfront.
- Do not accept fake, placeholder, or gibberish data. For example:
  - Invalid phone numbers like "1234567891" or too short.
  - Invalid or misspelled emails like "abc@gamial.com".
  - Unrealistic names (e.g., "asd asd", "xxx").
  - Empty strings or nonsense entries (e.g., "bal bala", "asdf").

- Ask only 1 question at a time.
- Decide the next question based on prior answers.
- SKIP irrelevant questions automatically.
- STOP when you've collected enough (not too much, not too little).
- Validate each patient response for correctness.
  - If answer is unclear, nonsense (e.g., "bal bala"), irrelevant, or incomplete, re-ask or prompt the user to clarify.
  - Examples of bad answers: gibberish, unknown terms, contradictions, wrong formats.
  - Politely ask them to rephrase or clarify only when needed.

⚠️ IMPORTANT: Be sure to cover all these critical areas during the intake:
- Patient's name , patient email
- Current symptoms and complaints
- Past medical history including any surgeries or hospitalizations
- Current medications the patient is taking
- Family medical history if relevant
- Lifestyle factors if relevant (e.g., smoking, alcohol)

📝 Your final output should ONLY be a JSON object like:
{
  "summary": "Short summary of findings",
  "patient_data": {
    "name": "Alice",
    "age": 34,
    "email": "G2JlB@example.com",
    "gender": "Female",
    "symptoms": "...",
    "past_surgeries": "...",
    "current_medications": "...",
    "allergies": "...",
    ...
  },
  "status": "complete"
}

Now begin by asking the first question to the patient.
"""
        st.session_state.intake_response = model.start_chat(history=[])
        reply = st.session_state.intake_response.send_message(
            intro + "\n\nStart by asking the first question to the patient.")
        st.session_state.intake_history.append(("bot", reply.text.strip()))
    else:
        reply = st.session_state.intake_response

    st.write(f" {st.session_state.intake_history[-1][1]}")

    user_input = st.text_input("Your answer here:", key="intake_input")
    submit = st.button("Submit answer", key="intake_submit")

    if submit and user_input:
        st.session_state.intake_history.append(("user", user_input))
        reply = st.session_state.intake_response.send_message(user_input)
        st.session_state.intake_history.append(("bot", reply.text.strip()))

        # Check if final JSON with status complete
        final_output = extract_json(reply.text)
        if final_output.get("status") == "complete":
            st.session_state.patient_data = final_output.get("patient_data", {})
            summary = final_output.get("summary", "")
            st.success(" Initial intake complete.")
            return st.session_state.patient_data, summary, True
        else:
            # Continue intake
            st.rerun()

    return {}, "", False


def post_analysis_and_followup(patient_data):
    if "followup_history" not in st.session_state:
        st.session_state.followup_history = []
    if "followup_response" not in st.session_state:
        prompt = f"""
You are a medical assistant reviewing the following patient data:

{json.dumps(patient_data, indent=2)}

🎯 TASK:
- Carefully analyze the above patient data.
- Identify if any critical required medical details are missing, inconsistent, or unclear.
- Do NOT ask unnecessary or overly detailed questions.
- Ask only essential follow-up questions one at a time to complete missing key information.
- If the data is sufficient and complete for medical intake purposes, return a JSON with status: "finalized".
- After collecting all required info, return JSON like:
{{
  "updated_patient_data": {{ ... }},
  "notes": "Summary of what was added or clarified",
  "status": "finalized"
}}

Begin your focused analysis now.
"""
        st.session_state.followup_response = model.start_chat(history=[])
        reply = st.session_state.followup_response.send_message(prompt)
        st.session_state.followup_history = [("bot", reply.text.strip())]
        st.session_state.updated_data = dict(patient_data)  # clone
    else:
        reply = st.session_state.followup_response

    if st.session_state.followup_history:
        st.write(f" {st.session_state.followup_history[-1][1]}")
    else:
        st.write("No follow-up history available.")

    user_input = st.text_input("Your answer here:", key="followup_input")
    submit = st.button("Submit follow-up answer", key="followup_submit")

    if submit and user_input:
        st.session_state.followup_history.append(("user", user_input))
        reply = st.session_state.followup_response.send_message(user_input)
        st.session_state.followup_history.append(("bot", reply.text.strip()))

        # Check for finalized status
        result = extract_json(reply.text)
        if result.get("status") == "finalized":
            return result.get("updated_patient_data", st.session_state.get("updated_data", {})), result.get("notes", ""), True
        else:
            st.rerun()

    return patient_data, "", False


def recommend_specialist(patient_data):
    prompt = f"""
You are a medical triage assistant.

Based on the following patient data, recommend the most appropriate medical specialist(s) for consultation.

Patient data:
{json.dumps(patient_data, indent=2)}

Instructions:
- Analyze symptoms, medical history, medications, allergies, and other relevant information.
- Recommend 1 or more specialist types (e.g., Cardiologist, Neurologist, Dermatologist, Orthopedic Surgeon, etc.)
- Provide a brief rationale for the recommendation.
- Return ONLY a JSON object with this format:

{{
  "recommended_specialist": ["Specialist Name 1", "Specialist Name 2"],
  "rationale": "Short explanation why these specialists are recommended.",
  "status": "done"
}}
"""
    response = model.start_chat(history=[])
    reply = response.send_message(prompt)

    for _ in range(3):
        result = extract_json(reply.text)
        if result.get("status") == "done":
            return result.get("recommended_specialist", []), result.get("rationale", "")
        else:
            break

    st.warning(" Specialist recommendation not found in LLM response.")
    st.write(reply.text)
    return [], ""


def confirm_mandatory_fields(final_json):
    if "confirm_response" not in st.session_state:
        prompt = f"""
You are a medical assistant. 

Given the patient data JSON below, check if ALL mandatory fields are present.

Mandatory fields:

- From Patient: "name" (maps to full_name), "email", "age", "gender", "Ph Number" (phone), "Address" (address)
- If "symptoms" == "yes": "symptom_list" required (comma-separated string)
- If "allergies" == "yes": "allergy_list" required
- If "medications" == "yes": "medication_list" required
- If "past_history" == "yes": "past_illness" required
- If surgery info present: "procedure_name", "surgery_date", "hospital_name" required

If any mandatory fields are missing or empty, ask the patient directly to provide them one by one.

If all mandatory fields are present, reply with:

{{"status": "confirmed", "message": "All mandatory fields present."}}

Otherwise, ask only for missing fields one at a time.

Here is the patient data:

{json.dumps(final_json, indent=2)}

Begin your check and ask for missing info as needed.
"""
        st.session_state.confirm_response = model.start_chat(history=[])
        reply = st.session_state.confirm_response.send_message(prompt)
        st.session_state.confirm_history = [("bot", reply.text.strip())]
        st.session_state.updated_final_data = dict(final_json)  # copy original data
    else:
        reply = st.session_state.confirm_response

    st.write(f" {st.session_state.confirm_history[-1][1]}")
    user_input = st.text_input("Your answer here:", key="confirm_input")
    submit = st.button("Submit mandatory info answer", key="confirm_submit")

    if submit and user_input:
        st.session_state.confirm_history.append(("user", user_input))
        # Heuristic to detect requested field from last bot message
        last_bot_msg = st.session_state.confirm_history[-1][1].lower()
        u_input = user_input.strip()
        d = st.session_state.updated_final_data.get("patient_data", {})

        if "name" in last_bot_msg:
            d["name"] = u_input
        elif "email" in last_bot_msg:
            d["email"] = u_input
        elif "age" in last_bot_msg:
            try:
                d["age"] = int(u_input)
            except:
                d["age"] = u_input
        elif "gender" in last_bot_msg:
            d["gender"] = u_input
        elif "phone" in last_bot_msg or "ph number" in last_bot_msg:
            d["phone"] = u_input
        elif "address" in last_bot_msg:
            d["address"] = u_input
        elif "symptom" in last_bot_msg:
            d["symptom_list"] = u_input
            d["symptoms"] = "yes"
        elif "allergy" in last_bot_msg:
            d["allergy_list"] = u_input
            d["allergies"] = "yes"
        elif "medication" in last_bot_msg:
            d["medication_list"] = u_input
            d["medications"] = "yes"
        elif "past illness" in last_bot_msg or "past history" in last_bot_msg:
            d["past_illness"] = u_input
            d["past_history"] = "yes"
        elif "procedure name" in last_bot_msg:
            d["procedure_name"] = u_input
        elif "surgery date" in last_bot_msg:
            d["surgery_date"] = u_input
        elif "hospital name" in last_bot_msg:
            d["hospital_name"] = u_input
        else:
            # generic fallback: store in notes
            d["notes"] = u_input

        st.session_state.updated_final_data["patient_data"] = d

        reply = st.session_state.confirm_response.send_message(user_input)
        st.session_state.confirm_history.append(("bot", reply.text.strip()))

        # Check for confirmation
        result = extract_json(reply.text)
        if result.get("status") == "confirmed":
            return st.session_state.updated_final_data, True, result.get("message", "")
        else:
            st.rerun()

    return final_json, False, ""


def main():
    st.title("Medical Intake Assistant")

    # --- MANUAL OVERRIDE: Start from mapping step if file exists ---
    if "step" not in st.session_state:
        st.session_state.step = "intake"
    # --------------------------------------------------------------

    if st.session_state.step == "intake":
        st.header("Step 1: Patient Intake")
        patient_data, summary, done = dynamic_medical_intake()
        if done:
            st.success("Patient intake completed.")
            st.write("Summary:", summary)
            st.session_state.patient_data = patient_data
            st.session_state.summary = summary
            st.session_state.step = "followup"
            st.rerun()

    elif st.session_state.step == "followup":
        st.header("Step 2: Follow-up Questions for Missing Info")
        patient_data = st.session_state.get("patient_data", {})
        updated_data, notes, done = post_analysis_and_followup(patient_data)
        if done:
            st.success("Follow-up questions complete.")
            st.write("Notes:", notes)
            st.session_state.patient_data = updated_data
            st.session_state.followup_notes = notes
            st.session_state.step = "specialist"
            st.rerun()

    elif st.session_state.step == "specialist":
        st.header("Step 3: Specialist Recommendation")
        patient_data = st.session_state.get("patient_data", {})
        specialists, rationale = recommend_specialist(patient_data)
        st.write("Recommended Specialists:", specialists)
        st.write("Rationale:", rationale)
        st.session_state.recommended_specialist = specialists
        st.session_state.specialist_rationale = rationale
        st.session_state.step = "confirm"
        st.rerun()

    elif st.session_state.step == "confirm":
        st.header("Step 4: Confirm Mandatory Fields")
        # Build the final JSON in your required format
        patient_data = st.session_state.get("patient_data", {})
        summary = st.session_state.get("summary", "")
        followup_notes = st.session_state.get("followup_notes", "")
        recommended_specialist = st.session_state.get("recommended_specialist", [])
        specialist_rationale = st.session_state.get("specialist_rationale", "")
        final_json = {
            "summary": summary,
            "patient_data": patient_data,
            "followup_notes": followup_notes,
            "recommended_specialist": recommended_specialist,
            "specialist_rationale": specialist_rationale,
            "status": "complete"
        }
        updated_data, confirmed, message = confirm_mandatory_fields(final_json)
        if confirmed:
            st.success(message)
            st.write("Final Patient Data:", updated_data)
            st.session_state.final_patient_json = updated_data
            with open("final_patient_summary.json", "w") as f:
                json.dump(updated_data, f, indent=2)
            st.session_state.step = "mapping"  # <-- Move to mapping step
            st.rerun()
        else:
            st.info("Please provide the missing information.")

    elif st.session_state.step == "mapping":
        st.header("Step 5: Map Collected Info to DB Schema")
        # Always use the latest confirmed data
        patient_json = st.session_state.get("final_patient_json", {})
        if patient_json:
            # Optionally save patient_json to disk (already done in confirm step)
            st.write("Patient JSON data ready for mapping.")
    
            # Call your mapping function from the imported module
            try:
                # Assuming your mapping module has a function like:
                # get_mapped_output(patient_json) -> dict
                mapped_result = mapping_collectedinfo_to_schema.get_mapped_output(patient_json)
                st.success("Mapping to DB schema completed successfully.")
                st.json(mapped_result)  # Show mapped data for verification
    
                # Save mapped data if you want
                with open("mapped_output.json", "w") as f:
                    json.dump(mapped_result, f, indent=2)
    
                # Proceed to next step or finish workflow
                st.session_state.mapped_patient_data = mapped_result # or any next step
                st.write("Mapping complete. You can now use this data to insert into your DB.")
                st.session_state.step = "db_insert" 
                st.rerun()
                return
            except Exception as e:
                st.error(f"Mapping failed: {e}")
        else:
            st.warning("No confirmed patient JSON data available yet.")

    elif st.session_state.step == "db_insert":
        st.header("Step 6: Review and Insert Data into Database")
        mapped_file = "mapped_output.json"
        if os.path.exists(mapped_file):
            try:
                with open(mapped_file, "r") as f:
                    mapped_result = json.load(f)
                st.subheader("Mapped JSON to be Inserted")
                st.json(mapped_result)

                # Debug: Show database configuration (with password hidden)
                debug_config = dict(db_config)
                if "password" in debug_config:
                    debug_config["password"] = "****"
                st.write("Database Configuration:")
                st.json(debug_config)

                if st.button("Insert into Database"):
                    try:
                        # Test database connection first
                        st.info("Testing database connection...")
                        conn = pymysql.connect(**db_config)
                        st.success("Database connection successful!")
                        conn.close()

                        # Proceed with insertion
                        st.info("Starting data insertion...")
                        insert_data_from_mapped_json(mapped_file)
                        st.success("✅ Data successfully inserted into the database.")
                        st.session_state.step = "booking"
                        st.rerun()
                    except pymysql.Error as e:
                        st.error(f"❌ Database connection/insertion failed: {str(e)}")
                        st.error("Error Code: " + str(getattr(e, 'args', ['Unknown'])[0]))
                        st.error("Error Message: " + str(getattr(e, 'args', ['Unknown'])[1]))
                    except Exception as e:
                        st.error(f"❌ Other error during insertion: {str(e)}")
                        import traceback
                        st.error("Full error trace: " + traceback.format_exc())
            except json.JSONDecodeError as e:
                st.error(f"❌ Error reading mapped file: {str(e)}")
            except Exception as e:
                st.error(f"❌ Unexpected error: {str(e)}")
        else:
            st.error("Mapped output file not found. Please complete mapping step first.")

    elif st.session_state.step == "booking":
        st.header("Step 7: Book Appointment with Recommended Specialist")
        try:
            result = book_appointment_from_json()  # returns message string or object
            if isinstance(result, str):
                st.text("Booking Script Output:\n" + result)
                if "Appointment booked" in result:
                    st.success("✅ Appointment successfully booked!")
                elif "No available slots found" in result:
                    st.warning("⚠️ No available slots found for any recommended specialist in the next 7 days.")
                else:
                    st.info("See output above for booking details.")
            else:
                st.error("Unexpected result format from booking function")
        except Exception as e:
            st.error(f"❌ Booking failed: {e}")
        
        # Show a "Finish" button to move to done step
        if st.button("Finish"):
            st.session_state.step = "done"
            st.rerun()

    else:
        st.header("All steps completed.")
        st.write("Thank you! The medical intake process is finished.")

if __name__ == "__main__":
    main()
