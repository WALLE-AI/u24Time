import asyncio
import sys
import os

# Add backend to path
sys.path.append(os.path.join(os.getcwd(), "backend"))

from crawler_engine.api_adapters.extended_adapters import HuggingFaceAdapter, ModelScopeAdapter

async def test_adapters():
    print("Testing HuggingFaceAdapter...")
    hf = HuggingFaceAdapter()
    models = await hf.fetch_trending_models()
    print(f"HF Models found: {len(models)}")
    if models:
        print(f"First model: {models[0].get('id')}")
    
    datasets = await hf.fetch_trending_datasets()
    print(f"HF Datasets found: {len(datasets)}")
    if datasets:
        print(f"First dataset: {datasets[0].get('id')}")

    print("\nTesting ModelScopeAdapter...")
    ms = ModelScopeAdapter()
    ms_models = await ms.fetch_models()
    print(f"MS Models found: {len(ms_models)}")
    if ms_models:
        print(f"First model: {ms_models[0].get('Name')}")
    
    ms_datasets = await ms.fetch_datasets()
    print(f"MS Datasets found: {len(ms_datasets)}")
    if ms_datasets:
        print(f"First dataset: {ms_datasets[0].get('Name')}")

if __name__ == "__main__":
    asyncio.run(test_adapters())
