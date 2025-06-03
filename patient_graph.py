from langgraph.graph import StateGraph, END
from typing import TypedDict, Optional, List, Dict, Any

# Import agent functions
from collecting_info import (
    dynamic_medical_intake,
    post_analysis_and_followup,
    recommend_specialist,
    confirm_mandatory_fields,
)
from mapping_collectedinfo_to_schema import get_mapped_output
from inserting_JSON_to_DB import insert_data_from_mapped_json
from booking import main as book_appointment

# Define shared state
class PatientState(TypedDict):
    patient_data: Optional[dict]
    summary: Optional[str]
    followup_notes: Optional[str]
    recommended_specialist: Optional[list]
    specialist_rationale: Optional[str]
    mapped_json: Optional[list]
    db_inserted: bool
    booking_done: bool
    appointment_details: Optional[dict]

# Agent 1: Collect patient info
def agent_collect_info(state: PatientState, config):
    try:
        patient_data, summary = dynamic_medical_intake()
        final_data, notes = post_analysis_and_followup(patient_data)
        specialists, rationale = recommend_specialist(final_data)
        enriched_data = confirm_mandatory_fields({
            "summary": summary,
            "patient_data": final_data,
            "followup_notes": notes,
            "recommended_specialist": specialists,
            "specialist_rationale": rationale,
            "status": "complete"
        })
        print("DEBUG: confirm_mandatory_fields returned:", enriched_data)  # Add this line
        state["patient_data"] = enriched_data["patient_data"]
        state["summary"] = summary
        state["followup_notes"] = notes
        state["recommended_specialist"] = specialists
        state["specialist_rationale"] = rationale

        # Write patient_data to JSON file for Agent 2
        import json
        with open("patient_data.json", "w") as f:
            json.dump(state["patient_data"], f, indent=2)
        return state
    except Exception as e:
        print("Error in agent_collect_info:", e)
        raise

# Agent 2: Map to DB schema
def agent_map_schema(state: PatientState, config):
    # Read patient_data from JSON file
    import json
    with open("patient_data.json", "r") as f:
        patient_data = json.load(f)
    mapped_json = get_mapped_output(patient_data)
    state["mapped_json"] = mapped_json
    with open("mapped_output.json", "w") as f:
        if isinstance(mapped_json, str):
            f.write(mapped_json)
        else:
            f.write(json.dumps(mapped_json))
    return state

# Agent 3: Insert to DB
def agent_insert_db(state: PatientState, config):
    insert_data_from_mapped_json("mapped_output.json")
    state["db_inserted"] = True

    # Write booking input to JSON for Agent 4
    import json
    with open("booking_input.json", "w") as f:
        json.dump({
            "patient_data": state["patient_data"],
            "recommended_specialist": state["recommended_specialist"]
        }, f, indent=2)
    return state

# Agent 4: Book appointment
def agent_booking(state: PatientState, config):
    import json
    # Read patient_data from JSON file (output of Agent 1)
    with open("patient_data.json", "r") as f:
        patient_data = json.load(f)
    # Pass patient_data to book_appointment
    appointment_details = book_appointment()
    state["booking_done"] = True
    state["appointment_details"] = appointment_details
    return state

# Build LangGraph pipeline
graph = StateGraph(PatientState)
graph.add_node("CollectInfo", agent_collect_info)
graph.add_node("MapSchema", agent_map_schema)
graph.add_node("InsertDB", agent_insert_db)
graph.add_node("Booking", agent_booking)

graph.set_entry_point("CollectInfo")
graph.add_edge("InsertDB", "MapSchema")
graph.add_edge("MapSchema", "InsertDB")
graph.add_edge("InsertDB", "Booking")
graph.add_edge("Booking", END)

app = graph.compile()

if __name__ == "__main__":
    state = PatientState(
        patient_data=None,
        summary=None,
        followup_notes=None,
        recommended_specialist=None,
        specialist_rationale=None,
        mapped_json=None,
        db_inserted=False,
        booking_done=False,
        appointment_details=None,
    )
    print("🚦 Starting patient workflow...")
    result = app.invoke(state)
    print("🏁 Workflow complete.")
    print("Booking done:", result["booking_done"])
    print("Appointment Details:", result.get("appointment_details"))