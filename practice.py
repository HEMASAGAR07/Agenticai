import os
import json
import streamlit as st
from dotenv import load_dotenv
import google.generativeai as genai
import mapping_collectedinfo_to_schema  # <-- Add this import at the top
import mysql.connector
import subprocess
import pymysql
from inserting_JSON_to_DB import db_config,insert_data_from_mapped_json, save_operation_state, handle_table_operation, get_last_update_timestamp
from booking import book_appointment_from_json
import uuid
from datetime import date, datetime

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


def get_user_from_db(email):
    """Retrieve user data from database using email"""
    # Check cache first
    cache_key = f"user_data_{email}"
    if "db_cache" not in st.session_state:
        st.session_state.db_cache = {}
    
    if cache_key in st.session_state.db_cache:
        return st.session_state.db_cache[cache_key]
        
    try:
        conn = pymysql.connect(**db_config)
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        
        # First get patient basic info
        cursor.execute("""
            SELECT 
                p.patient_id,
                p.full_name,
                p.age,
                p.gender,
                p.email,
                p.phone,
                p.address,
                p.DOB
            FROM patients p
            WHERE p.email = %s
        """, (email,))
        
        user_data = cursor.fetchone()
        if user_data:
            # Convert to regular dict and clean up None values
            user_data = dict(user_data)
            
            # Get symptoms
            cursor.execute("""
                SELECT GROUP_CONCAT(
                    CONCAT(symptom_description, ' (', severity, ', ', duration, ')')
                ) as symptoms_list
                FROM symptoms 
                WHERE patient_id = %s
            """, (user_data['patient_id'],))
            symptoms_result = cursor.fetchone()
            user_data['previous_symptoms'] = symptoms_result['symptoms_list'] if symptoms_result and symptoms_result['symptoms_list'] else ""
            
            # Get medications
            cursor.execute("""
                SELECT GROUP_CONCAT(
                    CONCAT(medication_name, ' (', dosage, ')')
                ) as medications_list
                FROM medications 
                WHERE patient_id = %s
            """, (user_data['patient_id'],))
            medications_result = cursor.fetchone()
            user_data['previous_medications'] = medications_result['medications_list'] if medications_result and medications_result['medications_list'] else ""
            
            # Get allergies
            cursor.execute("""
                SELECT GROUP_CONCAT(
                    CONCAT(substance, ' (', severity, ')')
                ) as allergies_list
                FROM allergies 
                WHERE patient_id = %s
            """, (user_data['patient_id'],))
            allergies_result = cursor.fetchone()
            user_data['previous_allergies'] = allergies_result['allergies_list'] if allergies_result and allergies_result['allergies_list'] else ""
            
            # Get surgeries
            cursor.execute("""
                SELECT GROUP_CONCAT(
                    CONCAT(procedure_name, ' at ', hospital_name, ' on ', surgery_date)
                ) as surgeries_list
                FROM surgeries 
                WHERE patient_id = %s
            """, (user_data['patient_id'],))
            surgeries_result = cursor.fetchone()
            user_data['previous_surgeries'] = surgeries_result['surgeries_list'] if surgeries_result and surgeries_result['surgeries_list'] else ""
            
            # Clean up None values
            for key in user_data:
                if user_data[key] is None:
                    user_data[key] = ""
            
            # Cache the result
            st.session_state.db_cache[cache_key] = user_data
        
        return user_data
    except Exception as e:
        st.error(f"Database error: {str(e)}")
        return None
    finally:
        if 'cursor' in locals():
            cursor.close()
        if 'conn' in locals():
            conn.close()

def invalidate_user_cache(email):
    """Invalidate cached data for a user"""
    if "db_cache" in st.session_state:
        cache_key = f"user_data_{email}"
        if cache_key in st.session_state.db_cache:
            del st.session_state.db_cache[cache_key]

def is_valid_name(name):
    """Validate a name with reasonable rules"""
    if not name:
        return False, "Name cannot be empty"
    
    # Remove extra spaces and standardize
    name = " ".join(name.split())
    
    # Basic validation rules
    if len(name) < 2:
        return False, "Name is too short"
    
    # Allow letters, spaces, hyphens, and apostrophes for names like O'Connor or Jean-Pierre
    if not all(c.isalpha() or c in " -'" for c in name):
        return False, "Name can only contain letters, spaces, hyphens, and apostrophes"
    
    # Check for at least one space (indicating first and last name)
    if " " not in name:
        return False, "Please provide both first and last name"
    
    # Check each part of the name
    parts = name.split()
    if any(len(part) < 2 for part in parts):
        return False, "Each part of the name must be at least 2 characters"
    
    # Check for obviously fake names
    fake_names = {"test test", "asdf asdf", "john doe", "jane doe"}
    if name.lower() in fake_names:
        return False, "Please provide your real name"
    
    return True, name

def is_valid_phone(phone):
    """Validate a phone number with reasonable rules"""
    if not phone:
        return False, "Phone number cannot be empty"
    
    # Remove all non-digit characters for standardization
    digits = ''.join(filter(str.isdigit, phone))
    
    # Basic validation rules
    if len(digits) < 10 or len(digits) > 15:
        return False, "Phone number must be between 10 and 15 digits"
    
    # Allow common prefixes for Indian numbers
    if digits.startswith('91'):
        if len(digits) != 12:  # 91 + 10 digits
            return False, "Indian phone numbers should be 10 digits after country code"
    
    # Basic format check - don't be too strict about repeated digits
    # Only check for obvious test numbers
    obvious_test = {'1234567890', '0987654321', '1111111111', '0000000000'}
    if digits[-10:] in obvious_test:
        return False, "This appears to be a test phone number"
    
    # Format the number nicely for display
    if digits.startswith('91'):
        formatted = f"+{digits[:2]}-{digits[2:7]}-{digits[7:]}"
    else:
        formatted = f"+{digits}"
    
    return True, formatted

def dynamic_medical_intake():
    # Using session state to store conversation & patient_data across reruns
    if "intake_history" not in st.session_state:
        st.session_state.intake_history = []
    if "intake_response" not in st.session_state:
        st.session_state.intake_response = None
    if "patient_data" not in st.session_state:
        st.session_state.patient_data = {}
    if "initial_collection_done" not in st.session_state:
        st.session_state.initial_collection_done = False
    if "db_data_retrieved" not in st.session_state:
        st.session_state.db_data_retrieved = False
    if "current_field" not in st.session_state:
        st.session_state.current_field = "name"
    if "data_confirmed" not in st.session_state:
        st.session_state.data_confirmed = False
    if "in_health_assessment" not in st.session_state:
        st.session_state.in_health_assessment = False
    if "symptoms_collected" not in st.session_state:
        st.session_state.symptoms_collected = False

    # If symptoms have been collected, show the proceed button
    if st.session_state.symptoms_collected:
        st.success("✅ Medical intake completed successfully!")
        if st.button("Proceed to Save Data"):
            st.session_state.step = "db_insert"
            st.rerun()
        return st.session_state.patient_data, "", True

    # If we're in health assessment, handle that flow
    if st.session_state.in_health_assessment:
        if st.session_state.intake_history:
            st.write(f"{st.session_state.intake_history[-1][1]}")

        user_input = st.text_input("Your answer:", key="intake_input", 
                                  placeholder="Type your response here...")
        submit = st.button("Continue", key="intake_submit")

        if submit and user_input:
            st.session_state.intake_history.append(("user", user_input))
            reply = st.session_state.intake_response.send_message(user_input)
            st.session_state.intake_history.append(("bot", reply.text.strip()))
            
            # Check if health intake is complete
            try:
                final_output = extract_json(reply.text)
                if final_output and isinstance(final_output, dict) and final_output.get("status") == "complete":
                    # Create a new patient data dictionary with existing and new data
                    updated_patient_data = st.session_state.patient_data.copy()
                    
                    # If there's new patient data in the final output, update our existing data
                    if "patient_data" in final_output and isinstance(final_output["patient_data"], dict):
                        updated_patient_data.update(final_output["patient_data"])
                    
                    # Store the updated data back in session state
                    st.session_state.patient_data = updated_patient_data
                    st.session_state.symptoms_collected = True
                    st.rerun()
            except Exception as e:
                st.error(f"Error processing response: {str(e)}")
            st.rerun()
        return {}, "", False

    # Initial collection logic
    if st.session_state.intake_response is None:
        intro = """
You are MediBot, a medical intake assistant.

Ask for name FIRST:
- Start with: "Please enter your full name:"
- Validate name but don't show validation details
- After valid name, ask for email
- Keep it simple and direct
"""
        st.session_state.intake_response = model.start_chat(history=[])
        reply = st.session_state.intake_response.send_message(intro)
        st.session_state.intake_history.append(("bot", "Please enter your full name:"))
    else:
        reply = st.session_state.intake_response

    # If we have retrieved data but not confirmed it yet, show confirmation UI
    if st.session_state.db_data_retrieved and not st.session_state.data_confirmed:
        st.markdown("### Your Information")
        st.markdown("Please verify if these details are correct:")
        
        patient_data = st.session_state.patient_data
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("*Personal Details:*")
            st.write(f"📝 Name: {patient_data.get('full_name', '')}")
            st.write(f"📧 Email: {patient_data.get('email', '')}")
            st.write(f"📱 Phone: {patient_data.get('phone', '')}")
            
        with col2:
            st.markdown("*Additional Information:*")
            st.write(f"🎂 Date of Birth: {patient_data.get('DOB', '')}")
            st.write(f"⚧ Gender: {patient_data.get('gender', '')}")
            st.write(f"📍 Address: {patient_data.get('address', '')}")

        # Show medical history if available
        if any(key in patient_data for key in ['previous_symptoms', 'previous_medications', 'previous_allergies', 'previous_surgeries']):
            st.markdown("### Previous Medical History")
            if patient_data.get('previous_symptoms'):
                st.write("🤒 Previous Symptoms:", patient_data['previous_symptoms'])
            if patient_data.get('previous_medications'):
                st.write("💊 Previous Medications:", patient_data['previous_medications'])
            if patient_data.get('previous_allergies'):
                st.write("⚠️ Known Allergies:", patient_data['previous_allergies'])
            if patient_data.get('previous_surgeries'):
                st.write("🏥 Previous Surgeries:", patient_data['previous_surgeries'])
        
        if st.button("✅ Confirm Details"):
            st.session_state.data_confirmed = True
            st.session_state.in_health_assessment = True
            # Start health-specific questions immediately
            health_prompt = """
You are MediBot, a medical intake assistant. The patient has confirmed their details.

IMPORTANT RULES:
1. Start IMMEDIATELY with symptoms assessment
2. Accept and process ALL user responses, including simple yes/no answers
3. If user says "yes", follow up with specific questions about their symptoms
4. If user says "no", ask if they have any other health concerns
5. Never ignore user input or ask for clarification unnecessarily

CONVERSATION FLOW:
1. First Question: "What symptoms or health concerns are you experiencing today? If none, please say 'no'."

2. Based on Response:
   If symptoms mentioned:
   - Ask about severity (mild/moderate/severe)
   - Ask about duration
   - Ask about frequency
   
   If "yes":
   - Ask "Please describe your symptoms or health concerns."
   
   If "no":
   - Ask "Do you have any other health concerns you'd like to discuss?"

3. Follow-up Questions:
   - Keep questions specific and direct
   - Process every answer meaningfully
   - Don't repeat questions
   - Don't ignore simple answers

4. When Complete:
   Return a JSON object with this structure:
   {
     "status": "complete",
     "patient_data": {
       "current_symptoms": [
         {
           "description": "headache",
           "severity": "mild",
           "duration": "2 days"
         }
       ],
       "other_concerns": "none",
       "additional_notes": "patient reports good overall health"
     }
   }

Begin with: "What symptoms or health concerns are you experiencing today? If none, please say 'no'."
"""
            st.session_state.intake_response = model.start_chat(history=[])
            reply = st.session_state.intake_response.send_message(health_prompt)
            st.session_state.intake_history.append(("bot", reply.text.strip()))
            st.rerun()
        
        if st.button("❌ Details are Incorrect"):
            st.error("Please contact support to update your information.")
            return {}, "", False
        
        return {}, "", False

    # Only show the last bot message during initial collection
    if st.session_state.intake_history and not st.session_state.in_health_assessment:
        st.write(f"{st.session_state.intake_history[-1][1]}")

    user_input = st.text_input("Your answer:", key="intake_input", 
                              placeholder="Type your response here...")
    submit = st.button("Continue", key="intake_submit")

    if submit and user_input and not st.session_state.in_health_assessment:
        # Handle name input
        if st.session_state.current_field == "name":
            is_valid, result = is_valid_name(user_input)
            if not is_valid:
                st.error(f"Invalid name: {result}")
                return {}, "", False
            
            # Save name and move to email collection
            st.session_state.patient_data['full_name'] = result
            st.session_state.current_field = "email"
            st.session_state.intake_history.append(("bot", "Please enter your email:"))
            st.rerun()
            return {}, "", False
            
        # Handle email input
        elif st.session_state.current_field == "email":
            # Basic email validation
            if "@" not in user_input or "." not in user_input:
                st.error("Please enter a valid email address.")
                return {}, "", False
            
            # Save email and proceed
            st.session_state.patient_data['email'] = user_input
            st.session_state.initial_collection_done = True
            
            # Try to retrieve user data from DB
            db_user_data = get_user_from_db(user_input)
            if db_user_data:
                # Merge DB data with collected data
                st.session_state.patient_data.update(db_user_data)
                st.session_state.db_data_retrieved = True
                st.rerun()
            else:
                st.error("No existing records found. Please contact support to update your information.")
                return {}, "", False

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
   - phone: Valid phone format with country code (e.g., +91-XXXXX-XXXXX)
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

For phone numbers:
- Accept numbers with or without country code
- Allow common formats (+91-XXXXX-XXXXX or XXXXXXXXXX)
- Basic validation only - focus on length and obvious test numbers
- Don't be too strict about repeated digits

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
        last_bot_msg = st.session_state.confirm_history[-1][1].lower()
        u_input = user_input.strip()
        d = st.session_state.updated_final_data.get("patient_data", {})

        # Phone number handling with new validation
        if "phone" in last_bot_msg:
            is_valid, formatted_phone = is_valid_phone(u_input)
            if is_valid:
                d["phone"] = formatted_phone
                st.success(f"Phone number saved: {formatted_phone}")
            else:
                st.error(f"Invalid phone number: {formatted_phone}")
                return st.session_state.updated_final_data, False, "Invalid phone format"
        elif "name" in last_bot_msg:
            d["name"] = u_input
        elif "age" in last_bot_msg:
            try:
                d["age"] = int(u_input)
            except:
                d["age"] = u_input
        elif "gender" in last_bot_msg:
            d["gender"] = u_input
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


def check_patient_exists(cursor, email):
    # Checks if patient exists using email
    # Returns patient_id if found, None if not
    cursor.execute("SELECT patient_id FROM patients WHERE email = %s", (email,))
    result = cursor.fetchone()
    return result[0] if result else None


def update_single_record(cursor, table, columns, where_clause):
    # Updates existing record instead of inserting new one
    # Returns number of rows affected
    query = f"UPDATE {table} SET "
    for column, value in columns.items():
        query += f"{column} = %s, "
    query = query.rstrip(", ") + " WHERE " + " AND ".join([f"{column} = %s" for column in where_clause])
    cursor.execute(query, tuple(columns.values()) + tuple(where_clause.values()))
    return cursor.rowcount


def update_multiple_records(cursor, table, records, patient_id, record_type):
    # Updates related records (symptoms, medications, etc.)
    # First deletes existing records for the patient
    # Then inserts new records
    cursor.execute(f"DELETE FROM {table} WHERE patient_id = %s", (patient_id,))
    for record in records:
        cursor.execute(f"INSERT INTO {table} (patient_id, {record_type}) VALUES (%s, %s)", (patient_id, record))
    return cursor.rowcount


def verify_medical_terms(terms, term_type):
    # Implementation of verify_medical_terms function
    # This function should be implemented based on your specific requirements
    # For now, we'll just print the terms
    st.write(f"Verifying medical terms of type: {term_type}")
    for term in terms:
        st.write(f"- {term}")


def recover_failed_operation(operation_id):
    """Recover from a failed database operation"""
    try:
        # Load the operation state
        state = load_operation_state(operation_id)
        if not state:
            return False, "Operation state not found"
        
        # Connect to database
        conn = pymysql.connect(**db_config)
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        
        # If we have a patient_id and last update timestamp
        if state.get("patient_id") and state.get("last_update"):
            # Check if data has been modified since our last update
            current_update = get_last_update_timestamp(cursor, state["patient_id"])
            if current_update != state["last_update"]:
                return False, "Data has been modified since last operation"
            
            # Restore original data
            if state.get("original_data"):
                handle_table_operation(cursor, "patients", state["original_data"], 
                                    {"patient_id": state["patient_id"]})
                conn.commit()
                return True, "Successfully recovered to original state"
        
        return False, "Insufficient data for recovery"
    except Exception as e:
        return False, f"Recovery failed: {str(e)}"
    finally:
        if 'cursor' in locals():
            cursor.close()
        if 'conn' in locals():
            conn.close()


def date_serializer(obj):
    """Custom JSON serializer for handling dates"""
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    raise TypeError(f"Type {type(obj)} not serializable")


def main():
    # Header with logo and title
    col1, col2 = st.columns([1, 4])
    with col1:
        st.markdown("# 🏥")
    with col2:
        st.markdown("""
            <h1 style='color: #2c3e50;'>Medical Symptom Analysis</h1>
            <p style='color: #7f8c8d;'>AI-powered symptom analysis and recommendations</p>
        """, unsafe_allow_html=True)

    # Progress bar
    if "step" not in st.session_state:
        st.session_state.step = "intake"
    
    # Simplified steps
    steps = ["intake", "db_insert"]
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

    if st.session_state.step == "intake":
        st.markdown("""
            <div class='step-header'>
                <h2>Step 1: Symptom Analysis</h2>
                <p>Let's analyze your symptoms and provide recommendations</p>
            </div>
        """, unsafe_allow_html=True)
        
        patient_data, _, done = dynamic_medical_intake()
        if done:
            # The symptom analysis and mapping are now handled in dynamic_medical_intake
            pass

    elif st.session_state.step == "db_insert":
        st.markdown("""
            <div class='step-header'>
                <h2>Step 2: Saving Analysis</h2>
                <p>Saving your symptom analysis and recommendations</p>
            </div>
        """, unsafe_allow_html=True)

        # Prepare data for mapping
        if "patient_data" in st.session_state:
            try:
                # Create the final JSON structure
                final_json = {
                    "patient_data": st.session_state.patient_data,
                    "status": "complete"
                }
                
                # Map the data to DB schema
                mapped_result = mapping_collectedinfo_to_schema.get_mapped_output(final_json)
                
                # Save mapped data with date serialization
                with open("mapped_output.json", "w") as f:
                    json.dump(mapped_result, f, indent=2, default=date_serializer)
                
                # Show the mapped data
                with st.expander("View Mapped Data"):
                    st.json(mapped_result)
                
                # Insert into database
                if st.button("Save to Database", key="save_to_db"):
                    try:
                        result = insert_data_from_mapped_json(mapped_result)
                        if result.get("status") == "success":
                            st.success("✅ Analysis saved successfully!")
                            
                            # Show the analysis results
                            if "symptoms_analysis" in mapped_result:
                                analysis = mapped_result["symptoms_analysis"]
                                st.write("### Analysis Results")
                                
                                if "symptoms_identified" in analysis:
                                    st.write("*Identified Symptoms:*")
                                    for symptom in analysis["symptoms_identified"]:
                                        st.write(f"- {symptom}")
                                
                                if "severity_analysis" in analysis:
                                    st.write(f"*Severity Analysis:* {analysis['severity_analysis']}")
                                
                                if "recommended_specialists" in analysis:
                                    st.write("*Recommended Medical Specialties:*")
                                    for specialist in analysis["recommended_specialists"]:
                                        st.write(f"- {specialist}")
                                
                                if "rationale" in analysis:
                                    st.write(f"*Analysis Rationale:* {analysis['rationale']}")
                            
                            if st.button("Start New Analysis"):
                                # Clear session state
                                for key in list(st.session_state.keys()):
                                    del st.session_state[key]
                                st.session_state.step = "intake"
                                st.rerun()
                        else:
                            st.error("❌ Failed to save analysis")
                    except Exception as e:
                        st.error(f"❌ Database error: {str(e)}")
            except Exception as e:
                st.error(f"❌ Error preparing data: {str(e)}")
                # Add debugging information
                st.write("Debug info:")
                st.write("Patient data:", st.session_state.patient_data)
        else:
            st.error("No patient data available. Please complete the symptom analysis first.")
            if st.button("Return to Symptom Analysis"):
                st.session_state.step = "intake"
                st.rerun()

if __name__ == "__main__":
    main()
