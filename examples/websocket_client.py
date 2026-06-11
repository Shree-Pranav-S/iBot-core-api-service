import asyncio
import sys

import websockets


async def test_ws(token: str):
    uri = f"ws://localhost:8002/ws/interview?token={token}"
    print(f"Connecting to {uri}...")
    try:
        async with websockets.connect(uri) as websocket:
            print("Successfully connected! Sending a test message...")
            await websocket.send("Hello from test candidate client!")

            # Listen for messages
            while True:
                response = await websocket.recv()
                print(f"Received message from server: {response}")
    except Exception as e:
        print(f"Connection failed/closed: {e}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python examples/websocket_client.py <TOKEN_UUID>")
        sys.exit(1)

    token_arg = sys.argv[1]
    asyncio.run(test_ws(token_arg))
