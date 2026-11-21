"""In-memory integration tests for Phase 7: REST API Server and Static Asset Serving."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock
import pytest
from aiohttp.test_utils import make_mocked_request

from src.config import MANDATORY_DISCLAIMER
from src.ui.server import APIServer


@pytest.fixture(scope="module")
def api_server() -> APIServer:
    """Shared APIServer fixture."""
    return APIServer()


def test_ui_index_endpoint_serves_html(api_server: APIServer):
    """Verify GET / serves the Google Stitch Dark-Theme index.html."""
    async def _test():
        req = make_mocked_request("GET", "/")
        resp = await api_server.handle_index(req)
        assert resp.status == 200
        assert "text/html" in resp.headers["Content-Type"]
        assert "Groww FAQ Assistant" in resp.text
        assert "Facts only. No investment advice." in resp.text or "Facts-only. No investment advice." in resp.text
        assert "HDFC Balanced Advantage Fund" in resp.text

    asyncio.run(_test())


def test_ui_api_schemes_endpoint(api_server: APIServer):
    """Verify GET /api/schemes returns all 5 active mutual fund schemes."""
    async def _test():
        req = make_mocked_request("GET", "/api/schemes")
        resp = await api_server.handle_schemes(req)
        assert resp.status == 200
        data = json.loads(resp.text)
        assert "schemes" in data
        assert len(data["schemes"]) == 5
        scheme_ids = [s["scheme_id"] for s in data["schemes"]]
        assert "hdfc-flexi-cap" in scheme_ids
        assert "hdfc-silver-etf-fof" in scheme_ids
        assert "hdfc-balanced-advantage" in scheme_ids
        assert "hdfc-large-and-mid-cap" in scheme_ids
        assert "hdfc-manufacturing" in scheme_ids
        assert data["disclaimer"] == MANDATORY_DISCLAIMER

    asyncio.run(_test())


def test_ui_api_health_endpoint(api_server: APIServer):
    """Verify GET /api/health returns valid system metrics."""
    async def _test():
        req = make_mocked_request("GET", "/api/health")
        resp = await api_server.handle_health(req)
        assert resp.status == 200
        data = json.loads(resp.text)
        assert data["status"] == "healthy"
        assert data["indexed_documents"] >= 50
        assert data["latest_crawl_date"] == "2026-11-15"

    asyncio.run(_test())


def test_ui_api_chat_validation_empty_query(api_server: APIServer):
    """Verify POST /api/chat rejects empty query with 400 Bad Request."""
    async def _test():
        req = make_mocked_request("POST", "/api/chat")
        req.json = AsyncMock(return_value={"query": ""})
        resp = await api_server.handle_chat(req)
        assert resp.status == 400
        data = json.loads(resp.text)
        assert "error" in data

    asyncio.run(_test())


def test_ui_api_chat_factual_query(api_server: APIServer):
    """Verify POST /api/chat answers factual query with valid RAG response."""
    async def _test():
        req = make_mocked_request("POST", "/api/chat")
        req.json = AsyncMock(return_value={"query": "What is the exit load for HDFC Balanced Advantage Fund?"})
        resp = await api_server.handle_chat(req)
        assert resp.status == 200
        data = json.loads(resp.text)
        assert "query" in data
        assert "answer" in data
        assert not data["is_refusal"]
        assert "groww.in" in data["citation_url"]
        assert data["last_updated_date"] == "2026-11-15"
        assert data["confidence_score"] > 0.0
        assert data["latency_ms"] >= 0.0

    asyncio.run(_test())


def test_ui_api_chat_advisory_refusal(api_server: APIServer):
    """Verify POST /api/chat blocks investment advice queries with 0 LLM cost."""
    async def _test():
        req = make_mocked_request("POST", "/api/chat")
        req.json = AsyncMock(return_value={"query": "Which fund should I buy for 20% return?"})
        resp = await api_server.handle_chat(req)
        assert resp.status == 200
        data = json.loads(resp.text)
        assert data["is_refusal"]
        assert "amfiindia.com" in data["answer"].lower() or "amfiindia.com" in data["citation_url"]

    asyncio.run(_test())


def test_ui_cors_middleware():
    """Verify CORS middleware sets required headers."""
    async def _test():
        server = APIServer()
        handler = AsyncMock(return_value=MagicMock(headers={}))
        middleware = server.app.middlewares[0]

        # Test OPTIONS preflight
        req_options = make_mocked_request("OPTIONS", "/api/chat")
        resp_options = await middleware(req_options, handler)
        assert resp_options.status == 204
        assert resp_options.headers["Access-Control-Allow-Origin"] == "*"

        # Test POST CORS headers
        req_post = make_mocked_request("POST", "/api/chat")
        resp_post = await middleware(req_post, handler)
        assert resp_post.headers["Access-Control-Allow-Origin"] == "*"

    asyncio.run(_test())
