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
from datetime import date, datetime, timedelta

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

def get_available_doctors():
    """Retrieve list of available doctors from database"""
    try:
        conn = pymysql.connect(**db_config)
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        
        # Get doctors with their booked appointments
        cursor.execute("""
            SELECT 
                d.doctor_id,
                d.full_name,
                d.specialization,
                d.experience_years,
                d.hospital_affiliation,
                d.available_days,
                d.available_slots,
                GROUP_CONCAT(
                    DISTINCT CONCAT(a.appointment_date, ' ', a.appointment_time)
                ) as booked_slots
            FROM doctors d
            LEFT JOIN appointments a ON d.doctor_id = a.doctor_id AND a.status = 1
            GROUP BY d.doctor_id
            ORDER BY d.full_name
        """)
        
        doctors = cursor.fetchall()
        
        # Process each doctor's booked slots
        for doctor in doctors:
            if doctor['booked_slots']:
                doctor['booked_slots'] = set(doctor['booked_slots'].split(','))
            else:
                doctor['booked_slots'] = set()
                
            # Convert available_slots from JSON if present
            if doctor['available_slots']:
                doctor['available_slots'] = json.loads(doctor['available_slots'])
            else:
                doctor['available_slots'] = []
                
        return doctors
    except Exception as e:
        st.error(f"Error fetching doctors: {str(e)}")
        return []
    finally:
        if 'cursor' in locals():
            cursor.close()
        if 'conn' in locals():
            conn.close()

def convert_time_format(time_str):
    """Convert time string to 24-hour format (HH:MM)"""
    try:
        # If time is already in 24-hour format
        if ":" in time_str and not any(x in time_str.upper() for x in ["AM", "PM"]):
            # Ensure consistent format HH:MM
            time_parts = time_str.split(":")
            if len(time_parts) == 2:
                hours = int(time_parts[0])
                minutes = int(time_parts[1])
                if 0 <= hours <= 23 and 0 <= minutes <= 59:
                    return f"{hours:02d}:{minutes:02d}"
            return None
        
        # Convert 12-hour format to 24-hour
        try:
            time_obj = datetime.strptime(time_str.strip(), "%I:%M %p")
            return time_obj.strftime("%H:%M")
        except ValueError:
            # Try alternative format without leading zeros
            time_obj = datetime.strptime(time_str.strip(), "%-I:%M %p")
            return time_obj.strftime("%H:%M")
    except Exception as e:
        st.write(f"Time conversion error for '{time_str}': {str(e)}")
        return None

def update_doctor_booked_slots(doctor_id, appointment_date, appointment_time):
    """Update the doctor's booked slots in the database"""
    try:
        conn = pymysql.connect(**db_config)
        cursor = conn.cursor()
        
        # First get current booked slots
        cursor.execute("""
            SELECT GROUP_CONCAT(
                CONCAT(appointment_date, ' ', appointment_time)
            ) as booked_slots
            FROM appointments 
            WHERE doctor_id = %s
        """, (doctor_id,))
        result = cursor.fetchone()
        
        # Create new booked slot
        new_slot = f"{appointment_date} {appointment_time}"
        
        # Combine existing and new slots
        current_slots = result[0].split(',') if result[0] else [] if result else []
        if new_slot not in current_slots:
            current_slots.append(new_slot)
        
        # Update appointments table
        cursor.execute("""
            INSERT INTO appointments 
            (doctor_id, appointment_date, appointment_time, patient_id, status) 
            VALUES (%s, %s, %s, %s, %s)
        """, (doctor_id, appointment_date, appointment_time, None, 1))
        
        conn.commit()
        return True
    except Exception as e:
        st.error(f"Error updating booked slots: {str(e)}")
        if 'conn' in locals():
            conn.rollback()
        return False
    finally:
        if 'cursor' in locals():
            cursor.close()
        if 'conn' in locals():
            conn.close()

def get_doctor_booked_slots(doctor_id):
    """Get the doctor's currently booked slots"""
    try:
        conn = pymysql.connect(**db_config)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT 
                CONCAT(appointment_date, ' ', appointment_time) as slot
            FROM appointments 
            WHERE doctor_id = %s
        """, (doctor_id,))
        
        results = cursor.fetchall()
        return [row[0] for row in results] if results else []
    except Exception as e:
        st.error(f"Error getting booked slots: {str(e)}")
        return []
    finally:
        if 'cursor' in locals():
            cursor.close()
        if 'conn' in locals():
            conn.close()

def is_slot_available(doctor, date, time):
    """Check if a time slot is available for the doctor"""
    try:
        # Convert time to 24-hour format for comparison
        time_24h = convert_time_format(time)
        if not time_24h:
            return False
            
        # Get real-time booked slots from database
        booked_slots = get_doctor_booked_slots(doctor['doctor_id'])
        
        # Format the requested slot in the same format as booked slots
        requested_slot = f"{date} {time_24h}"
        
        # Check if slot is already booked
        if requested_slot in booked_slots:
            return False
        
        # Check if day is in available days
        day_name = datetime.strptime(date, "%Y-%m-%d").strftime("%A")[:3]  # Get short day name (Mon, Tue, etc.)
        if doctor['available_days']:
            available_days = [day.strip()[:3] for day in doctor['available_days'].split(',')]  # Convert to short names
            if day_name not in available_days:
                return False
        
        # Check if time is in available slots
        if doctor['available_slots']:
            available_slots = json.loads(doctor['available_slots'])
            # Convert available slots to 24-hour format for comparison
            available_slots_24h = [convert_time_format(slot) for slot in available_slots]
            if time_24h not in available_slots_24h:
                return False
        
        return True
    except Exception as e:
        st.error(f"Error checking slot availability: {str(e)}")
        return False

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
    if "is_new_patient" not in st.session_state:
        st.session_state.is_new_patient = None
    if "selected_doctor" not in st.session_state:
        st.session_state.selected_doctor = None

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
        
        if st.session_state.is_new_patient:
            st.info("👋 Welcome! As a new patient, please provide your details below.")
            
            # Create a form for new patient details
            with st.form("new_patient_form"):
                col1, col2 = st.columns(2)
                
                with col1:
                    phone = st.text_input("📱 Phone Number", value=st.session_state.patient_data.get('phone', ''))
                    dob = st.date_input("🎂 Date of Birth")
                    gender = st.selectbox("⚧ Gender", ["", "Male", "Female", "Other"])
                
                with col2:
                    address = st.text_area("📍 Address")
                    allergies = st.text_area("⚠️ Known Allergies (if any)")
                    medications = st.text_area("💊 Current Medications (if any)")
                
                submit_new = st.form_submit_button("Submit Details")
                
                if submit_new:
                    # Validate phone number
                    is_valid_phone_num, phone_result = is_valid_phone(phone)
                    if not is_valid_phone_num:
                        st.error(f"Invalid phone number: {phone_result}")
                        return {}, "", False
                    
                    # Update patient data
                    st.session_state.patient_data.update({
                        'phone': phone_result,
                        'DOB': dob.strftime("%Y-%m-%d") if dob else None,
                        'gender': gender,
                        'address': address,
                        'allergies': allergies,
                        'medications': medications
                    })
                    
                    st.session_state.data_confirmed = True
                    st.session_state.in_health_assessment = True
                    st.rerun()
        else:
            # Show existing patient data
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
            
            st.info("👋 Welcome back! Please confirm your details are up to date.")
        
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
                st.session_state.is_new_patient = False
                st.rerun()
            else:
                # This is a new patient
                st.session_state.is_new_patient = True
                st.session_state.db_data_retrieved = True
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
{json.dumps(patient_data, indent=2, default=date_serializer)}

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


def get_all_slots_status(doctor_id, date):
    """Get all slots with their availability status"""
    try:
        conn = pymysql.connect(**db_config)
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        
        # First get all booked appointments for this date
        cursor.execute("""
            SELECT DATE_FORMAT(appointment_time, '%%H:%%i') as appointment_time 
            FROM appointments 
            WHERE doctor_id = %s 
            AND appointment_date = %s 
            AND status = 1
        """, (doctor_id, date))
        
        # Create set of booked times for O(1) lookup
        booked_slots = {row['appointment_time'] for row in cursor.fetchall()}
        
        # Now get doctor's schedule
        cursor.execute("""
            SELECT available_slots, available_days
            FROM doctors 
            WHERE doctor_id = %s
        """, (doctor_id,))
        
        doctor_schedule = cursor.fetchone()
        if not doctor_schedule or not doctor_schedule['available_slots']:
            st.warning("No schedule found for this doctor.")
            return []
            
        # Check if the selected date's day is in available days
        selected_day = datetime.strptime(date, "%Y-%m-%d").strftime("%A")[:3]
        available_days = [day.strip()[:3] for day in doctor_schedule['available_days'].split(',')]
        
        if selected_day not in available_days:
            st.info(f"Doctor is not available on {selected_day}days.")
            return []
        
        # Get all possible slots
        try:
            all_slots = json.loads(doctor_schedule['available_slots']) if isinstance(doctor_schedule['available_slots'], str) else doctor_schedule['available_slots']
        except Exception as e:
            st.error(f"Error parsing available slots: {str(e)}")
            return []
        
        # Debug information
        st.write("Debug Info (will be removed):")
        st.write(f"Total slots in schedule: {len(all_slots)}")
        st.write(f"Booked slots: {len(booked_slots)}")
        st.write("Booked times:", sorted(list(booked_slots)))
        
        # Filter available slots
        available_slots = []
        for slot in all_slots:
            try:
                # Convert to 24-hour format for comparison
                time_24h = convert_time_format(slot)
                if not time_24h:
                    st.write(f"Skipping invalid time format: {slot}")
                    continue
                    
                # Skip if slot is booked
                if time_24h in booked_slots:
                    st.write(f"Skipping booked slot: {time_24h}")
                    continue
                    
                # Convert to 12-hour format for display
                time_obj = datetime.strptime(time_24h, "%H:%M")
                display_time = time_obj.strftime("%I:%M %p").lstrip("0")
                
                available_slots.append({
                    "time": display_time,
                    "time_24h": time_24h,
                    "status": "available"
                })
            except Exception as e:
                st.write(f"Error processing slot {slot}: {str(e)}")
                continue
        
        # Debug information
        st.write(f"Available slots after filtering: {len(available_slots)}")
        st.write("Available times:", [slot["time"] for slot in available_slots])
        
        # Sort by time
        available_slots.sort(key=lambda x: datetime.strptime(x["time"], "%I:%M %p"))
        return available_slots
        
    except Exception as e:
        st.error(f"Error getting slots status: {str(e)}")
        st.write("Full error:", str(e))
        return []
    finally:
        if 'cursor' in locals():
            cursor.close()
        if 'conn' in locals():
            conn.close()

def reserve_appointment_slot(doctor_id, appointment_date, appointment_time, email):
    """Reserve an appointment slot in the database"""
    try:
        conn = pymysql.connect(**db_config)
        cursor = conn.cursor()
        
        # Start transaction
        cursor.execute("START TRANSACTION")
        
        # Check if slot is already booked
        cursor.execute("""
            SELECT COUNT(*) 
            FROM appointments 
            WHERE doctor_id = %s
            AND appointment_date = %s 
            AND appointment_time = %s
            AND status = 1
        """, (doctor_id, appointment_date, appointment_time))
        
        if cursor.fetchone()[0] > 0:
            cursor.execute("ROLLBACK")
            return False, "This slot is already booked."
        
        # Get patient_id from email
        cursor.execute("SELECT patient_id FROM patients WHERE email = %s", (email,))
        result = cursor.fetchone()
        if not result:
            cursor.execute("ROLLBACK")
            return False, "Patient not found. Please complete registration first."
        
        patient_id = result[0]
        
        # Check if patient already has an appointment at this time
        cursor.execute("""
            SELECT COUNT(*) 
            FROM appointments 
            WHERE patient_id = %s
            AND appointment_date = %s 
            AND appointment_time = %s
            AND status = 1
        """, (patient_id, appointment_date, appointment_time))
        
        if cursor.fetchone()[0] > 0:
            cursor.execute("ROLLBACK")
            return False, "You already have an appointment at this time."
        
        # Insert the appointment
        cursor.execute("""
            INSERT INTO appointments 
            (doctor_id, patient_id, appointment_date, appointment_time, status) 
            VALUES (%s, %s, %s, %s, 1)
        """, (doctor_id, patient_id, appointment_date, appointment_time))
        
        cursor.execute("COMMIT")
        return True, "Appointment slot reserved successfully!"
    except Exception as e:
        if 'cursor' in locals():
            cursor.execute("ROLLBACK")
        return False, f"Error reserving slot: {str(e)}"
    finally:
        if 'cursor' in locals():
            cursor.close()
        if 'conn' in locals():
            conn.close()

def init_session_state():
    """Initialize session state variables"""
    if "step" not in st.session_state:
        st.session_state.step = "intake"
    if "form_key" not in st.session_state:
        st.session_state.form_key = 0
    if "selected_date" not in st.session_state:
        st.session_state.selected_date = None
    if "last_doctor" not in st.session_state:
        st.session_state.last_doctor = None
    if "appointment_date_key" not in st.session_state:
        st.session_state.appointment_date_key = 0

def handle_date_change():
    """Handle date change event"""
    # Increment form key to force refresh
    st.session_state.form_key = st.session_state.get('form_key', 0) + 1
    st.session_state.appointment_date_key += 1
    # Clear previous selections
    if 'selected_time_24h' in st.session_state:
        del st.session_state.selected_time_24h

def main():
    # Initialize session state
    init_session_state()

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
    steps = ["intake", "specialist", "appointment", "db_insert"]
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
            st.session_state.step = "specialist"
            st.rerun()

    elif st.session_state.step == "specialist":
        st.markdown("""
            <div class='step-header'>
                <h2>Step 2: Specialist Recommendation</h2>
                <p>Based on your symptoms, we'll recommend appropriate specialists</p>
            </div>
        """, unsafe_allow_html=True)

        # Get specialist recommendations
        specialists, rationale = recommend_specialist(st.session_state.patient_data)
        
        if specialists:
            st.markdown("### Recommended Specialists")
            for specialist in specialists:
                st.write(f"👨‍⚕️ {specialist}")
            
            if rationale:
                st.markdown("### Recommendation Rationale")
                st.write(rationale)
            
            # Store recommendations in session state
            st.session_state.specialist_recommendations = {
                "specialists": specialists,
                "rationale": rationale
            }
            
            if st.button("Proceed to Appointment Booking"):
                st.session_state.step = "appointment"
                st.rerun()

    elif st.session_state.step == "appointment":
        st.markdown("""
            <div class='step-header'>
                <h2>Step 3: Schedule Appointment</h2>
                <p>Book an appointment with your recommended specialist</p>
            </div>
        """, unsafe_allow_html=True)

        if "specialist_recommendations" in st.session_state:
            specialists = st.session_state.specialist_recommendations["specialists"]
            rationale = st.session_state.specialist_recommendations["rationale"]
            
            st.markdown("### Recommended Specialists")
            for specialist in specialists:
                st.write(f"👨‍⚕️ {specialist}")
            
            if rationale:
                st.markdown("### Recommendation Rationale")
                st.write(rationale)
            
            # Get available doctors based on recommended specializations
            available_doctors = get_available_doctors()
            recommended_doctors = [
                doc for doc in available_doctors 
                if any(spec.lower() in doc['specialization'].lower() for spec in specialists)
            ]
            
            if not recommended_doctors:
                st.warning("No doctors available for the recommended specializations. Showing all available doctors.")
                recommended_doctors = available_doctors
            
            if recommended_doctors:
                st.markdown("### 👨‍⚕️ Available Doctors")
                
                # Date selection outside the form
                today = datetime.now().date()
                col1, col2 = st.columns([2, 1])
                
                with col1:
                    new_date = st.date_input(
                        "Select Date",
                        min_value=today + timedelta(days=1),
                        value=st.session_state.get('selected_date', today + timedelta(days=1)),
                        key=f"date_select_{st.session_state.appointment_date_key}"
                    )
                    
                    # Handle date change
                    if st.session_state.get('selected_date') != new_date:
                        st.session_state.selected_date = new_date
                        st.session_state.form_key = st.session_state.get('form_key', 0) + 1
                        st.session_state.appointment_date_key += 1
                        if 'selected_time_24h' in st.session_state:
                            del st.session_state.selected_time_24h
                        st.rerun()
                
                # Create appointment booking form
                appointment_form_key = f"appointment_form_{st.session_state.form_key}_{st.session_state.appointment_date_key}"
                with st.form(key=appointment_form_key):
                    # Create a formatted display name for each doctor
                    doctor_options = {
                        f"Dr. {doc['full_name']} - {doc['specialization']} ({doc['experience_years']} years) - {doc['hospital_affiliation']}": doc 
                        for doc in recommended_doctors
                    }
                    
                    selected_doctor_name = st.selectbox(
                        "Select Doctor",
                        options=list(doctor_options.keys()),
                        key=f"doctor_select_{st.session_state.form_key}",
                        help="Choose a doctor from the recommended specialists"
                    )

                    if selected_doctor_name:
                        selected_doctor = doctor_options[selected_doctor_name]
                        
                        # Show doctor's details
                        st.markdown("#### Doctor Details")
                        col1, col2 = st.columns(2)
                        with col1:
                            st.write("🏥 Hospital:", selected_doctor['hospital_affiliation'])
                            st.write("📚 Experience:", f"{selected_doctor['experience_years']} years")
                        with col2:
                            st.write("📅 Available Days:", selected_doctor['available_days'])
                            if selected_doctor['available_slots']:
                                try:
                                    available_slots = json.loads(selected_doctor['available_slots']) if isinstance(selected_doctor['available_slots'], str) else selected_doctor['available_slots']
                                    st.write("⏰ Available Slots:", ", ".join(available_slots))
                                except Exception as e:
                                    st.error(f"Error parsing available slots: {str(e)}")
                        
                        # Get available slots for selected doctor and date
                        available_slots = get_all_slots_status(
                            selected_doctor["doctor_id"], 
                            new_date.strftime("%Y-%m-%d")
                        )
                        
                        st.write("### 📅 Appointment Schedule")
                        st.write(f"Schedule for {new_date.strftime('%A, %B %d, %Y')}")
                        
                        if available_slots:
                            st.success(f"✅ Available Time Slots ({len(available_slots)})")
                            # Show available times in the selection
                            appointment_time = st.selectbox(
                                "Select a Time",
                                options=[slot["time"] for slot in available_slots],
                                key=f"time_select_{st.session_state.form_key}_{st.session_state.appointment_date_key}",
                                help="Choose from available time slots"
                            )
                            
                            # Store the 24h time format
                            if appointment_time:
                                selected_slot = next(
                                    (slot for slot in available_slots if slot["time"] == appointment_time),
                                    None
                                )
                                if selected_slot:
                                    st.session_state.selected_time_24h = selected_slot["time_24h"]
                            
                            # Show submit button
                            submit_appointment = st.form_submit_button("Book Appointment")
                            
                            if submit_appointment:
                                if not hasattr(st.session_state, 'selected_time_24h'):
                                    st.error("Please select an appointment time.")
                                    return
                                
                                # Double check slot availability
                                current_slots = get_all_slots_status(
                                    selected_doctor["doctor_id"], 
                                    new_date.strftime("%Y-%m-%d")
                                )
                                
                                if not any(slot["time_24h"] == st.session_state.selected_time_24h for slot in current_slots):
                                    st.error("❌ This slot is no longer available. Please select a different time.")
                                    st.session_state.form_key = st.session_state.get('form_key', 0) + 1
                                    st.rerun()
                                    return
                                
                                # Try to reserve the slot
                                success, message = reserve_appointment_slot(
                                    selected_doctor["doctor_id"],
                                    new_date.strftime("%Y-%m-%d"),
                                    st.session_state.selected_time_24h,
                                    st.session_state.patient_data.get("email", "")
                                )
                                
                                if success:
                                    st.success(f"✅ {message}")
                                    
                                    # Add appointment info to patient data
                                    st.session_state.patient_data["appointment"] = {
                                        "date": new_date.strftime("%Y-%m-%d"),
                                        "time": st.session_state.selected_time_24h,
                                        "status": "scheduled"
                                    }
                                    
                                    # Add selected doctor info
                                    st.session_state.patient_data["selected_doctor"] = {
                                        "doctor_id": selected_doctor["doctor_id"],
                                        "name": selected_doctor["full_name"],
                                        "specialization": selected_doctor["specialization"],
                                        "hospital": selected_doctor["hospital_affiliation"]
                                    }
                                    
                                    # Move to next step
                                    st.session_state.step = "db_insert"
                                    st.rerun()
                                else:
                                    st.error(f"❌ {message}")
                                    st.session_state.form_key = st.session_state.get('form_key', 0) + 1
                                    st.rerun()
                        else:
                            st.error("No available slots for this date")
                            st.info("💡 Suggestion: Try selecting a different date or check another doctor's availability")
                            st.form_submit_button("Book Appointment", disabled=True)
            else:
                st.error("No doctors available at the moment. Please try again later.")
                return

    elif st.session_state.step == "db_insert":
        st.markdown("""
            <div class='step-header'>
                <h2>Step 4: Saving Analysis</h2>
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
                
                # Add specialist recommendations if available
                if "specialist_recommendations" in st.session_state:
                    final_json["specialist_recommendations"] = st.session_state.specialist_recommendations
                
                # Map the data to DB schema
                mapped_result = mapping_collectedinfo_to_schema.get_mapped_output(final_json)
                
                # Save mapped data with date serialization
                mapped_file = "mapped_output.json"
                with open(mapped_file, "w") as f:
                    json.dump(mapped_result, f, indent=2, default=date_serializer)
                
                # Show the mapped data
                with st.expander("View Mapped Data"):
                    st.json(mapped_result)
                
                # Insert into database
                if st.button("Save to Database", key="save_to_db"):
                    try:
                        # Pass the file path to the insert function
                        result = insert_data_from_mapped_json(mapped_file)
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
                            
                            # Show appointment details if available
                            if "appointment" in st.session_state.patient_data and "selected_doctor" in st.session_state.patient_data:
                                st.write("### Appointment Details")
                                appt = st.session_state.patient_data["appointment"]
                                doctor = st.session_state.patient_data["selected_doctor"]
                                st.write(f"🗓️ Date: {appt['date']}")
                                st.write(f"⏰ Time: {appt['time']}")
                                st.write(f"👨‍⚕️ Doctor: Dr. {doctor['name']}")
                                st.write(f"🏥 Hospital: {doctor['hospital']}")
                            
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
