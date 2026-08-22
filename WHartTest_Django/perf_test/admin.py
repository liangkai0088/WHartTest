from django.contrib import admin

from .models import (
    PerfTestScenario,
    PerfTestRequest,
    PerfTestPlan,
    PerfTestExecution,
    PerfTestReport,
    PerfTestNode,
)


@admin.register(PerfTestScenario)
class PerfTestScenarioAdmin(admin.ModelAdmin):
    list_display = ['name', 'project', 'source', 'created_by', 'created_at']
    list_filter = ['source', 'created_at']
    search_fields = ['name', 'description']


@admin.register(PerfTestRequest)
class PerfTestRequestAdmin(admin.ModelAdmin):
    list_display = ['name', 'scenario', 'method', 'url', 'weight', 'order']
    list_filter = ['method']
    search_fields = ['name', 'url']


@admin.register(PerfTestPlan)
class PerfTestPlanAdmin(admin.ModelAdmin):
    list_display = ['scenario', 'users', 'spawn_rate', 'duration', 'think_time']
    search_fields = ['scenario__name']


@admin.register(PerfTestExecution)
class PerfTestExecutionAdmin(admin.ModelAdmin):
    list_display = ['id', 'scenario', 'status', 'progress', 'executed_by', 'created_at']
    list_filter = ['status', 'created_at']
    search_fields = ['scenario__name']
    readonly_fields = ['status', 'progress', 'error_message']


@admin.register(PerfTestReport)
class PerfTestReportAdmin(admin.ModelAdmin):
    list_display = [
        'execution', 'total_requests', 'total_failures', 'error_rate',
        'avg_response_time', 'p95', 'total_rps',
    ]
    readonly_fields = ['execution', 'total_requests', 'total_failures']


@admin.register(PerfTestNode)
class PerfTestNodeAdmin(admin.ModelAdmin):
    list_display = ['name', 'host', 'status', 'cpu_usage', 'memory_usage', 'last_heartbeat']
    list_filter = ['status']
    search_fields = ['name', 'host']
