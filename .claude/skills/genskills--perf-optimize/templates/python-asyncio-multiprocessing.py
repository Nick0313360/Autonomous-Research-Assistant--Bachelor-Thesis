# asyncio - for I/O-bound concurrency
import asyncio

async def fetch_all(urls):
    sem = asyncio.Semaphore(20)  # limit concurrency
    async with aiohttp.ClientSession() as session:
        async def fetch(url):
            async with sem:
                async with session.get(url) as resp:
                    return await resp.json()
        return await asyncio.gather(*[fetch(u) for u in urls])

# multiprocessing - for CPU-bound parallelism (bypasses GIL)
from concurrent.futures import ProcessPoolExecutor
with ProcessPoolExecutor(max_workers=4) as executor:
    results = list(executor.map(cpu_heavy_fn, data_chunks))

# Use multiprocessing for CPU work, asyncio for I/O work - never mix blocking I/O into asyncio
# Use asyncio.to_thread() for legacy blocking calls in async code
