import requests
import json

API_BASE = "http://localhost:5001"

def check_tech_oss():
    print("Checking Technology domain, OSS sub-domain...")
    try:
        url = f"{API_BASE}/api/v1/items?domain=technology&sub_domain=oss&limit=10"
        resp = requests.get(url)
        data = resp.json()
        if data.get("success"):
            print(f"Total items found: {data.get('total')}")
            for i, item in enumerate(data.get("data", [])):
                print(f"{i+1}. {item.get('title')} | Source: {item.get('source_id')} | Sub: {item.get('sub_domain')}")
        else:
            print(f"Error: {data.get('msg')}")
    except Exception as e:
        print(f"Failed to connect: {e}")

if __name__ == "__main__":
    check_tech_oss()
