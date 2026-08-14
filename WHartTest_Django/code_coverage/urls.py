from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import CoverageReportViewSet

router = DefaultRouter()
router.register(r'reports', CoverageReportViewSet, basename='coverage-report')

urlpatterns = [
    path('', include(router.urls)),
]
