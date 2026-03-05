
import urllib.request
import json

def test_summary():
    url = "http://localhost:5001/api/v1/ai/summary"
    data = json.dumps({"domain": "economy", "force": True}).encode('utf-8')
    req = urllib.request.Request(url, data=data, method='POST')
    req.add_header('Content-Type', 'application/json')
    
    print(f"Testing POST {url}...")
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            result = json.loads(response.read().decode())
            print(f"Success! Summary snippet: {str(result.get('data'))[:100]}...")
    except Exception as e:
        print(f"Failed: {e}")

if __name__ == "__main__":
    test_summary()
