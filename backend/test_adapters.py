import asyncio
from crawler_engine.api_adapters.extended_adapters import HuggingFaceAdapter, SemanticScholarAdapter, PolymarketAdapter

async def test():
    try:
        hf = await HuggingFaceAdapter().fetch()
        print("HF:", len(hf))
    except Exception as e:
        print("HF Error:", e)

    try:
        s2 = await SemanticScholarAdapter().fetch_trending(query='AI')
        print("S2:", len(s2))
    except Exception as e:
        print("S2 Error:", e)

    try:
        poly = await PolymarketAdapter().fetch_active()
        print("Poly:", len(poly))
    except Exception as e:
        print("Poly Error:", e)

if __name__ == "__main__":
    asyncio.run(test())
