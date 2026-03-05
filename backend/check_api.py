
import urllib.request
import json
import socket

def check_api(url):
    print(f"Checking {url}...")
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            data = json.loads(response.read().decode())
            print(f"Success! Status: {data.get('success')}")
            items = data.get('data', [])
            print(f"Item count: {len(items)}")
            if items:
                print(f"Sample domains: {[i.get('domain') for i in items[:5]]}")
                print(f"Sample source_ids: {[i.get('source_id') for i in items[:5]]}")
            return items
    except Exception as e:
        print(f"Failed: {e}")
        return None

if __name__ == "__main__":
    # Test all domains
    domains = ["all", "economy", "technology", "academic", "global"]
    for d in domains:
        check_api(f"http://localhost:5001/api/v1/newsflash?domain={d}")
        print("-" * 20)
