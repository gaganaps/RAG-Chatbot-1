"""High-performance asynchronous REST API server for the Groww Mutual Fund RAG Assistant."""

import argparse
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict
from aiohttp import web

from src.config import ACTIVE_SCHEMES, MANDATORY_DISCLAIMER
from src.pipeline.rag_engine import RAGEngine, RAGResponse

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

STATIC_DIR = Path(__file__).resolve().parent / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)


class APIServer:
    """REST API and Static Asset Server powering the Google Stitch Dark-Theme UI."""

    def __init__(self, rag_engine: RAGEngine = None):
        """Initialize API server with RAG Engine."""
        self.engine = rag_engine or RAGEngine()
        self.app = web.Application()
        self._setup_routes()
        self._setup_cors()

    def _setup_cors(self):
        """Enable CORS for external frontend runners (e.g. Vite, Next.js, Stitch live preview)."""
        @web.middleware
        async def cors_middleware(request, handler):
            if request.method == "OPTIONS":
                response = web.Response(status=204)
            else:
                response = await handler(request)

            response.headers["Access-Control-Allow-Origin"] = "*"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
            response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
            return response

        self.app.middlewares.append(cors_middleware)

    def _setup_routes(self):
        """Register API and static routes."""
        self.app.router.add_post("/api/chat", self.handle_chat)
        self.app.router.add_get("/api/schemes", self.handle_schemes)
        self.app.router.add_get("/api/health", self.handle_health)

        # Serve static assets (HTML, CSS, JS)
        if STATIC_DIR.exists():
            self.app.router.add_static("/static/", path=str(STATIC_DIR), name="static")
            self.app.router.add_get("/", self.handle_index)

    async def handle_index(self, request: web.Request) -> web.Response:
        """Serve main frontend index.html."""
        index_file = STATIC_DIR / "index.html"
        if index_file.exists():
            with open(index_file, "r", encoding="utf-8") as f:
                content = f.read()
            return web.Response(text=content, content_type="text/html")
        return web.Response(
            text="<h1>Groww MF Assistant API Running</h1><p>Static index.html not yet placed in src/ui/static/</p>",
            content_type="text/html",
        )

    async def handle_chat(self, request: web.Request) -> web.Response:
        """Process incoming user question through the guarded RAG pipeline.
        
        Expected JSON body:
            { "query": "What is the exit load for HDFC Balanced Advantage Fund?" }
        """
        try:
            data = await request.json()
            query = data.get("query", "").strip()

            if not query:
                return web.json_response(
                    {"error": "Query parameter is required."},
                    status=400,
                )

            logger.info(">>> USER QUERY: %r", query)
            # Execute full RAG pipeline (Input Guard -> Hybrid Search -> LLM -> Output Guard)
            rag_response: RAGResponse = self.engine.answer(query)
            logger.info("<<< RAG ANSWER (refusal=%s, latency=%.1fms): %s", rag_response.is_refusal, rag_response.latency_ms, rag_response.answer[:140].replace('\n', ' '))
            return web.json_response(rag_response.to_dict())

        except Exception as e:
            logger.error("Error processing /api/chat: %s", e, exc_info=True)
            return web.json_response(
                {
                    "error": "Internal server error occurred while processing query.",
                    "details": str(e),
                },
                status=500,
            )

    async def handle_schemes(self, request: web.Request) -> web.Response:
        """Return list of curated active mutual fund schemes."""
        schemes_data = [
            {
                "scheme_id": s.scheme_id,
                "scheme_name": s.scheme_name,
                "category": s.category,
                "amc": s.amc,
                "groww_url": s.groww_url,
            }
            for s in ACTIVE_SCHEMES.values()
        ]
        return web.json_response({
            "disclaimer": MANDATORY_DISCLAIMER,
            "schemes": schemes_data,
        })

    async def handle_health(self, request: web.Request) -> web.Response:
        """System health and metadata endpoint."""
        doc_count = self.engine.retriever.vector_store.collection.count()
        return web.json_response({
            "status": "healthy",
            "disclaimer": MANDATORY_DISCLAIMER,
            "indexed_documents": doc_count,
            "latest_crawl_date": "2026-11-15",
            "provider": self.engine.llm_client.provider,
            "model": self.engine.llm_client.model,
        })


def create_app() -> web.Application:
    """Factory creating the aiohttp application."""
    server = APIServer()
    return server.app


def main():
    """Start local web server with cloud PaaS $PORT and $HOST support."""
    default_port = int(os.environ.get("PORT", 8000))
    default_host = os.environ.get("HOST", "0.0.0.0" if "PORT" in os.environ else "127.0.0.1")

    parser = argparse.ArgumentParser(description="Groww Mutual Fund RAG API Server")
    parser.add_argument("--host", default=default_host, help=f"Host interface (default: {default_host})")
    parser.add_argument("--port", type=int, default=default_port, help=f"Port to listen on (default: {default_port})")
    args = parser.parse_args()

    app = create_app()
    logger.info("Starting Groww RAG Assistant Server at http://%s:%d", args.host, args.port)
    web.run_app(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
