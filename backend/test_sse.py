import requests
import json
import sys

def main():
    print("Triggering run...")
    resp = requests.post("http://localhost:5001/agents/e2e/run", json={"topic": "auto", "is_heartbeat": False})
    if resp.status_code != 200:
        print(f"Error: {resp.text}")
        sys.exit(1)
        
    data = resp.json()
    run_id = data.get("run_id")
    print(f"Run ID: {run_id}")
    
    print("Listening to SSE...")
    response = requests.get(f"http://localhost:5001/agents/e2e/stream/{run_id}", stream=True)
    
    event = None
    data_str = ""
    for line in response.iter_lines():
        if line:
            l = line.decode('utf-8')
            if l.startswith("event: "):
                event = l[7:]
            elif l.startswith("data: "):
                data_str = l[6:]
                print(f"Event: {event}")
                print(f"Data: {data_str}")
                if event in ("run_complete", "error"):
                    sys.exit(0)
            
if __name__ == "__main__":
    main()
