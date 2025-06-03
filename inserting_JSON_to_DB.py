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
    conn = connect_to_db()
    cursor = conn.cursor()

    try:
        for item in data:
            table = item["table"]
            if "columns" in item:
                insert_single_record(cursor, table, item["columns"])
            elif "records" in item:
                insert_multiple_records(cursor, table, item["records"])
        conn.commit()
        print(" All data inserted into the database.")
    except Exception as e:
        conn.rollback()
        print(f" Error inserting data: {e}")
    finally:
        cursor.close()
        conn.close()

if __name__ == "__main__":
    insert_data_from_mapped_json("mapped_output.json")
    