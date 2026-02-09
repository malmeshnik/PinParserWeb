import requests
from django.conf import settings
from loguru import logger

class NineProxyService:
    def __init__(self, api_url=None):
        self.api_url = api_url or getattr(settings, "NINE_PROXY_API_URL", None)

    def get_proxy(self, num=1, filters=None):
        """
        Fetches proxies from 9Proxy API.
        Returns a list of proxy strings in format "host:port".
        """
        if not self.api_url:
            logger.warning("NINE_PROXY_API_URL is not configured")
            return []

        params = {
            "num": num,
            "t": 2, # JSON format
        }

        if filters:
            if filters.get("country"): params["country"] = filters["country"]
            if filters.get("state"): params["state"] = filters["state"]
            if filters.get("city"): params["city"] = filters["city"]
            if filters.get("zip"): params["zip"] = filters["zip"]
            if filters.get("isp"): params["isp"] = filters["isp"]

        try:
            # Assuming the API URL provided is the base URL like http://127.0.0.1:10101
            url = f"{self.api_url.rstrip('/')}/api/proxy"
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            if data.get("error"):
                logger.error(f"9Proxy API error: {data.get('message')}")
                return []

            return data.get("data", [])
        except Exception as e:
            logger.error(f"Failed to fetch from 9Proxy: {e}")
            return []

    def get_and_create_proxy_model(self, filters=None):
        from apps.proxies.models import Proxy, ProxyStatus

        proxies = self.get_proxy(num=1, filters=filters)
        if not proxies:
            return None

        proxy_str = proxies[0] # host:port
        try:
            host, port = proxy_str.split(":")
            proxy, created = Proxy.objects.get_or_create(
                host=host,
                port=port,
                defaults={
                    "name": f"9Proxy_{host}_{port}",
                    "status": ProxyStatus.ACTIVE,
                }
            )

            # Verify proxy health before returning
            if not proxy.check_health():
                msg = f"Fetched proxy {proxy} failed health check"
                logger.warning(msg)
                proxy.status = ProxyStatus.DEAD
                proxy.save(update_fields=['status'])
                return None

            return proxy
        except ValueError:
            logger.error(f"Invalid proxy format from 9Proxy: {proxy_str}")
            return None
