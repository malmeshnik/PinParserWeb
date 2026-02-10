import requests
from django.conf import settings
from loguru import logger
from django.db.models import Max

from apps.proxies.models import Proxy, ProxyStatus


class NineProxyService:
    def __init__(self, api_url=None):
        self.api_url = api_url or getattr(settings, "NINE_PROXY_API_URL", None)

    def _build_params(self, num=1, port=None, filters=None):
        params = {
            "num": num,
            "t": 2,
        }

        if port:
            params["port"] = port

        if filters:
            params.update({
                k: v for k, v in filters.items()
                if v is not None
            })

        return params

    def _request_proxy(self, params):
        url = f"{self.api_url.rstrip('/')}/api/proxy"
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()

        data = response.json()
        if data.get("error"):
            raise RuntimeError(data.get("message"))

        return data.get("data", [])

    def _get_next_port(self):

        last_port = Proxy.objects.aggregate(
            max_port=Max("port")
        )["max_port"]

        return (last_port or 60000) + 1

    def get_proxy(self, proxy: Proxy, filters=None):
        if not self.api_url:
            logger.warning("NINE_PROXY_API_URL is not configured")
            return None

        if proxy.port:
            if proxy.check_health():
                return proxy

            logger.warning(f"Proxy {proxy} is dead, refreshing on same port")
            return self._refresh_proxy(proxy, filters)

        return self._create_new_proxy(proxy, filters)

    def _create_new_proxy(self, proxy: Proxy, filters: dict):
        

        port = self._get_next_port()
        params = self._build_params(num=1, port=port, filters=filters)

        try:
            proxies = self._request_proxy(params)
            if not proxies:
                return None

            host, _ = proxies[0].split(":")

            proxy.host = host
            proxy.port = port
            proxy.status = ProxyStatus.ACTIVE
            proxy.fail_count = 0
            proxy.save(update_fields=["host", "port", "status", "fail_count"])

            if not proxy.check_health():
                return None

            return proxy

        except Exception as e:
            logger.error(f"Failed to create proxy: {e}")
            return None

    def _refresh_proxy(self, proxy, filters):

        params = self._build_params(
            num=1,
            port=proxy.port,
            filters=filters
        )

        try:
            proxies = self._request_proxy(params)
            if not proxies:
                proxy.status = ProxyStatus.DEAD
                proxy.save(update_fields=["status"])
                return None

            host, _ = proxies[0].split(":")

            proxy.host = host
            proxy.status = ProxyStatus.ACTIVE
            proxy.save(update_fields=["host", "status"])

            if not proxy.check_health():
                proxy.status = ProxyStatus.DEAD
                proxy.save(update_fields=["status"])
                return None

            return proxy

        except Exception as e:
            logger.error(f"Failed to refresh proxy on port {proxy.port}: {e}")
            proxy.status = ProxyStatus.DEAD
            proxy.save(update_fields=["status"])
            return None
