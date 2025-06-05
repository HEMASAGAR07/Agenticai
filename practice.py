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

# Custom styling
st.set_page_config(
    page_title="MediBot - Smart Medical Assistant",
    page_icon="🏥",
    layout="wide"
)

# Custom CSS
st.markdown("""
<style>
    .main {
        padding: 2rem;
    }
    .stButton>button {
        background-color: #3498db;
        color: white;
        border-radius: 20px;
        padding: 0.5rem 2rem;
        border: none;
        transition: all 0.3s ease;
    }
    .stButton>button:hover {
        background-color: #2980b9;
        transform: translateY(-2px);
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
    }
    .success-message {
        padding: 1rem;
        border-radius: 10px;
        background-color: #d4edda;
        border: 1px solid #c3e6cb;
        color: #155724;
    }
    .error-message {
        padding: 1rem;
        border-radius: 10px;
        background-color: #f8d7da;
        border: 1px solid #f5c6cb;
        color: #721c24;
    }
    .info-box {
        background-color: #e3f2fd;
        padding: 1.5rem;
        border-radius: 10px;
        margin: 1rem 0;
        border-left: 5px solid #2196f3;
    }
    .step-header {
        background: linear-gradient(90deg, #3498db, #2980b9);
        color: white;
        padding: 1rem;
        border-radius: 10px;
        margin: 1rem 0;
    }
    .chat-message {
        padding: 1rem;
        border-radius: 15px;
        margin: 0.5rem 0;
        max-width: 80%;
    }
    .bot-message {
        background-color: #f1f1f1;
        margin-right: auto;
    }
    .user-message {
        background-color: #e3f2fd;
        margin-left: auto;
    }
    .input-container {
        background-color: white;
        padding: 1rem;
        border-radius: 10px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }
</style>
""", unsafe_allow_html=True)

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
    if "name_collected" not in st.session_state:
        st.session_state.name_collected = False

    if st.session_state.intake_response is None:
        intro = """
You are MediBot, an intelligent medical intake assistant with strong validation capabilities.

Your job is to collect all necessary health details step-by-step, one question at a time, while strictly validating each response.

🔍 Validation Rules:
1. Name Validation:
   - Must contain at least 2 words (first and last name)
   - No numbers or special characters allowed
   - Each word must be at least 2 characters long
   - Must not be gibberish (e.g., "asdf asdf", "test test")

2. Email Validation:
   - Must follow valid email format (user@domain.com)
   - Common typos in domain names should be caught (e.g., "gmial.com", "yaho.com")
   - Must not be temporary/disposable email patterns

3. Phone Number Validation:
   - Must be a valid phone number format (e.g., 10 digits for US numbers)
   - Must not be sequential numbers (e.g., "1234567890")
   - Must not be repeated digits (e.g., "1111111111")

4. Age/Date Validation:
   - Must be a reasonable age (0-120)
   - Dates must be in YYYY-MM-DD format
   - Future dates are not allowed for birth dates
   - Surgery dates must be in the past

5. Medical Information Validation:
   - Symptoms must be specific and clear (not vague terms like "not feeling well")
   - Medications must include dosage when provided
   - Allergies must be specific substances/medications
   - Medical conditions must be recognized terms

For EACH user response:
1. First validate the format based on the field type
2. Check for common mistakes or invalid patterns
3. If invalid:
   - Explain specifically why the input is invalid
   - Provide an example of correct format
   - Ask for the information again
4. If valid but unclear:
   - Ask follow-up questions for clarification
   - Request more specific details if needed

Context Rules:
- Track previous answers to ensure consistency
- Flag contradictions in medical history
- Ensure related medical information aligns
- Maintain conversation context between questions

Never proceed to the next question until the current answer is fully validated and clear.

📝 Your final output should ONLY be a JSON object like:
{
  "summary": "Short summary of findings",
  "patient_data": {
    "name": "John Smith",
    "email": "john@email.com",
    "age": 34,
    "gender": "Male",
    "phone": "1234567890",
    "address": "123 Main St, City, State, ZIP",
    "symptoms": "yes",
    "symptom_list": "Specific symptoms...",
    "medications": "yes",
    "medication_list": "Med1 10mg, Med2 20mg...",
    "allergies": "yes",
    "allergy_list": "Specific allergies...",
    "past_history": "yes",
    "past_illness": "Specific conditions..."
  },
  "validation_status": {
    "all_fields_valid": true,
    "last_validated_field": "field_name",
    "validation_message": "All inputs validated successfully"
  },
  "status": "complete"
}

Begin with a friendly greeting and ask for the patient's full name.
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
        
        # Check if this is a name response
        last_bot_msg = st.session_state.intake_history[-2][1].lower()
        if "name" in last_bot_msg and not st.session_state.name_collected:
            st.session_state.name_collected = True
            st.session_state.patient_data["name"] = user_input.strip()
        
        # Construct context with emphasis on brevity and not repeating name
        context = "Previous conversation:\n"
        for role, text in st.session_state.intake_history[-4:]:
            context += f"{'Assistant' if role == 'bot' else 'Patient'}: {text}\n"
        
        context += f"\nCurrent patient data: {json.dumps(st.session_state.patient_data, indent=2)}\n"
        if st.session_state.name_collected:
            context += "\nNOTE: Name has already been collected. DO NOT ask for it again.\n"
        context += "\nContinue with SHORT, DIRECT questions. One question at a time."
        
        reply = st.session_state.intake_response.send_message(
            context + "\n\nPatient: " + user_input
        )
        st.session_state.intake_history.append(("bot", reply.text.strip()))

        # Check if final JSON with status complete
        final_output = extract_json(reply.text)
        if final_output.get("status") == "complete":
            patient_data = final_output.get("patient_data", {})
            
            # Validate required fields before allowing completion
            required_fields = ["name", "email", "dob", "gender", "phone", "address"]
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
You are a medical assistant with strong validation capabilities.

Given the patient data JSON below, strictly validate ALL mandatory fields.

Mandatory fields with validation rules:

1. Patient Basic Info:
   - name: Must be full name (first + last), no numbers/special chars
   - email: Valid format (user@domain.com), no typos in common domains
   - age: Number between 0-120
   - gender: Standard gender terms
   - phone: Valid phone format, no sequential/repeated numbers
   - address: Must include street, city, state/region

2. Conditional Fields:
   - If symptoms="yes": symptom_list must have specific symptoms
   - If allergies="yes": allergy_list must have specific allergens
   - If medications="yes": medication_list must include names and dosages
   - If past_history="yes": past_illness must have specific conditions
   - If surgery info exists: All surgery fields must be complete and valid

Validation Process:
1. Check each field's presence
2. Validate format and content
3. Cross-reference related fields
4. Check for contradictions
5. Verify completeness

For EACH invalid or unclear field:
1. Explain why it's invalid
2. Show correct format/example
3. Request the information again

⚠️ IMPORTANT: 
- Email field MUST be validated first
- Do not proceed until email is valid
- Flag any suspicious patterns
- Check for data consistency
- Ensure medical terms are valid

Here is the patient data:

{json.dumps(final_json, indent=2)}

Begin validation and request missing/invalid information one at a time.
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
        elif "address" in last_bot_msg:
            d["address"] = u_input
            # Move from notes to address if it was stored in notes
            if "notes" in d and d["notes"] and not d.get("address"):
                d["address"] = d["notes"]
                d["notes"] = ""
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
        required_fields = ["name", "email", "dob", "gender", "phone", "address"]
        for field in required_fields:
            if field not in patient_data:
                patient_data[field] = ""
                
        data["patient_data"] = patient_data
    
    return data


def main():
    # Header with logo and title
    col1, col2 = st.columns([1, 4])
    with col1:
        st.markdown("# 🏥")
    with col2:
        st.markdown("""
            <h1 style='color: #2c3e50;'>Medical Intake Assistant</h1>
            <p style='color: #7f8c8d;'>Your AI-powered healthcare companion</p>
        """, unsafe_allow_html=True)

    # Progress bar
    if "step" not in st.session_state:
        st.session_state.step = "intake"
    
    steps = ["intake", "followup", "specialist", "confirm", "mapping", "db_insert", "booking"]
    current_step = steps.index(st.session_state.step) + 1
    progress = current_step / len(steps)
    
    st.markdown(f"""
        <div style='padding: 1rem; background-color: #f8f9fa; border-radius: 10px; margin-bottom: 2rem;'>
            <p style='margin-bottom: 0.5rem;'>Progress: Step {current_step} of {len(steps)}</p>
        </div>
    """, unsafe_allow_html=True)
    st.progress(progress)

    # Migrate any existing session data
    if "patient_data" in st.session_state:
        st.session_state.patient_data = migrate_existing_data({"patient_data": st.session_state.patient_data})["patient_data"]
    if "final_patient_json" in st.session_state:
        st.session_state.final_patient_json = migrate_existing_data(st.session_state.final_patient_json)

    if st.session_state.step == "intake":
        st.markdown("""
            <div class='step-header'>
                <h2>Step 1: Patient Intake</h2>
                <p>Let's start by gathering your basic information</p>
            </div>
        """, unsafe_allow_html=True)
        
        patient_data, summary, done = dynamic_medical_intake()
        if done:
            st.markdown("""
                <div class='success-message'>
                    ✅ Patient intake completed successfully!
                </div>
            """, unsafe_allow_html=True)
            st.markdown(f"""
                <div class='info-box'>
                    <h4>Summary</h4>
                    <p>{summary}</p>
                </div>
            """, unsafe_allow_html=True)
            st.session_state.patient_data = patient_data
            st.session_state.summary = summary
            st.session_state.step = "followup"
            st.rerun()

    elif st.session_state.step == "followup":
        st.markdown("""
            <div class='step-header'>
                <h2>Step 2: Follow-up Questions</h2>
                <p>Let's get some additional details to better understand your needs</p>
            </div>
        """, unsafe_allow_html=True)
        
        patient_data = st.session_state.get("patient_data", {})
        updated_data, notes, done = post_analysis_and_followup(patient_data)
        if done:
            st.markdown("""
                <div class='success-message'>
                    ✅ Follow-up questions completed!
                </div>
            """, unsafe_allow_html=True)
            if notes:
                st.markdown(f"""
                    <div class='info-box'>
                        <h4>Additional Notes</h4>
                        <p>{notes}</p>
                    </div>
                """, unsafe_allow_html=True)
            st.session_state.patient_data = updated_data
            st.session_state.followup_notes = notes
            st.session_state.step = "specialist"
            st.rerun()

    elif st.session_state.step == "specialist":
        st.markdown("""
            <div class='step-header'>
                <h2>Step 3: Specialist Recommendation</h2>
                <p>Let's find the right specialist for you</p>
            </div>
        """, unsafe_allow_html=True)
        
        patient_data = st.session_state.get("patient_data", {})
        specialists, rationale = recommend_specialist(patient_data)
        st.write("Recommended Specialists:", specialists)
        st.write("Rationale:", rationale)
        st.session_state.recommended_specialist = specialists
        st.session_state.specialist_rationale = rationale
        st.session_state.step = "confirm"
        st.rerun()

    elif st.session_state.step == "confirm":
        st.markdown("""
            <div class='step-header'>
                <h2>Step 4: Confirm Mandatory Fields</h2>
                <p>Let's ensure all your information is correct</p>
            </div>
        """, unsafe_allow_html=True)
        
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
            st.markdown("""
                <div class='success-message'>
                    ✅ Mandatory fields confirmed!
                </div>
            """, unsafe_allow_html=True)
            st.markdown(f"""
                <div class='info-box'>
                    <h4>Final Patient Data</h4>
                    <p>{json.dumps(updated_data, indent=2)}</p>
                </div>
            """, unsafe_allow_html=True)
            st.session_state.final_patient_json = updated_data
            with open("final_patient_summary.json", "w") as f:
                json.dump(updated_data, f, indent=2)
            st.session_state.step = "mapping"  # <-- Move to mapping step
            st.rerun()
        else:
            st.info("Please provide the missing information.")

    elif st.session_state.step == "mapping":
        st.markdown("""
            <div class='step-header'>
                <h2>Step 5: Map Collected Info to DB Schema</h2>
                <p>Let's ensure your data is correctly mapped to our database</p>
            </div>
        """, unsafe_allow_html=True)
        
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
        st.markdown("""
            <div class='step-header'>
                <h2>Step 6: Review and Insert Data into Database</h2>
                <p>Let's ensure your data is correctly inserted into our database</p>
            </div>
        """, unsafe_allow_html=True)
        
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
                    debug_config["password"] = "**"
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
        st.markdown("""
            <div class='step-header'>
                <h2>Step 7: Book Appointment with Recommended Specialist</h2>
                <p>Let's schedule your appointment with the recommended specialist</p>
            </div>
        """, unsafe_allow_html=True)
        
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
        st.markdown("""
            <div class='step-header'>
                <h2>All steps completed!</h2>
                <p>Thank you for using the Medical Intake Assistant!</p>
            </div>
        """, unsafe_allow_html=True)
        
        # Add a restart button
        if st.button("Start New Intake"):
            # Clear session state
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.session_state.step = "intake"
            st.rerun()

if __name__ == "__main__":
    main()
