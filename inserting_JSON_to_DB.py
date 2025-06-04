import os
import json
import pymysql
from dotenv import load_dotenv

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
    col_names = ", ".join(columns.keys())
    placeholders = ", ".join(["%s"] * len(columns))
    values = list(columns.values())
    query = f"INSERT INTO {table} ({col_names}) VALUES ({placeholders})"
    print(f"🔍 Executing query: {query}")
    print(f"🔍 With values: {values}")
    cursor.execute(query, values)

# Insert multi-record table
def insert_multiple_records(cursor, table, records):
    if not records:
        return
    col_names = ", ".join(records[0].keys())
    placeholders = ", ".join(["%s"] * len(records[0]))
    query = f"INSERT INTO {table} ({col_names}) VALUES ({placeholders})"
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

# Main logic
def insert_data_from_mapped_json(file_path):
    print(f"🔄 Loading data from file: {file_path}")
    data = load_mapped_output(file_path)
    
    print(f"📝 Loaded data structure type: {type(data)}")
    print(f"📝 Data content: {json.dumps(data, indent=2)}")

    conn = None
    cursor = None
    inserted_records = []

    try:
        print("🔄 Starting database insert...")
        conn = connect_to_db()
        cursor = conn.cursor(pymysql.cursors.DictCursor)

        # Start transaction
        conn.begin()
        
        # Handle both list and dict formats
        if isinstance(data, dict):
            data = [data]
        
        if not isinstance(data, list):
            raise ValueError(f"Expected list or dict, got {type(data)}")
            
        print(f"📝 Processing {len(data)} items...")
        
        for idx, item in enumerate(data):
            print(f"📝 Processing item {idx + 1}/{len(data)}")
            
            if not isinstance(item, dict):
                print(f"⚠️ Skipping invalid item type {type(item)}: {item}")
                continue
                
            table = item.get("table")
            if not table:
                print(f"⚠️ Skipping item without table name: {item}")
                continue

            print(f"📝 Processing table: {table}")
            
            if "columns" in item:
                print(f"📥 Inserting single record into '{table}': {item['columns']}")
                insert_single_record(cursor, table, item["columns"])
                # Verify the insertion
                cursor.execute("SELECT LAST_INSERT_ID()")
                last_id = cursor.fetchone()['LAST_INSERT_ID()']
                pk_column = get_primary_key_column(table)
                inserted_records.append({
                    "table": table,
                    "id": last_id,
                    "type": "single",
                    "pk_column": pk_column
                })
                print(f"✅ Inserted single record with ID: {last_id}")
                
            elif "records" in item:
                if not item["records"]:  # Skip if records is empty
                    print(f"⚠️ No records to insert for table {table}")
                    continue
                    
                print(f"📥 Inserting multiple records into '{table}': {item['records']}")
                insert_multiple_records(cursor, table, item["records"])
                # Get the number of affected rows
                affected = cursor.rowcount
                inserted_records.append({
                    "table": table,
                    "count": affected,
                    "type": "multiple"
                })
                print(f"✅ Inserted {affected} records")

        # Verify all insertions
        print("🔍 Verifying insertions...")
        for record in inserted_records:
            if record["type"] == "single":
                pk_column = record["pk_column"]
                cursor.execute(f"SELECT * FROM {record['table']} WHERE {pk_column} = %s", (record['id'],))
                result = cursor.fetchone()
                if not result:
                    raise Exception(f"Verification failed: Could not find inserted record in {record['table']} with {pk_column}={record['id']}")
                print(f"✅ Verified single record in {record['table']} with {pk_column}={record['id']}")
            else:
                print(f"✅ Inserted {record['count']} records into {record['table']}")

        # If we got here, all insertions were successful
        conn.commit()
        print("✅ All data inserted and verified in the database.")
        
        return {
            "status": "success",
            "inserted_records": inserted_records
        }
        
    except Exception as e:
        if conn:
            conn.rollback()
        print(f"❌ Error inserting data: {e}")
        raise
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

if __name__ == "__main__":
    insert_data_from_mapped_json("mapped_output.json")
    
