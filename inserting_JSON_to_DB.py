import os
import json
import pymysql
from dotenv import load_dotenv
import uuid

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
    """Save operation state for recovery"""
    with open(f"operation_state_{operation_id}.json", "w") as f:
        json.dump(state_data, f, indent=2)

def load_operation_state(operation_id):
    """Load operation state for recovery"""
    try:
        with open(f"operation_state_{operation_id}.json", "r") as f:
            return json.load(f)
    except FileNotFoundError:
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

def handle_table_operation(cursor, operation_type, table, data, patient_id):
    """Handle database operations with proper error handling"""
    try:
        if operation_type == "update":
            affected = update_single_record(cursor, table, data, {"patient_id": patient_id})
        elif operation_type == "insert":
            insert_single_record(cursor, table, data)
            affected = cursor.lastrowid
        elif operation_type == "multiple":
            affected = update_multiple_records(cursor, table, data, patient_id, table)
        
        print(f"✅ {operation_type.capitalize()} successful for {table}")
        return {"status": "success", "affected": affected}
    except Exception as e:
        print(f"❌ Error in {operation_type} for {table}: {str(e)}")
        raise

def insert_data_from_mapped_json(file_path):
    print(f"🔄 Loading data from file: {file_path}")
    data = load_mapped_output(file_path)
    
    operation_id = str(uuid.uuid4())
    conn = None
    cursor = None
    inserted_records = []
    
    try:
        conn = connect_to_db()
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        
        # Start transaction
        conn.begin()
        
        # First, find patient data
        patient_data = next((item for item in data if item.get("table") == "patients"), None)
        if not patient_data:
            raise ValueError("No patient data found in mapped JSON")
        
        email = patient_data["columns"].get("email")
        if not email:
            raise ValueError("Email is required for patient identification")
        
        # Check if patient exists and get last update timestamp
        patient_id = check_patient_exists(cursor, email)
        if patient_id:
            last_update = get_last_update_timestamp(cursor, patient_id)
            print(f"✅ Found existing patient with ID: {patient_id}, last updated: {last_update}")
            
            # Save current state before updates
            save_operation_state(operation_id, {
                "patient_id": patient_id,
                "last_update": last_update,
                "original_data": patient_data
            })
            
            # Update patient record
            result = handle_table_operation(
                cursor, "update", "patients", 
                patient_data["columns"], patient_id
            )
            inserted_records.append({
                "table": "patients",
                "id": patient_id,
                "type": "update",
                "action": "updated"
            })
        else:
            # Create new patient record
            print("📥 Creating new patient record...")
            result = handle_table_operation(
                cursor, "insert", "patients", 
                patient_data["columns"], None
            )
            patient_id = result["affected"]
            save_operation_state(operation_id, {
                "patient_id": patient_id,
                "action": "insert",
                "original_data": patient_data
            })
            inserted_records.append({
                "table": "patients",
                "id": patient_id,
                "type": "single",
                "action": "inserted"
            })
        
        # Process other tables
        for item in data:
            if item.get("table") == "patients":
                continue
            
            table = item.get("table")
            if not table or "records" not in item:
                continue
            
            # Verify medical terms if applicable
            if table in ["medications", "symptoms", "allergies"]:
                terms = [record.get(f"{table[:-1]}_name", "") for record in item["records"]]
                if not verify_medical_terms(terms, table[:-1]):
                    raise ValueError(f"Invalid {table} format detected")
            
            # Update records
            result = handle_table_operation(
                cursor, "multiple", table, 
                item["records"], patient_id
            )
            inserted_records.append({
                "table": table,
                "count": result["affected"],
                "type": "multiple",
                "action": "updated"
            })
        
        # Update timestamp
        update_patient_timestamp(cursor, patient_id)
        
        # Verify all operations
        print("🔍 Verifying database operations...")
        for record in inserted_records:
            if record["type"] in ["single", "update"]:
                cursor.execute(
                    f"SELECT * FROM {record['table']} WHERE patient_id = %s",
                    (patient_id,)
                )
                if not cursor.fetchone():
                    raise Exception(f"Verification failed for {record['table']}")
            else:
                cursor.execute(
                    f"SELECT COUNT(*) as count FROM {record['table']} WHERE patient_id = %s",
                    (patient_id,)
                )
                if not cursor.fetchone()['count']:
                    raise Exception(f"Verification failed for {record['table']}")
        
        # If we got here, all operations were successful
        conn.commit()
        print("✅ All data operations completed successfully")
        
        # Clean up operation state
        try:
            os.remove(f"operation_state_{operation_id}.json")
        except:
            pass
        
        return {
            "status": "success",
            "patient_id": patient_id,
            "operations": inserted_records
        }
        
    except Exception as e:
        if conn:
            conn.rollback()
        print(f"❌ Error in database operation: {e}")
        
        # Save error state for recovery
        save_operation_state(operation_id, {
            "error": str(e),
            "patient_id": patient_id if 'patient_id' in locals() else None,
            "last_successful_operation": inserted_records[-1] if inserted_records else None
        })
        
        raise
    finally:
        if cursor:
            cursor.close()
        if conn:
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
    
