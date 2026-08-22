from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    PerfTestScenarioViewSet,
    PerfTestRequestViewSet,
    PerfTestPlanViewSet,
    PerfTestExecutionViewSet,
    PerfTestReportViewSet,
    PerfTestNodeViewSet,
)

router = DefaultRouter()
router.register(r'scenarios', PerfTestScenarioViewSet, basename='perf-scenario')
router.register(r'requests', PerfTestRequestViewSet, basename='perf-request')
router.register(r'plans', PerfTestPlanViewSet, basename='perf-plan')
router.register(r'executions', PerfTestExecutionViewSet, basename='perf-execution')
router.register(r'reports', PerfTestReportViewSet, basename='perf-report')
router.register(r'nodes', PerfTestNodeViewSet, basename='perf-node')

urlpatterns = [
    path('', include(router.urls)),
]
