import os
import json
from dotenv import load_dotenv
import google.generativeai as genai

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
        print("❌ JSON Parsing error:", e)
    return {}

# Phase 1: Initial intelligent questioning
def dynamic_medical_intake():
    conversation = []
    patient_data = {}

    intro =  """
You are an intelligent medical intake assistant.

Your job is to collect all *necessary health details* step-by-step, one question at a time. You must also *evaluate each answer* and ensure it's valid.

🔍 Your behavior should follow these rules:
- Do NOT ask all questions upfront.
- Do **not** accept fake, placeholder, or gibberish data. For example:
  - Invalid phone numbers like "1234567891" or too short.
  - Invalid or misspelled emails like "abc@gamial.com".
  - Unrealistic names (e.g., "asd asd", "xxx").
  - Empty strings or nonsense entries (e.g., "bal bala", "asdf").
  
- Ask only 1 question at a time.
- Decide the next question based on prior answers.
- SKIP irrelevant questions automatically.
- STOP when you've collected enough (not too much, not too little).
- Validate each patient response for correctness.
  - If answer is unclear, nonsense (e.g., "bal bala"), irrelevant, or incomplete, re-ask or prompt the user to clarify.
  - Examples of bad answers: gibberish, unknown terms, contradictions, wrong formats.
  - Politely ask them to rephrase or clarify only when needed.

⚠️ IMPORTANT: Be sure to cover all these critical areas during the intake:
- Patient's name
- Current symptoms and complaints
- Past medical history including any surgeries or hospitalizations
- Current medications the patient is taking
- Family medical history if relevant
- Lifestyle factors if relevant (e.g., smoking, alcohol)

📝 Your final output should ONLY be a JSON object like:
{
  "summary": "Short summary of findings",
  "patient_data": {
    "name": "Alice",
    "age": 34,
    "gender": "Female",
    "symptoms": "...",
    "past_surgeries": "...",
    "current_medications": "...",
    "allergies": "...",
    ...
  },
  "status": "complete"
}

Now begin by asking the first question to the patient.
"""


    # Start the first chat
    response = model.start_chat(history=[])
    reply = response.send_message(intro + "\n\nStart by asking the first question to the patient.")

    while True:
        question = reply.text.strip()
        print(f"\n🤖 {question}")
        
        # Validate non-empty user input
        user_input = ""
        while not user_input:
            user_input = input("👤 ").strip()
            if not user_input:
                print("⚠️ Please enter a valid response (cannot be empty).")

        # Send user input
        reply = response.send_message(user_input)

        # Check for final structured output
        final_output = extract_json(reply.text)
        if final_output.get("status") == "complete":
            patient_data = final_output.get("patient_data", {})
            summary = final_output.get("summary", "")
            break

    print("\n✅ Initial intake complete. Running final completeness analysis...\n")
    return patient_data, summary

# Phase 2: Post-analysis and follow-up questioning
def post_analysis_and_followup(patient_data):
    followup_prompt = f"""
You are a medical assistant reviewing the following patient data:

{json.dumps(patient_data, indent=2)}

🎯 TASK:
- Carefully analyze the above patient data.
- Identify if any *critical required* medical details are missing, inconsistent, or unclear.
- Do NOT ask unnecessary or overly detailed questions.
- Ask only *essential follow-up questions* one at a time to complete missing key information.
- If the data is sufficient and complete for medical intake purposes, return a JSON with status: "finalized".
- After collecting all required info, return JSON like:
{{
  "updated_patient_data": {{ ... }},
  "notes": "Summary of what was added or clarified",
  "status": "finalized"
}}

Begin your focused analysis now.
"""

    response = model.start_chat(history=[])
    reply = response.send_message(followup_prompt)

    updated_data = dict(patient_data)  # clone
    while True:
        if "```json" in reply.text or "{" in reply.text:
            result = extract_json(reply.text)
            if result.get("status") == "finalized":
                return result.get("updated_patient_data", updated_data), result.get("notes", "")
        
        print(f"\n🤖 {reply.text.strip()}")

        user_input = ""
        while not user_input:
            user_input = input("👤 ").strip()
            if not user_input:
                print("⚠️ Please enter a valid response (cannot be empty).")

        reply = response.send_message(user_input)


# Phase 3: Specialist recommendation based on collected data
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

    # Try extracting JSON until 'done' status or fallback
    for _ in range(3):  # retry a few times if needed
        result = extract_json(reply.text)
        if result.get("status") == "done":
            return result.get("recommended_specialist", []), result.get("rationale", "")
        else:
            # If not done, you can optionally continue the conversation or break
            break

    # If extraction failed or no 'done' status, fallback return
    print("⚠️ Warning: Specialist recommendation not found in LLM response.")
    print("LLM response was:\n", reply.text)
    return [], ""

def confirm_mandatory_fields(final_json):
    prompt = f"""
You are a medical assistant. 

Given the patient data JSON below, check if ALL mandatory fields are present.

Mandatory fields:

- From Patient: "name" (maps to full_name), "email", "age", "gender", "Ph Number" (phone), "Address" (address)
- If "symptoms" == "yes": "symptom_list" required (comma-separated string)
- If "allergies" == "yes": "allergy_list" required
- If "medications" == "yes": "medication_list" required
- If "past_history" == "yes": "past_illness" required
- If surgery info present: "procedure_name", "surgery_date", "hospital_name" required

If any mandatory fields are missing or empty, ask the patient directly to provide them one by one.

If all mandatory fields are present, reply with:

{{"status": "confirmed", "message": "All mandatory fields present."}}

Otherwise, ask only for missing fields one at a time.

Here is the patient data:

{json.dumps(final_json, indent=2)}

Begin your check and ask for missing info as needed.
"""

    response = model.start_chat(history=[])
    reply = response.send_message(prompt)

    updated_data = dict(final_json)  # copy original data

    while True:
        print(f"\n🤖 {reply.text.strip()}")
        output = extract_json(reply.text)

        if output.get("status") == "confirmed":
            print("✅ Mandatory fields confirmed complete.")
            # Return updated data with confirmation message
            return updated_data

        # Expect patient to respond with answer to missing field
        user_input = ""
        while not user_input:
            user_input = input("👤 ").strip()
            if not user_input:
                print("⚠️ Please provide a valid response.")

        # Heuristic: try to detect what field the LLM is asking for, or
        # simply append user's answer under a likely field in updated_data
        # (you can improve this with regex or prompt engineering)

        # Basic example:
        # Look at last bot message, parse which field is requested
        last_bot_msg = reply.text.lower()

        if "name" in last_bot_msg:
            updated_data["patient_data"]["name"] = user_input
        elif "email" in last_bot_msg:
            updated_data["patient_data"]["email"] = user_input
        elif "age" in last_bot_msg:
            try:
                updated_data["patient_data"]["age"] = int(user_input)
            except:
                updated_data["patient_data"]["age"] = user_input
        elif "gender" in last_bot_msg:
            updated_data["patient_data"]["gender"] = user_input
        elif "phone" in last_bot_msg or "ph number" in last_bot_msg:
            updated_data["patient_data"]["phone"] = user_input
        elif "address" in last_bot_msg:
            updated_data["patient_data"]["address"] = user_input
        elif "symptom" in last_bot_msg:
            updated_data["patient_data"]["symptom_list"] = user_input
            updated_data["patient_data"]["symptoms"] = "yes"
        elif "allergy" in last_bot_msg:
            updated_data["patient_data"]["allergy_list"] = user_input
            updated_data["patient_data"]["allergies"] = "yes"
        elif "medication" in last_bot_msg:
            updated_data["patient_data"]["medication_list"] = user_input
            updated_data["patient_data"]["medications"] = "yes"
        elif "past illness" in last_bot_msg:
            updated_data["patient_data"]["past_illness"] = user_input
            updated_data["patient_data"]["past_history"] = "yes"
        elif "procedure name" in last_bot_msg:
            updated_data["patient_data"]["procedure_name"] = user_input
        elif "surgery date" in last_bot_msg:
            updated_data["patient_data"]["surgery_date"] = user_input
        elif "hospital name" in last_bot_msg:
            updated_data["patient_data"]["hospital_name"] = user_input

        # Send user input to LLM for next step
        reply = response.send_message(user_input)

if __name__ == "__main__":
    patient_data, summary = dynamic_medical_intake()
    final_data, notes = post_analysis_and_followup(patient_data)
    specialists, rationale = recommend_specialist(final_data)

    final_output = {
        "summary": summary,
        "patient_data": final_data,
        "followup_notes": notes,
        "recommended_specialist": specialists,
        "specialist_rationale": rationale,
        "status": "complete"
    }

    print("\n✅ Final Output Before Mandatory Check:\n")
    print(json.dumps(final_output, indent=2))

    # Phase 4: Confirm and enrich all mandatory fields with user input
    enriched_data = confirm_mandatory_fields(final_output)

    final_output["patient_data"] = enriched_data["patient_data"]  # update with enriched fields

    # Save final enriched output
    with open("final_patient_summary.json", "w") as f:
        json.dump(final_output, f, indent=2)

    print("\n✅ Final JSON with mandatory fields updated saved.")
