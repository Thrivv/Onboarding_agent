
context = """
Tell me my age based on the given info.-
    My name is satvik and I'm 23 years old. """

import requests
import time

API_KEY = "rpa_KN3HAWGAIXJVZPKFL7WD5JV8XYIZW27LWYZC2RYZ1wthhi"
ENDPOINT_ID = "1a59d70n24gnw1"
BASE_URL = f"https://api.runpod.ai/v2/{ENDPOINT_ID}"

def extract_main_content(output):
    try:
        # Get the tokens from the response
        tokens = output[0]['choices'][0]['tokens'][0]
        
        # Extract first answer (assuming it's between "Answer:" and the next newline)
        if "Answer:" in tokens:
            answer = tokens.split("Answer:")[1].split("\n")[0]
            return answer.strip()
        return tokens.strip()
    except Exception as e:
        return f"Error parsing output: {str(e)}"

# Step 1: Submit the job
headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}

data = {
    "input": {
        "prompt": """My name is xyz, can you tell me my name?""",
        "sampling_params": {
            "temperature": 0.2,  
            "max_tokens": 1000,     
            # "top_p": 3,        
            "repetition_penalty": 1.2
        }
    }
}

try:
    # Submit request
    response = requests.post(f"{BASE_URL}/run", headers=headers, json=data)
    response.raise_for_status()
    job = response.json()
    job_id = job["id"]

    # Poll for result
    while True:
        status_response = requests.get(f"{BASE_URL}/status/{job_id}", headers=headers)
        status_json = status_response.json()
        
        if status_json["status"] == "COMPLETED":
            raw_output = status_json["output"]
            clean_output = extract_main_content(raw_output)
            print("Answer:", clean_output)
            break
        elif status_json["status"] == "FAILED":
            print("Error: Job failed")
            break
        else:
            time.sleep(3)

except Exception as e:
    print(f"Error: {str(e)}")