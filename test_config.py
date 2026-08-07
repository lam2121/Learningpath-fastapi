import asyncio
from app.core.config import app_config
from app.core.ai.gemini import _default_ssl_context
import httpx

async def main():
    print("DISABLE_SSL_VERIFY:", app_config.DISABLE_SSL_VERIFY)
    verify_val = _default_ssl_context()
    print("verify_val:", verify_val)
    async with httpx.AsyncClient(verify=verify_val) as client:
        try:
            r = await client.get("https://generativelanguage.googleapis.com/v1beta/openai/chat/completions")
            print("Status: ", r.status_code)
        except Exception as e:
            print("Error:", type(e), e)

asyncio.run(main())
