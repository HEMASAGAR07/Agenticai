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
import streamlit.components.v1 as components

# Import additional Streamlit components for UI enhancement
import streamlit.components.v1 as components

# Enhance the UI with a custom theme and layout
st.set_page_config(
    page_title="MediBot - Medical Intake Assistant",
    page_icon="🩺",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Add a custom CSS style for better UI
st.markdown(
    """
    <style>
    .reportview-container {
        background: #f0f2f6;
    }
    .sidebar .sidebar-content {
        background: #e0e4e8;
    }
    .stButton>button {
        background-color: #4CAF50;
        color: white;
    }
    .stTextInput>div>div>input {
        border: 1px solid #4CAF50;
    }
    </style>
    """,
    unsafe_allow_html=True
)

# Add a header with an icon
st.title("MediBot - Your Medical Intake Assistant 🩺")

# Add a progress bar to indicate the intake process
progress = st.progress(0)

# Initialize progress value within the valid range
if "intake_progress" not in st.session_state:
    st.session_state.intake_progress = 0

# Safely increment progress value
st.session_state.intake_progress = min(st.session_state.intake_progress + 10, 100)

# Update progress bar
progress.progress(st.session_state.intake_progress)

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
You are an intelligent and empathetic medical intake assistant named MediBot.

Your job is to collect necessary health details through a natural, conversational dialogue. Make patients feel comfortable while gathering information.

🔍 Follow these guidelines:
1. Be conversational and friendly, but professional
2. Adapt your questions based on previous answers
3. Show empathy and understanding
4. Ask follow-up questions when appropriate
5. Validate responses naturally

For example, instead of just asking "What's your name?", say something like:
"Hi there! I'm MediBot, and I'll be helping you today. Could you please tell me your full name?"

⚠️ Important behaviors:
- Keep the conversation natural and flowing
- Acknowledge patient responses before asking the next question
- Ask relevant follow-up questions based on symptoms or conditions mentioned
- Show understanding and empathy in your responses
- Validate information while staying conversational
- Maintain a warm, professional tone

Required Information to Collect:
1. Basic Information:
   - Full Name
   - Email (valid format)
   - Date of Birth
   - Gender
   - Phone Number

2. Medical Information:
   - Current symptoms or concerns
   - Duration and severity of symptoms
   - Past medical history
   - Current medications
   - Allergies
   - Family medical history (if relevant)
   - Lifestyle factors (if relevant)

Your responses should be conversational but ensure all necessary information is collected. For example:

Patient: "I'm John and I have a headache"
You: "Nice to meet you, John! I'm sorry to hear about your headache. Could you tell me how long you've been experiencing it? Also, I'll need your email address to set up your records properly."

When complete, return a JSON like:
{
  "summary": "Friendly summary of findings",
  "patient_data": {
    "name": "John Smith",
    "email": "john@email.com",
    "dob": "1990-01-01",
    "gender": "Male",
    "phone": "555-0123",
    "symptoms": "Headache for 2 days",
    ...
  },
  "status": "complete"
}

Begin with a friendly greeting and ask for the patient's full name in a conversational way.
"""
        st.session_state.intake_response = model.start_chat(history=[])
        reply = st.session_state.intake_response.send_message(intro)
        st.session_state.intake_history.append(("bot", reply.text.strip()))
    else:
        reply = st.session_state.intake_response

    st.write(f" {st.session_state.intake_history[-1][1]}")

    user_input = st.text_input("Your answer:", key="intake_input", 
                              placeholder="Type your response here...")
    submit = st.button("Continue", key="intake_submit")

    if submit and user_input:
        st.session_state.intake_history.append(("user", user_input))
        
        # Construct context from history
        context = "Previous conversation:\n"
        for role, text in st.session_state.intake_history[-4:]:  # Last 4 exchanges
            context += f"{'Assistant' if role == 'bot' else 'Patient'}: {text}\n"
        
        context += f"\nCurrent patient data: {json.dumps(st.session_state.patient_data, indent=2)}\n"
        context += "\nContinue the conversation naturally while gathering any missing information."
        
        # Prioritize essential questions
        essential_questions = ["name", "email", "dob", "gender", "phone"]
        missing_essentials = [q for q in essential_questions if not st.session_state.patient_data.get(q)]
        
        if missing_essentials:
            # Ask only essential questions
            prompt = f"""
Please provide the following essential information: {', '.join(missing_essentials)}.

Remember to:
1. Stay conversational and friendly
2. Acknowledge previous responses
3. Ask for missing information naturally
4. Validate the information received

Previous conversation:
{context}
"""
            reply = st.session_state.intake_response.send_message(prompt)
            st.session_state.intake_history.append(("bot", reply.text.strip()))
        else:
            # Continue with follow-up questions only if essential information is complete
            reply = st.session_state.intake_response.send_message(
                context + "\n\nPatient: " + user_input
            )
            st.session_state.intake_history.append(("bot", reply.text.strip()))

        # Check if final JSON with status complete
        final_output = extract_json(reply.text)
        if final_output.get("status") == "complete":
            patient_data = final_output.get("patient_data", {})
            
            # Validate required fields before allowing completion
            required_fields = ["name", "email", "dob", "gender", "phone"]
            missing_fields = [field for field in required_fields if not patient_data.get(field)]
            
            if missing_fields:
                # If any required field is missing, continue the intake
                prompt = f"""
Some required information is still missing. Please collect the following in a natural, conversational way:
{', '.join(missing_fields)}

Remember to:
1. Stay conversational and friendly
2. Acknowledge previous responses
3. Ask for missing information naturally
4. Validate the information received

Previous conversation:
{context}
"""
                st.session_state.intake_response.send_message(prompt)
                st.rerun()
            else:
                st.session_state.patient_data = patient_data
                summary = final_output.get("summary", "")
                st.success("✅ Initial intake complete. Thank you for your patience!")
                return patient_data, summary, True
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

    user_input = st.text_input("Your answer here:", key="followup_input", help="Please provide your response here.")
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

- From Patient: "name", "email", "age", "gender", "Ph Number" (phone)
- If "symptoms" == "yes": "symptom_list" required (comma-separated string)
- If "allergies" == "yes": "allergy_list" required
- If "medications" == "yes": "medication_list" required
- If "past_history" == "yes": "past_illness" required
- If surgery info present: "procedure_name", "surgery_date", "hospital_name" required

⚠️ IMPORTANT: The email field MUST be present and valid (e.g., user@domain.com format).
If email is missing or invalid, you MUST ask for it first before any other fields.
DO NOT proceed with other fields until a valid email is provided.

If any mandatory fields are missing or empty, ask the patient directly to provide them one by one.

If all mandatory fields are present, reply with:

{{"status": "confirmed", "message": "All mandatory fields present."}}

Otherwise, ask only for missing fields one at a time.

Here is the patient data:

{json.dumps(final_json, indent=2)}

Begin your check and ask for missing info as needed, starting with email if it's missing or invalid.
"""
        st.session_state.confirm_response = model.start_chat(history=[])
        reply = st.session_state.confirm_response.send_message(prompt)
        st.session_state.confirm_history = [("bot", reply.text.strip())]
        st.session_state.updated_final_data = dict(final_json)  # copy original data
        if "patient_data" not in st.session_state.updated_final_data:
            st.session_state.updated_final_data["patient_data"] = {}
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

        # Email handling with validation
        if "email" in last_bot_msg:
            if "@" in u_input and "." in u_input:  # Basic email validation
                d["email"] = u_input
                st.success(f"Email saved: {u_input}")
            else:
                st.error("Please provide a valid email address (e.g., user@domain.com)")
                return st.session_state.updated_final_data, False, "Invalid email format"
        elif "name" in last_bot_msg:
            d["name"] = u_input
        elif "age" in last_bot_msg:
            try:
                d["age"] = int(u_input)
            except:
                d["age"] = u_input
        elif "gender" in last_bot_msg:
            d["gender"] = u_input
        elif "phone" in last_bot_msg or "ph number" in last_bot_msg:
            d["phone"] = u_input
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

        # Debug: Show current data state
        st.write("Current data state:")
        st.json(st.session_state.updated_final_data)

        reply = st.session_state.confirm_response.send_message(user_input)
        st.session_state.confirm_history.append(("bot", reply.text.strip()))

        # Check for confirmation
        result = extract_json(reply.text)
        if result.get("status") == "confirmed":
            # Double check mandatory fields
            if "email" not in d or not d["email"] or "@" not in d["email"]:
                st.error("Email is required. Please provide a valid email address.")
                return st.session_state.updated_final_data, False, "Email is required"
            
            # Move address from notes if it exists there
            if not d.get("address") and d.get("notes"):
                d["address"] = d["notes"]
                d["notes"] = ""
                st.session_state.updated_final_data["patient_data"] = d
            
            return st.session_state.updated_final_data, True, result.get("message", "")
        else:
            st.rerun()

    return final_json, False, ""


def migrate_existing_data(data):
    """Migrate existing data to new format, ensuring all required fields exist."""
    if not isinstance(data, dict):
        return data

    if "patient_data" in data:
        patient_data = data["patient_data"]
        
        # Move address from notes if it exists and address is empty
        if "notes" in patient_data and not patient_data.get("address"):
            patient_data["address"] = patient_data["notes"]
            patient_data["notes"] = ""
        
        # Ensure email field exists
        if "email" not in patient_data:
            patient_data["email"] = ""
            
        # Ensure other required fields exist
        required_fields = ["name", "email", "dob", "gender", "phone"]
        for field in required_fields:
            if field not in patient_data:
                patient_data[field] = ""
                
        data["patient_data"] = patient_data
    
    return data


def main():
    st.title("Medical Intake Assistant")

    # --- MANUAL OVERRIDE: Start from mapping step if file exists ---
    if "step" not in st.session_state:
        st.session_state.step = "intake"
    # --------------------------------------------------------------

    # Migrate any existing session data
    if "patient_data" in st.session_state:
        st.session_state.patient_data = migrate_existing_data({"patient_data": st.session_state.patient_data})["patient_data"]
    if "final_patient_json" in st.session_state:
        st.session_state.final_patient_json = migrate_existing_data(st.session_state.final_patient_json)

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

                # Check if data has been inserted successfully
                if "db_insert_success" in st.session_state and st.session_state.db_insert_success:
                    st.success("✅ Data has been successfully inserted into the database!")
                    if st.button("Proceed to Booking", key="proceed_to_booking"):
                        st.session_state.step = "booking"
                        st.rerun()
                    return

                if st.button("Insert into Database", key="insert_db"):
                    try:
                        # Test database connection first
                        st.info("Testing database connection...")
                        conn = pymysql.connect(**db_config)
                        cursor = conn.cursor(pymysql.cursors.DictCursor)
                        
                        # Verify we can read from the database
                        st.info("Verifying database read access...")
                        cursor.execute("SHOW TABLES")
                        tables = cursor.fetchall()
                        # Extract table names from DictCursor result
                        table_names = [list(table.values())[0] for table in tables]
                        st.write("Available tables:", table_names)
                        
                        # Get initial record counts
                        st.info("Getting initial record counts...")
                        table_counts_before = {}
                        for table_name in table_names:
                            cursor.execute(f"SELECT COUNT(*) as count FROM {table_name}")
                            result = cursor.fetchone()
                            table_counts_before[table_name] = result['count']
                        st.write("Initial record counts:", table_counts_before)
                        
                        # Proceed with insertion
                        st.info("Starting data insertion...")
                        result = insert_data_from_mapped_json(mapped_file)
                        
                        if result.get("status") == "success":
                            st.success("✅ Data successfully inserted into the database!")
                            
                            # Show insertion summary
                            st.write("Records inserted:")
                            for record in result.get("inserted_records", []):
                                if record["type"] == "single":
                                    st.write(f"- Added 1 record to {record['table']} (ID: {record['id']})")
                                else:
                                    st.write(f"- Added {record['count']} records to {record['table']}")
                            
                            # Set success flag and show proceed button
                            st.session_state.db_insert_success = True
                            st.rerun()  # Rerun to show the proceed button
                        else:
                            st.error("❌ Data insertion failed")
                            st.session_state.db_insert_success = False
                            
                    except Exception as e:
                        st.error(f"❌ Error during database operation: {str(e)}")
                        import traceback
                        st.error("Full error trace: " + traceback.format_exc())
                    finally:
                        if 'cursor' in locals():
                            cursor.close()
                        if 'conn' in locals():
                            conn.close()
            except Exception as e:
                st.error(f"❌ Error: {str(e)}")
        else:
            st.error("Mapped output file not found. Please complete mapping step first.")

    elif st.session_state.step == "booking":
        st.header("Step 7: Book Appointment with Recommended Specialist")
        
        # Verify that we came from a successful database insertion
        if not st.session_state.get("db_insert_success", False):
            st.warning("⚠️ Please complete the database insertion step first")
            if st.button("Go Back to Database Insertion"):
                st.session_state.step = "db_insert"
                st.rerun()
            return
        
        # First verify we have the patient data with email
        try:
            with open("final_patient_summary.json", "r") as f:
                patient_data = json.load(f)
            
            # Show the data being used for booking
            with st.expander("View Patient Data"):
                st.json(patient_data.get("patient_data", {}))
            
            # Show recommended specialists
            specialists = patient_data.get("recommended_specialist", [])
            if specialists:
                st.write("Recommended Specialists:")
                for specialist in specialists:
                    st.write(f"- {specialist}")
            
            if not patient_data.get("patient_data", {}).get("email"):
                st.error("❌ Email is missing in the patient data. Please complete the patient information first.")
                if st.button("Go Back to Patient Info"):
                    st.session_state.step = "confirm"
                    st.rerun()
                return
            
            # Add a button to initiate booking
            book_button = st.button("Book Appointment", key="book_appointment")
            if book_button:
                try:
                    result = book_appointment_from_json()  # returns message string or object
                    if isinstance(result, str):
                        if "Appointment booked" in result:
                            st.success("✅ " + result)
                            st.session_state.booking_success = True
                            # Show finish button only after successful booking
                            finish_button = st.button("Finish", key="finish_booking")
                            if finish_button:
                                st.session_state.step = "done"
                                st.rerun()
                        elif "No available slots found" in result:
                            st.warning("⚠️ " + result)
                            st.session_state.booking_success = False
                        else:
                            st.info(result)
                    else:
                        st.error("Unexpected result format from booking function")
                except Exception as e:
                    st.error(f"❌ Booking failed: {str(e)}")
                    import traceback
                    st.error("Full error trace: " + traceback.format_exc())
                    
        except FileNotFoundError:
            st.error("❌ Patient data file not found. Please complete the patient information first.")
            if st.button("Go Back to Patient Info"):
                st.session_state.step = "confirm"
                st.rerun()
        except json.JSONDecodeError:
            st.error("❌ Error reading patient data file. The file might be corrupted.")
        except Exception as e:
            st.error(f"❌ Unexpected error: {str(e)}")

    else:  # done step
        st.header("All steps completed!")
        st.success("Thank you for using the Medical Intake Assistant!")
        
        # Add a restart button
        if st.button("Start New Intake"):
            # Clear session state
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.session_state.step = "intake"
            st.rerun()

    # Add a footer with contact information
    st.markdown("""
    ---
    **Contact Us:**
    - Email: support@medibot.com
    - Phone: +1-800-555-0199
    """)

if __name__ == "__main__":
    main()
