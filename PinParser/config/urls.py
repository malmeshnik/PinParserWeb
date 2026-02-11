"""
URL configuration for PinParser project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from rest_framework.routers import DefaultRouter
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView

from apps.tasks.views import TaskViewSet
from apps.accounts.views import AccountViewSet
from apps.proxies.views import ProxyViewSet
from apps.results.views import PinResultViewSet
from apps.uniqueness.views import UniquenessConfigViewSet
from apps.analytics.views import analytics_dashboard

router = DefaultRouter()
router.register(r'tasks', TaskViewSet)
router.register(r'accounts', AccountViewSet)
router.register(r'proxies', ProxyViewSet)
router.register(r'results', PinResultViewSet)
router.register(r'uniqueness', UniquenessConfigViewSet)

urlpatterns = [
    path('admin/analytics/', analytics_dashboard, name='analytics_dashboard'),
    path('admin/', admin.site.urls),
    path('api/', include(router.urls)),
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/schema/swagger-ui/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/schema/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),
]

urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)