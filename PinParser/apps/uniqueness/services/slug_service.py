import re
import unicodedata
from typing import Optional


class SlugService:
    MAX_LENGTH = 80

    @classmethod
    def make_slug(cls, text: Optional[str]) -> Optional[str]:
        if not text:
            return None

        text = unicodedata.normalize("NFKD", text)
        text = text.encode("ascii", "ignore").decode("ascii")

        text = text.lower()

        text = re.sub(r"[^a-z0-9]+", "-", text)

        text = text.strip("-")

        if len(text) > cls.MAX_LENGTH:
            text = text[: cls.MAX_LENGTH].rstrip("-")

        return text or None

    @classmethod
    def build_slug_url(
        cls,
        pin_id: Optional[str],
        utitle: Optional[str],
    ) -> Optional[str]:
        slug = cls.make_slug(utitle)
        if not slug:
            return None

        if pin_id:
            return f"https://www.pinterest.com/pin/{pin_id}/?slug={slug}"

        return f"?slug={slug}"
