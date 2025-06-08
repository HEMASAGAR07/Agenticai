import os
import json
import pymysql
from dotenv import load_dotenv
import uuid
import mysql.connector
from datetime import datetime

# Load environment variables from .env file (if you use one)
load_dotenv()

db_config = {
    "host": os.getenv("DB_HOST"),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
    "database": os.getenv("DB_NAME"),
    "port": int(os.getenv("DB_PORT", 3306))
}

# Connect to DB
def connect_to_db():
    return pymysql.connect(**db_config)

# Insert single-record table
def insert_single_record(cursor, table, columns):
    # Escape column names with backticks
    col_names = ", ".join([f"`{key}`" for key in columns.keys()])
    placeholders = ", ".join(["%s"] * len(columns))
    values = list(columns.values())
    query = f"INSERT INTO `{table}` ({col_names}) VALUES ({placeholders})"
    print(f"🔍 Executing query: {query}")
    print(f"🔍 With values: {values}")
    cursor.execute(query, values)

# Insert multi-record table
def insert_multiple_records(cursor, table, records):
    if not records:
        return
    # Escape column names with backticks
    col_names = ", ".join([f"`{key}`" for key in records[0].keys()])
    placeholders = ", ".join(["%s"] * len(records[0]))
    query = f"INSERT INTO `{table}` ({col_names}) VALUES ({placeholders})"
    values = [tuple(rec.values()) for rec in records]
    print(f"🔍 Executing query: {query}")
    print(f"🔍 With values: {values}")
    cursor.executemany(query, values)

# Load mapped JSON
def load_mapped_output(file_path):
    """Load and validate the mapped JSON data"""
    try:
        with open(file_path, "r") as f:
            content = f.read().strip()
            # Debug print
            print(f"📝 Raw file content: {content[:200]}...")  # Show first 200 chars
            
            # Try to parse the JSON content
            try:
                data = json.loads(content)
            except json.JSONDecodeError as e:
                print(f"❌ JSON parsing error at position {e.pos}: {e.msg}")
                print(f"Near text: {content[max(0, e.pos-20):min(len(content), e.pos+20)]}")
                raise ValueError(f"Invalid JSON format: {str(e)}")

            # Validate the structure
            if isinstance(data, (dict, list)):
                return data
            else:
                raise ValueError(f"Expected JSON object or array, got {type(data)}")
    except FileNotFoundError:
        raise FileNotFoundError(f"File not found: {file_path}")
    except Exception as e:
        raise ValueError(f"Error loading mapped output: {str(e)}")

def get_primary_key_column(table):
    """Return the primary key column name for each table"""
    primary_keys = {
        "patients": "patient_id",
        "symptoms": "symptom_id",
        "medications": "medication_id",
        "allergies": "allergy_id",
        "surgeries": "surgery_id",
        "appointments": "appointment_id",
        "doctors": "doctor_id"
    }
    return primary_keys.get(table, "id")

def update_single_record(cursor, table, columns, where_clause):
    """Update an existing record in the database"""
    # Escape column names with backticks
    set_clause = ", ".join([f"`{key}` = %s" for key in columns.keys()])
    where_str = " AND ".join([f"`{key}` = %s" for key in where_clause.keys()])
    
    query = f"UPDATE `{table}` SET {set_clause} WHERE {where_str}"
    values = list(columns.values()) + list(where_clause.values())
    
    print(f"🔄 Executing update query: {query}")
    print(f"🔄 With values: {values}")
    cursor.execute(query, values)
    return cursor.rowcount

def check_patient_exists(cursor, email):
    """Check if a patient exists and get their ID"""
    cursor.execute("SELECT patient_id FROM patients WHERE email = %s", (email,))
    result = cursor.fetchone()
    return result['patient_id'] if result else None

def update_multiple_records(cursor, table, records, patient_id, record_type):
    """Update or insert multiple records for a patient"""
    # First, delete existing records of this type for the patient
    cursor.execute(f"DELETE FROM {table} WHERE patient_id = %s", (patient_id,))
    
    # Then insert new records
    if records:
        # Add patient_id to each record
        for record in records:
            record['patient_id'] = patient_id
        
        col_names = ", ".join([f"`{key}`" for key in records[0].keys()])
        placeholders = ", ".join(["%s"] * len(records[0]))
        query = f"INSERT INTO `{table}` ({col_names}) VALUES ({placeholders})"
        values = [tuple(rec.values()) for rec in records]
        
        print(f"🔄 Executing {record_type} update query: {query}")
        print(f"🔄 With values: {values}")
        cursor.executemany(query, values)
    return cursor.rowcount

def get_last_update_timestamp(cursor, patient_id):
    """Get the last update timestamp for a patient"""
    cursor.execute("SELECT last_updated FROM patients WHERE patient_id = %s", (patient_id,))
    result = cursor.fetchone()
    return result['last_updated'] if result else None

def save_operation_state(operation_id, state_data):
    """Save the state of a database operation"""
    try:
        state_file = f"operation_state_{operation_id}.json"
        with open(state_file, 'w') as f:
            json.dump(state_data, f)
        return True
    except:
        return False

def load_operation_state(operation_id):
    """Load the state of a database operation"""
    try:
        state_file = f"operation_state_{operation_id}.json"
        if os.path.exists(state_file):
            with open(state_file, 'r') as f:
                return json.load(f)
    except:
        pass
    return None

def update_patient_timestamp(cursor, patient_id):
    """Update the last_updated timestamp for a patient"""
    cursor.execute(
        "UPDATE patients SET last_updated = CURRENT_TIMESTAMP WHERE patient_id = %s",
        (patient_id,)
    )

def verify_medical_terms(terms, term_type):
    """Verify medical terms against standard vocabulary"""
    # TODO: Implement actual medical term verification
    # For now, just check basic format
    if term_type == "medication":
        # Check if medication has dosage
        return all((" " in term and any(unit in term.lower() for unit in ["mg", "ml", "g"]) for term in terms))
    elif term_type == "symptom":
        # Check if symptom has duration
        return all(len(term) > 3 for term in terms)
    return True

def handle_table_operation(cursor, table, data, where_clause):
    """Handle a table operation with proper error handling"""
    try:
        # Build the query
        query = f"UPDATE {table} SET "
        set_values = []
        where_values = []
        
        # Add SET clause
        for key, value in data.items():
            set_values.append(f"{key} = %s")
        query += ", ".join(set_values)
        
        # Add WHERE clause
        query += " WHERE "
        for key in where_clause:
            where_values.append(f"{key} = %s")
        query += " AND ".join(where_values)
        
        # Execute query
        values = tuple(data.values()) + tuple(where_clause.values())
        cursor.execute(query, values)
        return True
    except Exception as e:
        raise Exception(f"Error in table operation: {str(e)}")

def load_json_file(file_path):
    """Load and parse a JSON file"""
    try:
        with open(file_path, 'r') as f:
            return json.load(f)
    except Exception as e:
        raise Exception(f"Error loading JSON file: {str(e)}")

def insert_data_from_mapped_json(json_file_path):
    """Insert data from mapped JSON file into the database"""
    try:
        # Load the JSON file
        mapped_data = load_json_file(json_file_path)
        
        # Connect to the database
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()

        # Get patient info
        patient_info = mapped_data.get("patient_info", {})
        
        # Insert into patients table
        patient_query = """
            INSERT INTO patients (full_name, email, phone, DOB, gender, address)
            VALUES (%s, %s, %s, %s, %s, %s)
        """
        patient_values = (
            patient_info.get("name"),  # We keep "name" here as it comes from the mapped data
            patient_info.get("email"),
            patient_info.get("phone"),
            patient_info.get("dob"),
            patient_info.get("gender"),
            patient_info.get("address")
        )
        cursor.execute(patient_query, patient_values)
        patient_id = cursor.lastrowid

        # Insert current symptoms into symptoms table
        current_symptoms = mapped_data.get("current_symptoms", [])
        if current_symptoms:
            symptoms_query = """
                INSERT INTO symptoms 
                (patient_id, symptom_description, severity, duration) 
                VALUES (%s, %s, %s, %s)
            """
            for symptom in current_symptoms:
                symptom_values = (
                    patient_id,
                    symptom.get("description"),
                    symptom.get("severity"),
                    symptom.get("duration")
                )
                cursor.execute(symptoms_query, symptom_values)

        # Insert specialist recommendations if available
        if "specialist_recommendations" in mapped_data:
            recommendations = mapped_data["specialist_recommendations"]
            specialists = recommendations.get("specialists", [])
            rationale = recommendations.get("rationale", "")
            
            for specialist in specialists:
                specialist_query = """
                    INSERT INTO specialist_recommendations 
                    (patient_id, specialist_type, rationale) 
                    VALUES (%s, %s, %s)
                """
                cursor.execute(specialist_query, (patient_id, specialist, rationale))

        # Insert appointment if available
        if "appointment" in mapped_data:
            appointment = mapped_data["appointment"]
            appointment_query = """
                INSERT INTO appointments 
                (patient_id, specialist, appointment_date, appointment_time, status) 
                VALUES (%s, %s, %s, %s, %s)
            """
            appointment_values = (
                patient_id,
                appointment.get("specialist"),
                appointment.get("date"),
                appointment.get("time"),
                appointment.get("status", "scheduled")
            )
            cursor.execute(appointment_query, appointment_values)

        # Commit the transaction
        conn.commit()
        
        return {"status": "success", "patient_id": patient_id}

    except Exception as e:
        if 'conn' in locals():
            conn.rollback()
        raise Exception(f"Database error: {str(e)}")
    
    finally:
        if 'cursor' in locals():
            cursor.close()
        if 'conn' in locals():
            conn.close()

def recover_failed_operation(operation_id):
    """Recover from a failed operation"""
    state = load_operation_state(operation_id)
    if not state:
        return {"status": "error", "message": "No recovery state found"}
    
    try:
        conn = connect_to_db()
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        
        if state.get("error"):
            # Rollback to last successful state
            if state.get("patient_id"):
                last_op = state.get("last_successful_operation")
                if last_op:
                    # Restore to last known good state
                    if "original_data" in state:
                        update_single_record(
                            cursor, "patients", 
                            state["original_data"]["columns"],
                            {"patient_id": state["patient_id"]}
                        )
                    
                    return {
                        "status": "recovered",
                        "patient_id": state["patient_id"],
                        "last_successful": last_op
                    }
        
        return {"status": "error", "message": "Unable to recover"}
        
    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

if __name__ == "__main__":
    insert_data_from_mapped_json("mapped_output.json")
    
