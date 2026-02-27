import httpx
import asyncio

async def trigger():
    sids = [
        "academic.arxiv.cs_ai",
        "academic.arxiv.cs_lg",
        "academic.arxiv.cs_cv",
        "academic.arxiv.cs_cl",
        "academic.arxiv.econ",
        "academic.arxiv.physics",
        "academic.arxiv.q_bio",
        "academic.arxiv.math_st",
        "academic.huggingface.papers",
        "academic.semantic_scholar.trending"
    ]
    async with httpx.AsyncClient() as client:
        for sid in sids:
            print(f"Triggering {sid}...")
            try:
                resp = await client.post(f"http://localhost:5001/api/v1/scheduler/trigger/{sid}", timeout=10)
                print(f"  Result: {resp.status_code}")
            except Exception as e:
                print(f"  Error triggering {sid}: {e}")
            await asyncio.sleep(1)

if __name__ == "__main__":
    asyncio.run(trigger())
