import os
import json
import pymysql
from dotenv import load_dotenv
import uuid
import mysql.connector
from datetime import datetime
import google.generativeai as genai

# Load environment variables from .env file (if you use one)
load_dotenv()

# Configure Gemini
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
model = genai.GenerativeModel("gemini-1.5-flash")

db_config = {
    "host": os.getenv("DB_HOST"),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
    "database": os.getenv("DB_NAME"),
    "port": int(os.getenv("DB_PORT", 3306)),
    "charset": "utf8mb4",
    "use_unicode": True
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

def summarize_symptom_description(description):
    """Use LLM to summarize long symptom descriptions"""
    try:
        if len(description) < 1000:  # Only summarize if it's long
            return description
            
        prompt = f"""
Summarize the following medical symptom description in a concise way (maximum 200 characters) while preserving all important medical information:

{description}

Keep the summary professional and medically accurate. Include severity and duration if mentioned.
"""
        response = model.generate_content(prompt)
        summary = response.text.strip()
        return summary[:200]  # Ensure it doesn't exceed 200 chars
    except Exception as e:
        print(f"Warning: Error summarizing description: {str(e)}")
        return description[:200]  # Fallback to simple truncation

def insert_data_from_mapped_json(json_file_path):
    """Insert data from mapped JSON file into the database"""
    try:
        # Load the JSON file
        mapped_data = load_json_file(json_file_path)
        
        if not isinstance(mapped_data, list):
            raise ValueError("Expected mapped data to be a list of table operations")
        
        # Connect to the database with proper encoding
        conn = mysql.connector.connect(
            **db_config,
            collation="utf8mb4_unicode_ci"
        )
        cursor = conn.cursor()

        patient_id = None
        
        # Process each table operation
        for table_op in mapped_data:
            table_name = table_op.get("table")
            if not table_name:
                continue
                
            if table_name == "patients":
                # Insert patient data
                columns = table_op.get("columns", {})
                if columns:
                    col_names = ", ".join([f"`{key}`" for key in columns.keys()])
                    placeholders = ", ".join(["%s"] * len(columns))
                    query = f"INSERT INTO `{table_name}` ({col_names}) VALUES ({placeholders})"
                    values = list(columns.values())
                    cursor.execute(query, values)
                    patient_id = cursor.lastrowid
            
            elif table_name == "appointments" and patient_id:
                # Insert appointment data
                columns = table_op.get("columns", {})
                if columns:
                    # Add patient_id to the appointment
                    columns["patient_id"] = patient_id
                    col_names = ", ".join([f"`{key}`" for key in columns.keys()])
                    placeholders = ", ".join(["%s"] * len(columns))
                    query = f"INSERT INTO `{table_name}` ({col_names}) VALUES ({placeholders})"
                    values = list(columns.values())
                    cursor.execute(query, values)
            
            elif table_name == "symptoms" and patient_id:
                # Insert symptoms data
                records = table_op.get("records", [])
                for record in records:
                    # Add patient_id to the record
                    record["patient_id"] = patient_id
                    # Handle symptom description
                    if "symptom_description" in record:
                        record["symptom_description"] = str(record["symptom_description"])[:65535]  # Limit to MEDIUMTEXT size
                    col_names = ", ".join([f"`{key}`" for key in record.keys()])
                    placeholders = ", ".join(["%s"] * len(record))
                    query = f"INSERT INTO `{table_name}` ({col_names}) VALUES ({placeholders})"
                    values = list(record.values())
                    cursor.execute(query, values)

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
    
