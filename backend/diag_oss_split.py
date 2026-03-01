import requests
import json

API_BASE = "http://localhost:5001"

def check_tech_domains():
    print("Checking Technology domain, OSS sub-domain...")
    try:
        url = f"{API_BASE}/api/v1/items?domain=technology&sub_domain=oss&limit=5"
        resp = requests.get(url)
        data = resp.json()
        print(f"OSS Items: {len(data.get('data', []))}")
        for i, item in enumerate(data.get("data", [])):
            print(f"  {i+1}. {item.get('title')} | Source: {item.get('source_id')}")
            
        print("\nChecking Technology domain, TECH_NEWS sub-domain...")
        url = f"{API_BASE}/api/v1/items?domain=technology&sub_domain=tech_news&limit=5"
        resp = requests.get(url)
        data = resp.json()
        print(f"TECH_NEWS Items: {len(data.get('data', []))}")
        for i, item in enumerate(data.get("data", [])):
            print(f"  {i+1}. {item.get('title')} | Source: {item.get('source_id')}")
    except Exception as e:
        print(f"Failed to connect: {e}")

if __name__ == "__main__":
    check_tech_domains()
