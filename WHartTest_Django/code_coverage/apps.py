from django.apps import AppConfig


class CodeCoverageConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'code_coverage'
    verbose_name = '代码覆盖率'
