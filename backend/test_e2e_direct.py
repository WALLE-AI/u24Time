import asyncio
import os
import sys

# Ensure backend directory is in the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db.session import get_async_session
from utils.llm_client import LLMClient
from agents.pipeline.e2e_coordinator import EndToEndCoordinator
from agents.channel_dispatcher import ChannelDispatcher

async def main():
    print("Starting direct E2E Coordinator test...")
    target_topic = "auto"
    
    # Init dependencies
    llm = LLMClient()
    dispatcher = ChannelDispatcher()
    
    async with get_async_session() as db_session:
        coordinator = EndToEndCoordinator(
            db_session=db_session,
            llm=llm,
            channel_dispatcher=dispatcher,
            token_budget=12000
        )
        
        print(f"Running coordinator for topic: {target_topic}")
        try:
            result = await coordinator.run(topic=target_topic)
            print("\nCoordinator finished.")
            print("Status:", result.get("status"))
            
            if result.get("status") == "error":
                print("Error Details:", result.get("error"))
            else:
                print("Success!")
                print(f"Final Report Length: {len(str(result.get('report', '')))}")
                
        except Exception as e:
            print(f"\nUnhandled Exception during execution: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
