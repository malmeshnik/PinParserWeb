# import requests
# from bs4 import BeautifulSoup
# import json
# import re

# url = "https://ru.pinterest.com/pin/31666003624994128/"

# response = requests.get(url)
# with open("pin_page.html", "w", encoding="utf-8") as file:
#     file.write(response.text)

# pattern = re.compile(
#     r'__PWS_RELAY_REGISTER_COMPLETED_REQUEST__\([^,]+,\s*(\{.*?\})\s*\);',
#     re.DOTALL
# )

# match = pattern.search(response.text)

# if not match:
#     raise Exception("Relay JSON not found")

# raw_json = match.group(1)

# data = json.loads(raw_json)

# print(json.dumps(data, indent=2, ensure_ascii=False))

# from workers.pin_fetcher import PinFetcher
# from apps.parser.services.pin_parser import PinParser
# # from apps.accounts.models import PinterestAccount

# # account = PinterestAccount.objects.first()
# fetcher = PinFetcher("account")
# parser = PinParser()

# pin_url = "https://ru.pinterest.com/pin/31666003624994128/"
# html = fetcher.fetch(pin_url)
# # response = requests.get(pin_url)

# data = parser.parse(
#     html=html,
#     pin_url=pin_url,
#     keyword="python"
# )

# print(data)

# apps/parser/tasks/debug_pinterest.py

import asyncio
from celery import shared_task
from loguru import logger
from playwright.async_api import async_playwright


async def _run(proxy_host, proxy_port, username, password):
    cookies = [
    {
        "name": "csrftoken",
        "value": "9a3bc131081bdc14b13633e9b8fc1a52",
        "domain": "www.pinterest.com",
        "path": "/",
        "expires": 1801907497,
        "httpOnly": False,
        "secure": True,
        "sameSite": "Lax",
    },
    {
        "name": "_auth",
        "value": "1",
        "domain": ".pinterest.com",
        "path": "/",
        "expires": 1806923565,
        "httpOnly": True,
        "secure": True,
        "sameSite": "Lax",
    },
    {
        "name": "_pinterest_sess",
        "value": "TWc9PSZPVUtuYUw1akRsWGlWaEFhcVN2S2NGSFpWZ1YwUlhveFI3Y2cxUVZUUDVtV0FiamNFcHRhczZkMndhdFdweVVvYUtiT1BsNXQ1ZTVrNG1QRVNkZjUzS1Q1WU96V0FSOEJiS28rTURsWVN1RmhZTWRiQ1VhKzRoOGt1YTJJdk0wVkJlUE00T2VreDNKbVpZV0J1SWhmVFhmNW4vSTNaYmI4Szg0a3pUOTVZc3EyTGVjZW5LRnd6ekE5WUZuR1p6andUcUJRV2toL0R1MzRiV1pJR08ydUhPLzFkOHdTMUh5MXBCeS9SaGt6L1lHekxHb0Q2aTRoVzF6UW11UmVVTzh3dzZBdHlqSE1PL1lwNDY0RHBOQkdQUDBLVUNWRmtBSjI0bmJFYW9LN0IxQkVEQ1ErVXI2MUZTL0dJcXFPUnFTb2xwckMyTDFGV1JvdEZXVGQxWkdIbW1tOFUrWmxPS0JPbVFmVHRvOW0yazh5Q0liNTZMZWdJWFV6WDY0RFZGK0ZDWkJybEJSbVdrVFpkTWdMOFN3V2Y0NU5GeUxmMFlZM2NFSndoTXdOSzVzS1dsbkRrdU93NCtuL2JPV3dvU2h6U1J5SXBnWVNyUC9DYnFZYXVQK2tHNjlTVUZESmVVbHNmZ0V0YjVUdWwzcWNnSEtkOHFzVFdLNlJvQWxSTjdhckYvalpvZzgvMTdpMjVPRXZabERaa3BmZE5Qby9LWWxkQUtIQys1bWNhVWVJSzFjZmhkSElRNVNlQllpbUZxeVVwOWRHNm9GN3lXZ2VQSmZOWHpyQmJUdGxvZWJYTkJQK1ZpUWoxb0hYdXhFUDd2bWNzdFJzcFIxdHFvb3luUmdLcmFOMS9PVHNXN0FnYW80dkFHcjdzZHR1VGhQdWVhcTFyRHJuNnRWVStGWUNNeDczU2Uxa1JNSzBIU3pPWGozWGFSaC9WSXBaM2xucm05WkRHNWJTNjdrK0NnTEdVUTljQXYrOVdtRDBtbHBVamlRSm92NFJHcDVEOG5ERWFnS3dMakY2V2VHRWJ6RDcrTzRqbm1pcXY3dDhuYmxtU3d3S3g4TS9Qb25TdzRCQ0lXOG8xelZnU2hwUEl6UDRYNzA4OFF4OGE0Nkgrc2N2VnhpSm9TRThIWGw0eGNDbHIxemRsVjY3SCtCc2w0dmNMTUU4Um40eElmeFZ0Q2F6cGh0aXJ0bUdJQ3pObmhmaW9ndEl6UlM3LzV0K1MxN2J6eVp2NW5Lc0Frc284a1laaHpVem5TWUFKUkFUdjhFSUY3akpSYTJXSGJsQm5IZno0ZzBZeGtQbUp3TFFxS0QzNmx0bUlXZnVrMS9NRnp4TnhjS056dThwenlNZ2FjcXNhTFRPNURxWUtFK2VlNERHKy9TbXZCNTBDYk92VUxDOC9Lb0g0ZnlxOUxzM2taVmxlWWJ0czB4QmgxQS9LSjFjbE9vQjRoYWlhem5sbDFlZVc4b2orVGxOeUVRVExZNWcvTEFUWldUcjMrbFJxaW9PTm52d0lzQkY2Y2NWV2ZZc2NROEpNa0RyS0tWUU5zd2c2VmRMdG5qVUUzNVNZdEpVUUV0bXFTUmpJWlpudkZQNDVQejN0d1NZNHBRNDZ5STBwV3Nva0ZvaVJnWFpDVWc4TkNVbGxUU1Y3MzFLbkRJQ2xiMEVpeDd4SnVBeGIwd0ZKc2I3RExXTmVRS0FrblJoZWdOWUFObTU4NkUrOVI5cDJLVXNrdmUwTHlvRUZCQjJVb2lhR2tBUjhWRCtTa29TSU0rNEFMMGh0Z1A4dzBTUkdIY1gmdFlkL0xWOGVVaHRnbVcvdGNBMDRQT0g2cHdRPQ==",
        "domain": ".pinterest.com",
        "path": "/",
        "expires": 1806923565,
        "httpOnly": True,
        "secure": True,
        "sameSite": "None",
    },
]
    playwright = await async_playwright().start()

    proxy = {
        "server": f"http://{proxy_host}:{proxy_port}"
    }

    if username and password:
        proxy["username"] = username
        proxy["password"] = password

    browser = await playwright.chromium.launch(
        headless=True,
        proxy=proxy,
        args=["--disable-blink-features=AutomationControlled"]
    )

    context = await browser.new_context(
        viewport=None,
        locale="en-US"
    )

    page = await context.new_page()
    await context.add_cookies(cookies)

    try:
        # 🔥 1. перевірка IP
        await page.goto("https://api.ipify.org?format=json", timeout=20000)
        ip = await page.text_content("body")
        logger.info(f"[DEBUG] IP: {ip}")

        # 🔥 2. Pinterest home
        await page.goto("https://www.pinterest.com/", timeout=30000)
        await page.wait_for_timeout(5000)

        # 🔥 3. пошук
        await page.goto("https://www.pinterest.com/search/pins/?q=cats", timeout=30000)
        await page.wait_for_timeout(5000)

        content = await page.content()

        if "не вдалося знайти піни" in content.lower() or "no results" in content.lower():
            logger.error("[DEBUG] ❌ EMPTY RESULTS → SHADOW BAN")
        else:
            logger.success("[DEBUG] ✅ RESULTS FOUND")

        # 🔥 скрін
        await page.screenshot(path="debug_result.png", full_page=True)
        logger.info("[DEBUG] Screenshot saved: debug_result.png")

    except Exception as e:
        logger.error(f"[DEBUG] ERROR: {e}")

    finally:
        await browser.close()
        await playwright.stop()

if __name__ == "__main__":
    asyncio.run(_run(
        proxy_host="147.45.203.187",
        proxy_port=8000,
        username="FRnu5o",
        password="TBReFP"
    ))