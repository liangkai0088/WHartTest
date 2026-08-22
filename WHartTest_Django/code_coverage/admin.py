from django.contrib import admin

from .models import CoverageReport, CoverageFile, CoverageDelta


@admin.register(CoverageReport)
class CoverageReportAdmin(admin.ModelAdmin):
    list_display = ['name', 'project', 'format', 'test_type', 'status', 'created_at']
    list_filter = ['format', 'test_type', 'status', 'created_at']
    search_fields = ['name', 'test_execution_ref', 'git_commit']
    readonly_fields = ['id', 'summary', 'status', 'error_message', 'created_at']


@admin.register(CoverageFile)
class CoverageFileAdmin(admin.ModelAdmin):
    list_display = ['file_path', 'report', 'line_coverage', 'lines_total', 'lines_covered']
    list_filter = ['created_at']
    search_fields = ['file_path', 'report__name']
    readonly_fields = ['id', 'line_coverage', 'branch_coverage', 'lines_total', 'lines_covered', 'created_at']


@admin.register(CoverageDelta)
class CoverageDeltaAdmin(admin.ModelAdmin):
    list_display = ['git_commit', 'project', 'base_commit', 'created_at']
    list_filter = ['created_at']
    search_fields = ['git_commit', 'base_commit', 'project__name']
    readonly_fields = ['id', 'project', 'report', 'base_report', 'summary', 'files', 'created_at']
