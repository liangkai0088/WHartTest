from django.contrib import admin

from .models import AgentLocatorCache, QaBatchRun, QaRun, QaStepResult, QaSuite


@admin.register(QaSuite)
class QaSuiteAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'project', 'group', 'engine', 'source', 'status', 'test_count', 'created_by', 'created_at')
    list_filter = ('engine', 'source', 'status', 'group')
    search_fields = ('name', 'group', 'description')
    raw_id_fields = ('project', 'llm_config', 'created_by')


@admin.register(QaRun)
class QaRunAdmin(admin.ModelAdmin):
    list_display = ('id', 'suite', 'batch', 'status', 'started_at', 'finished_at', 'created_by', 'created_at')
    list_filter = ('status',)
    raw_id_fields = ('suite', 'batch', 'created_by')


@admin.register(QaBatchRun)
class QaBatchRunAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'project', 'group', 'status', 'created_by', 'created_at')
    list_filter = ('status',)
    raw_id_fields = ('project', 'created_by')


@admin.register(QaStepResult)
class QaStepResultAdmin(admin.ModelAdmin):
    list_display = ('id', 'run', 'test_index', 'step_index', 'action', 'status', 'duration_ms', 'created_at')
    list_filter = ('status',)
    raw_id_fields = ('run',)


@admin.register(AgentLocatorCache)
class AgentLocatorCacheAdmin(admin.ModelAdmin):
    list_display = ('id', 'project', 'base_url', 'description', 'selector', 'strategy', 'hits', 'updated_at')
    list_filter = ('strategy',)
    raw_id_fields = ('project',)
