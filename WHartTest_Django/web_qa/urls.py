from django.urls import path

from .views import QaRunViewSet, QaSuiteViewSet

app_name = 'web_qa'

urlpatterns = [
    # 套件
    path('projects/<int:project_pk>/web-qa/suites/',
         QaSuiteViewSet.as_view({'get': 'list', 'post': 'create'})),
    path('projects/<int:project_pk>/web-qa/suites/import/',
         QaSuiteViewSet.as_view({'post': 'import_suite'})),
    path('projects/<int:project_pk>/web-qa/suites/<int:pk>/',
         QaSuiteViewSet.as_view({'get': 'retrieve', 'put': 'update', 'delete': 'destroy'})),
    path('projects/<int:project_pk>/web-qa/suites/<int:pk>/yaml/',
         QaSuiteViewSet.as_view({'put': 'update_yaml'})),
    path('projects/<int:project_pk>/web-qa/suites/<int:pk>/run/',
         QaSuiteViewSet.as_view({'post': 'run_suite'})),

    # 批量执行 / PRD 生成 / 定位缓存
    path('projects/<int:project_pk>/web-qa/batch-run/',
         QaSuiteViewSet.as_view({'post': 'batch_run'})),
    path('projects/<int:project_pk>/web-qa/prd-generate/',
         QaSuiteViewSet.as_view({'post': 'prd_generate'})),
    path('projects/<int:project_pk>/web-qa/locator-cache/',
         QaSuiteViewSet.as_view({'get': 'locator_cache'})),
    path('projects/<int:project_pk>/web-qa/locator-cache/<int:pk>/',
         QaSuiteViewSet.as_view({'delete': 'locator_cache_delete'})),

    # 执行记录
    path('projects/<int:project_pk>/web-qa/runs/',
         QaRunViewSet.as_view({'get': 'list'})),
    path('projects/<int:project_pk>/web-qa/runs/<int:pk>/',
         QaRunViewSet.as_view({'get': 'retrieve'})),
    path('projects/<int:project_pk>/web-qa/runs/<int:pk>/report.md/',
         QaRunViewSet.as_view({'get': 'report_md'})),
    path('projects/<int:project_pk>/web-qa/runs/<int:pk>/cancel/',
         QaRunViewSet.as_view({'post': 'cancel'})),
]
