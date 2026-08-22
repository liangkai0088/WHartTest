from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import CoverageReportViewSet, CoverageDeltaViewSet

router = DefaultRouter()
router.register(r'reports', CoverageReportViewSet, basename='coverage-report')
router.register(r'deltas', CoverageDeltaViewSet, basename='coverage-delta')

urlpatterns = [
    path('', include(router.urls)),
]
