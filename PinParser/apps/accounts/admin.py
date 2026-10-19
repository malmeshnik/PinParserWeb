import json

from django import forms
from django.contrib import admin, messages
from django.utils.html import format_html

from .cookies import normalize_cookies, has_session_cookie, CookieFormatError, SESSION_COOKIE
from .models import PinterestAccount


class PinterestAccountForm(forms.ModelForm):
    # Звичайний текст замість JSON-поля: можна вставити рядок «a=b; c=d» або cookies.txt
    cookies = forms.CharField(
        label="Cookies",
        widget=forms.Textarea(attrs={"rows": 12, "style": "width: 100%; font-family: monospace; font-size: 12px"}),
        help_text=(
            "Вставте cookies у будь-якому форматі: JSON з розширення браузера (Cookie-Editor, EditThisCookie), "
            "формат Playwright/Puppeteer, {\"name\": \"value\"}, рядок «name=value; name2=value2» "
            "або вміст cookies.txt. Після збереження вони автоматично приводяться до формату Playwright."
        ),
    )

    class Meta:
        model = PinterestAccount
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk and self.instance.cookies:
            self.initial["cookies"] = json.dumps(self.instance.cookies, ensure_ascii=False, indent=2)

    def clean_cookies(self):
        try:
            return normalize_cookies(self.cleaned_data["cookies"])
        except CookieFormatError as e:
            raise forms.ValidationError(str(e))


@admin.register(PinterestAccount)
class PinterestAccountAdmin(admin.ModelAdmin):
    form = PinterestAccountForm

    def has_module_permission(self, request):
        return request.user.is_superuser

    list_display = ('id', 'name', 'proxy', 'status', 'cookies_info', 'fail_count', 'last_used_at', 'is_active')
    list_filter = ('status', 'is_active')
    search_fields = ('name',)

    actions = ['rotate_proxy_action', 'normalize_cookies_action']

    @admin.display(description="Cookies")
    def cookies_info(self, obj):
        count = len(obj.cookies) if isinstance(obj.cookies, list) else 0
        if has_session_cookie(obj.cookies):
            return format_html('<span style="color:#198754">✔ {} шт., сесія є</span>', count)
        return format_html('<span style="color:#dc3545">⚠ {} шт., немає {}</span>', count, SESSION_COOKIE)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if not has_session_cookie(obj.cookies):
            messages.warning(
                request,
                f"У cookies акаунта «{obj.name}» немає {SESSION_COOKIE} — без неї акаунт не залогінений "
                f"у Pinterest. Експортуйте cookies з браузера, де ви увійшли в акаунт.",
            )

    def rotate_proxy_action(self, request, queryset):
        count = 0
        for account in queryset:
            if account.rotate_proxy():
                count += 1
        self.message_user(request, f"Проксі змінено для {count} аккаунтів")
    rotate_proxy_action.short_description = "🔄 Ротувати проксі"

    @admin.action(description="🍪 Нормалізувати cookies (для акаунтів, доданих раніше)")
    def normalize_cookies_action(self, request, queryset):
        fixed, failed = 0, []
        for account in queryset:
            try:
                account.cookies = normalize_cookies(account.cookies)
                account.save(update_fields=["cookies"])
                fixed += 1
            except CookieFormatError as e:
                failed.append(f"{account.name}: {e}")
        if fixed:
            self.message_user(request, f"Cookies нормалізовано для {fixed} акаунтів")
        for error in failed:
            self.message_user(request, error, level=messages.ERROR)
