import asyncio
import httpx
import ssl
import certifi

async def main():
    print("Testing default httpx")
    async with httpx.AsyncClient() as client:
        try:
            r = await client.get("https://generativelanguage.googleapis.com/v1beta/openai/chat/completions")
            print("Default httpx: ", r.status_code)
        except Exception as e:
            print("Default httpx error:", e)

    print("\nTesting ssl.create_default_context()")
    async with httpx.AsyncClient(verify=ssl.create_default_context()) as client:
        try:
            r = await client.get("https://generativelanguage.googleapis.com/v1beta/openai/chat/completions")
            print("Default SSL: ", r.status_code)
        except Exception as e:
            print("Default SSL error:", e)
            
    print("\nTesting certifi.where()")
    async with httpx.AsyncClient(verify=certifi.where()) as client:
        try:
            r = await client.get("https://generativelanguage.googleapis.com/v1beta/openai/chat/completions")
            print("Certifi: ", r.status_code)
        except Exception as e:
            print("Certifi error:", e)

asyncio.run(main())
