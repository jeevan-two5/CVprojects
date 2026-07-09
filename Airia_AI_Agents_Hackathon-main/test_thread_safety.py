import asyncio
import threading
import time
import json

clients = []

def emit_event(data):
    json_str = json.dumps(data)
    message = f"data: {json_str}\n\n"
    print(f"[Thread] Emitting message to {len(clients)} clients")
    for queue in clients:
        try:
            queue.put_nowait(message)
            print("[Thread] put_nowait success")
        except Exception as e:
            print(f"[Thread] Error: {e}")

async def main():
    queue = asyncio.Queue()
    clients.append(queue)
    
    print("[Main] Starting thread...")
    t = threading.Thread(target=lambda: emit_event({"test": "data"}))
    t.start()
    
    print("[Main] Waiting for message...")
    try:
        # Wait with timeout to see if it actually arrives
        message = await asyncio.wait_for(queue.get(), timeout=2.0)
        print(f"[Main] Received: {message!r}")
    except asyncio.TimeoutError:
        print("[Main] TIMEOUT - Message never arrived (likely thread-safety issue)")
    
    t.join()

if __name__ == "__main__":
    asyncio.run(main())
