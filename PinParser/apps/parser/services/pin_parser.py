import json
import re
from typing import Optional

from bs4 import BeautifulSoup
from loguru import logger

RELAY_PATTERN = re.compile(
    r'__PWS_RELAY_REGISTER_COMPLETED_REQUEST__\([^,]+,\s*(\{.*?\})\s*\);',
    re.DOTALL
)

class PinParser:

    def parse(self, html: str, pin_url: str, keyword: str) -> Optional[dict]:
        try:
            relay_json = self._extract_relay_json(html)
            if not relay_json:
                logger.warning(f"[PIN PARSER] Relay JSON not found | {pin_url}")
                return None

            try:
                pin = relay_json["data"]["v3GetPinQuery"]["data"]
            except KeyError:
                logger.warning(f"[PIN PARSER] Invalid Relay structure | {pin_url}")
                return None
            
            return self._map_pin(pin, pin_url, keyword)
        except Exception as e:
            logger.warning(
                f"[PIN PARSER] Failed pin {pin_url} | {e}"
            )
            return None

        
    
    def _extract_relay_json(self, html: str) -> Optional[dict]:
        match = RELAY_PATTERN.search(html)
        if not match:
            return None

        raw_json = match.group(1)

        try:
            return json.loads(raw_json)
        except json.JSONDecodeError:
            logger.warning("[PIN PARSER] Failed to decode Relay JSON")
            return None
        
    def _map_pin(self, pin: dict, pin_url: str, keyword: str) -> dict:
        if not isinstance(pin, dict):
            return None

        aggregated = pin.get("aggregatedPinData") or {}
        if not isinstance(aggregated, dict):
            aggregated = {}

        stats = aggregated.get("aggregatedStats") or {}
        if not isinstance(stats, dict):
            stats = {}

        return {
            "pin_url": pin_url,
            "keyword": keyword,
            "pin_id": pin.get("entityId"),

            "title": pin.get("title") or pin.get("gridTitle"),
            "description": pin.get("closeupUnifiedDescription")
                or pin.get("description"),
            "alt_text": pin.get("seoAltText"),

            "image_url": self._best_image(pin),

            "domain": pin.get("domain"),
            "pinner_username": self._get_username(pin),

            "saves": stats.get("saves"),

            "creation_date": pin.get("createdAt"),
            "annotation": self._join_annotations(pin),
        }
    
    def _best_image(self, pin: dict) -> Optional[str]:
        images = pin.get("images_orig") or {}
        if isinstance(images, dict):
            return images.get("url")

        for key in ("images_736x", "images_564x", "images_474x"):
            img = pin.get(key)
            if isinstance(img, dict):
                return img.get("url")

        return None
    
    def _get_username(self, pin: dict) -> Optional[str]:
        for key in ("pinner", "originPinner", "nativeCreator"):
            user = pin.get(key) or {}
            if isinstance(user, dict):
                return user.get("username")
        return None
    
    def _join_annotations(self, pin: dict) -> str | None:
        pin_join = pin.get("pinJoin", {})

        if not isinstance(pin_join, dict):
            return None

        annotations = pin_join.get("visualAnnotation")

        if isinstance(annotations, list):
            return ", ".join(annotations)

        return None