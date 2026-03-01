import asyncio
import httpx

async def test_hf():
    print("Testing HuggingFace directly...")
    async with httpx.AsyncClient() as client:
        # Models
        resp = await client.get("https://huggingface.co/api/models?sort=trending&limit=5")
        models = resp.json()
        print(f"HF Models: {len(models)}")
        if models: print(f"Sample: {models[0].get('id')}")
        
        # Datasets
        resp = await client.get("https://huggingface.co/api/datasets?sort=trending&limit=5")
        datasets = resp.json()
        print(f"HF Datasets: {len(datasets)}")
        if datasets: print(f"Sample: {datasets[0].get('id')}")

async def test_ms():
    print("\nTesting ModelScope directly...")
    headers = {"Content-Type": "application/json"}
    async with httpx.AsyncClient() as client:
        # Models
        payload = {"PageNumber": 1, "PageSize": 5, "SortBy": "Chinese", "SortOrder": "Descending"}
        resp = await client.post("https://modelscope.cn/api/v1/models/search", json=payload, headers=headers)
        data = resp.json()
        models = data.get("Data", {}).get("Models", [])
        print(f"MS Models: {len(models)}")
        if models: print(f"Sample: {models[0].get('Name')}")
        
        # Datasets
        payload = {"PageNumber": 1, "PageSize": 5, "SortBy": "Chinese", "SortOrder": "Descending"}
        resp = await client.post("https://modelscope.cn/api/v1/datasets/search", json=payload, headers=headers)
        data = resp.json()
        datasets = data.get("Data", {}).get("Datasets", [])
        print(f"MS Datasets: {len(datasets)}")
        if datasets: print(f"Sample: {datasets[0].get('Name')}")

if __name__ == "__main__":
    asyncio.run(test_hf())
    asyncio.run(test_ms())
