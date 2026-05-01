#!/usr/bin/env python3
"""
open-agent-ia - Web UI Entry Point

Run with: python app_web.py
Or: uvicorn web.server:app --reload --port 8000
"""

import uvicorn

if __name__ == "__main__":
    print("🤖 Starting open-agent-ia...")
    print("📍 Open http://localhost:8000 in your browser")
    print("📖 API docs at http://localhost:8000/docs")
    print()
    
    uvicorn.run(
        "web.server:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )
