
import urllib.request
import time

def listen_sse(url):
    print(f"Listening to SSE @ {url}...")
    try:
        # Use urlopen for streaming
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=60) as response:
            start_time = time.time()
            while time.time() - start_time < 30:
                line = response.readline().decode('utf-8')
                if not line:
                    break
                if line.startswith("data: "):
                    content = line[6:].strip()
                    try:
                        data = json.loads(content)
                        print(f"Event: {data.get('event')} | Domain: {data.get('domain')} | Source: {data.get('source_id')}")
                        if data.get('items'):
                            print(f"  Items: {len(data['items'])}")
                    except:
                        print(f"Data: {content}")
                elif line.strip():
                    print(f"Line: {line.strip()}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    import json
    listen_sse("http://localhost:5001/stream")
