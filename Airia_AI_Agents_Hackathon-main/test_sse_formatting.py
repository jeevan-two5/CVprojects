import asyncio
from sse_starlette.sse import EventSourceResponse
from fastapi import FastAPI
import httpx
import threading
import uvicorn
import json

app = FastAPI()

@app.get("/events")
async def events():
    async def generator():
        # This is what routers/dashboard.py does
        yield 'data: {"test": "data"}\n\n'
    return EventSourceResponse(generator())

def run_server():
    uvicorn.run(app, host="127.0.0.1", port=8001, log_level="error")

async def test():
    t = threading.Thread(target=run_server, daemon=True)
    t.start()
    await asyncio.sleep(2) # Wait for server
    
    async with httpx.AsyncClient() as client:
        async with client.stream("GET", "http://127.0.0.1:8001/events") as response:
            print(f"Status: {response.status_code}")
            async for line in response.aiter_lines():
                if line:
                    print(f"Raw line: {line!r}")
                if "data:" in line:
                    # After first data line, we exit
                    break

if __name__ == "__main__":
    asyncio.run(test())
