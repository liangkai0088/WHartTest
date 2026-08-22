from django.apps import AppConfig


class PerfTestConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'perf_test'
    verbose_name = '性能测试'
