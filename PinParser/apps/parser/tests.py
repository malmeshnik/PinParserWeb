import requests
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

from workers.pin_fetcher import PinFetcher
from apps.parser.services.pin_parser import PinParser
# from apps.accounts.models import PinterestAccount

# account = PinterestAccount.objects.first()
fetcher = PinFetcher("account")
parser = PinParser()

pin_url = "https://ru.pinterest.com/pin/31666003624994128/"
html = fetcher.fetch(pin_url)
# response = requests.get(pin_url)

data = parser.parse(
    html=html,
    pin_url=pin_url,
    keyword="python"
)

print(data)
