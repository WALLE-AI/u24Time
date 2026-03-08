import asyncio
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient
from httpx import AsyncClient

# Import the agents application and dependencies
from agents.server import create_agents_app
from agents.phase1_bettafish.analysis.query_agent import QueryAgent, SearchResult
from agents.phase1_bettafish.crawlers.topic_extractor import TopicExtractor
from utils.llm_client import LLMClient

# Initialize the distinct FastAPI APP
app = create_agents_app()
client = TestClient(app)

# ---------------------------------------------------------
# Unit Tests
# ---------------------------------------------------------

@pytest.fixture
def mock_llm_client():
    llm = LLMClient(api_key="sk-mock", base_url="http://mock", model="mock-model")
    return llm

@pytest.mark.asyncio
async def test_query_agent_formatting(mock_llm_client):
    """测试 QueryAgent 的格式化方法"""
    agent = QueryAgent(mock_llm_client)
    mock_results = [
        SearchResult(title="Result 1", url="http://1", content="Content 1"),
        SearchResult(title="Result 2", url="http://2", content="Content 2"),
    ]
    formatted = agent._format(mock_results)
    
    assert "[1] Result 1" in formatted
    assert "链接: http://1" in formatted
    assert "内容: Content 2" in formatted

@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_query_agent_reflection(MockAsyncClient, mock_llm_client):
    """测试 QueryAgent 的反思检索逻辑"""
    agent = QueryAgent(mock_llm_client)
    
    # Mock LLM response to simulate reflection output
    mock_post = AsyncMock()
    mock_post.return_value.json.return_value = {
        "choices": [{"message": {"content": "无需补充"}}]
    }
    
    mock_client_instance = AsyncMock()
    mock_client_instance.__aenter__.return_value = mock_client_instance
    mock_client_instance.post = mock_post
    MockAsyncClient.return_value = mock_client_instance
    
    result = await agent._reflect("test_query", "context")
    assert result == "无需补充"
    
    # Called LLM
    mock_post.assert_called_once()
    args, kwargs = mock_post.call_args
    assert "messages" in kwargs["json"]
    assert "test_query" in kwargs["json"]["messages"][1]["content"]

# ---------------------------------------------------------
# End-to-End API Route Tests
# ---------------------------------------------------------

def test_api_health():
    """测试独立应用的健康状况"""
    response = client.get("/agents/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "U24Time Agents API", "version": "1.0.0"}

def test_mirofish_ontology_generation_api():
    """测试 MiroFish Ontology API 的 Pydantic 验证和路由连通性"""
    # Providing missing fields should throw 422
    response = client.post("/agents/mirofish/ontology/generate", json={"document_texts": ["test"]})
    assert response.status_code == 422
    
    # Proper payload (we mock the LLM Dep to avoid real HTTP cost)
    with patch("agents.routers.mirofish.OntologyGenerator.generate", new_callable=AsyncMock) as mock_gen:
        mock_gen.return_value = {"entity_types": [{"name": "Person"}], "edge_types": []}
        
        response = client.post(
            "/agents/mirofish/ontology/generate", 
            json={"document_texts": ["test context"], "simulation_requirement": "Extract users"}
        )
        assert response.status_code == 200
        assert "entity_types" in response.json()
        assert response.json()["entity_types"][0]["name"] == "Person"

def test_bettafish_run_api():
    """测试 BettaFish 核心流水线触发接口"""
    # Overriding the DB dependency so it doesn't try to access SQLite
    from agents.dependencies import get_db
    
    async def override_get_db():
        # Yield a mock session
        mock_session = AsyncMock()
        yield mock_session
        
    app.dependency_overrides[get_db] = override_get_db
    
    # Mock background task pipeline so it doesn't actually hit DB without context
    with patch("agents.routers.bettafish.BettaFishPipeline.run_end_to_end", new_callable=AsyncMock) as mock_run:
        response = client.post(
            "/agents/bettafish/run",
            json={
                "query": "Test Event",
                "platforms": ["weibo"],
                "max_reflections": 1
            }
        )
    
    assert response.status_code == 200
    assert response.json()["status"] == "pending"
    assert "session_id" in response.json()
    
    # Clean up override
    app.dependency_overrides.clear()
