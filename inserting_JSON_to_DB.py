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
    cursor.execute(query, values)

# Insert multi-record table
def insert_multiple_records(cursor, table, records):
    if not records:
        return
    col_names = ", ".join(records[0].keys())
    placeholders = ", ".join(["%s"] * len(records[0]))
    query = f"INSERT INTO {table} ({col_names}) VALUES ({placeholders})"
    values = [tuple(rec.values()) for rec in records]
    cursor.executemany(query, values)

# Load mapped JSON
def load_mapped_output(file_path):
    with open(file_path, "r") as f:
        return json.load(f)

# Main logic
def insert_data_from_mapped_json(file_path):
    data = load_mapped_output(file_path)
    conn = None
    cursor = None
    inserted_records = []

    try:
        print("🔄 Starting database insert...")
        conn = connect_to_db()
        cursor = conn.cursor()

        # Start transaction
        conn.begin()
        
        for item in data:
            table = item["table"]
            if "columns" in item:
                print(f"📥 Inserting single record into '{table}': {item['columns']}")
                insert_single_record(cursor, table, item["columns"])
                # Verify the insertion
                cursor.execute(f"SELECT LAST_INSERT_ID()")
                last_id = cursor.fetchone()[0]
                inserted_records.append({"table": table, "id": last_id, "type": "single"})
                
            elif "records" in item:
                print(f"📥 Inserting multiple records into '{table}': {item['records']}")
                insert_multiple_records(cursor, table, item["records"])
                # Get the number of affected rows
                affected = cursor.rowcount
                inserted_records.append({"table": table, "count": affected, "type": "multiple"})

        # Verify all insertions
        print("🔍 Verifying insertions...")
        for record in inserted_records:
            if record["type"] == "single":
                cursor.execute(f"SELECT * FROM {record['table']} WHERE id = {record['id']}")
                result = cursor.fetchone()
                if not result:
                    raise Exception(f"Verification failed: Could not find inserted record in {record['table']} with id {record['id']}")
                print(f"✅ Verified single record in {record['table']} with id {record['id']}")
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
    
