import asyncio
import httpx

async def main():
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                "https://api.telegram.org"
            )
            print("Status:", response.status_code)
            print("Koneksi Telegram berhasil!")
    except Exception as e:
        print("Koneksi gagal:", repr(e))

asyncio.run(main())