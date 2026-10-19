from rest_framework import serializers
from .cookies import normalize_cookies, CookieFormatError
from .models import PinterestAccount

class PinterestAccountSerializer(serializers.ModelSerializer):
    cookies = serializers.JSONField(
        help_text="Cookies у будь-якому форматі: JSON з розширення браузера / Playwright, "
                  "{name: value}, рядок «a=b; c=d» або вміст cookies.txt. Зберігаються у форматі Playwright."
    )

    class Meta:
        model = PinterestAccount
        fields = '__all__'

    def validate_cookies(self, value):
        try:
            return normalize_cookies(value)
        except CookieFormatError as e:
            raise serializers.ValidationError(str(e))
