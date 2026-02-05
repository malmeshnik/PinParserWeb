from django.utils import timezone
from django.db import transaction

from apps.accounts.models import PinterestAccount, AccountStatus
from apps.proxies.models import Proxy, ProxyStatus

MAX_ACCOUNT_FAILS = 3
MAX_PROXY_FAILS = 3
MAX_RETRIES = 2

class NoAvailableAccountError(Exception):
    pass

class AccountRotator:
    def get_account(self):
        accounts = (
            PinterestAccount.objects
            .select_related("proxy")
            .filter(
                is_active=True,
                status = AccountStatus.ACTIVE,
                fail_count__lt=MAX_ACCOUNT_FAILS,
            )
            .order_by("last_used_at", "id")
        )

        if not accounts.exists():
            raise NoAvailableAccountError("No available Pinterest accounts.")
        
        for _ in range(MAX_RETRIES):
            for account in accounts:
                if self._is_account_healthy(account):
                    self._mark_used(account)
                    return account
                
        raise NoAvailableAccountError("No healthy Pinterest accounts available after retries.")
    
    def _is_account_healthy(self, account: PinterestAccount) -> bool:
        proxy = account.proxy
        if proxy:
            if proxy.status != ProxyStatus.ACTIVE or proxy.fail_count >= MAX_PROXY_FAILS:
                return False
        return True
    
    def _is_proxy_healthy(self, proxy: Proxy) -> bool:
        if (
            not proxy.is_active or
            proxy.status != ProxyStatus.ACTIVE or
            proxy.fail_count >= MAX_PROXY_FAILS
        ):
            return False
        
        return True
    
    @transaction.atomic
    def _mark_used(self, account: PinterestAccount):
        account.last_used_at = timezone.now()
        account.save(update_fields=["last_used_at"])

    @transaction.atomic
    def register_account_fail(self, account: PinterestAccount):
        account.fail_count += 1
        if account.fail_count >= MAX_ACCOUNT_FAILS:
            account.status = AccountStatus.BANNED

        account.save(update_fields=["fail_count", "status"])

    @transaction.atomic
    def _register_proxy_fail(self, proxy: Proxy):
        proxy.fail_count += 1
        if proxy.fail_count >= MAX_PROXY_FAILS:
            proxy.status = ProxyStatus.DEAD

        proxy.save(update_fields=["fail_count", "status"])