from django.urls import path

from .views import (
    CodeProjectViewSet,
    ComponentAnalysisViewSet,
    SpecAnalysisViewSet,
)

app_name = 'code_analysis'

urlpatterns = [
    # 代码项目
    path('projects/<int:project_pk>/code/projects/',
         CodeProjectViewSet.as_view({'get': 'list', 'post': 'create'})),
    path('projects/<int:project_pk>/code/projects/<int:pk>/',
         CodeProjectViewSet.as_view({'get': 'retrieve', 'delete': 'destroy'})),
    path('projects/<int:project_pk>/code/projects/<int:pk>/upload/',
         CodeProjectViewSet.as_view({'post': 'upload'})),
    path('projects/<int:project_pk>/code/projects/<int:pk>/files/',
         CodeProjectViewSet.as_view({'get': 'files'})),
    path('projects/<int:project_pk>/code/projects/<int:pk>/files/<int:file_id>/content/',
         CodeProjectViewSet.as_view({'get': 'file_content'})),
    path('projects/<int:project_pk>/code/projects/<int:pk>/analyze-changes/',
         CodeProjectViewSet.as_view({'post': 'analyze_changes'})),
    path('projects/<int:project_pk>/code/projects/<int:pk>/git-import/',
         CodeProjectViewSet.as_view({'post': 'git_import'})),
    path('projects/<int:project_pk>/code/projects/<int:pk>/links/',
         CodeProjectViewSet.as_view({'get': 'list_links', 'post': 'create_link'})),
    path('projects/<int:project_pk>/code/projects/<int:pk>/links/<int:link_id>/',
         CodeProjectViewSet.as_view({'delete': 'delete_link'})),
    path('projects/<int:project_pk>/code/projects/<int:pk>/impacts/',
         CodeProjectViewSet.as_view({'get': 'list_impacts'})),
    path('projects/<int:project_pk>/code/projects/<int:pk>/impacts/<int:impact_id>/resolve/',
         CodeProjectViewSet.as_view({'post': 'resolve_impact'})),

    # OpenAPI 规范分析
    path('projects/<int:project_pk>/code/spec-analysis/',
         SpecAnalysisViewSet.as_view({'get': 'list', 'post': 'create'})),
    path('projects/<int:project_pk>/code/spec-analysis/<int:pk>/',
         SpecAnalysisViewSet.as_view({'get': 'retrieve', 'delete': 'destroy'})),
    path('projects/<int:project_pk>/code/spec-analysis/<int:pk>/suggestions/',
         SpecAnalysisViewSet.as_view({'get': 'suggestions'})),
    path('projects/<int:project_pk>/code/spec-analysis/<int:pk>/approve/',
         SpecAnalysisViewSet.as_view({'post': 'approve'})),
    path('projects/<int:project_pk>/code/spec-analysis/<int:pk>/reject/',
         SpecAnalysisViewSet.as_view({'post': 'reject'})),

    # 组件源码分析
    path('projects/<int:project_pk>/code/component-analysis/',
         ComponentAnalysisViewSet.as_view({'get': 'list', 'post': 'create'})),
    path('projects/<int:project_pk>/code/component-analysis/<int:pk>/',
         ComponentAnalysisViewSet.as_view({'get': 'retrieve', 'delete': 'destroy'})),
    path('projects/<int:project_pk>/code/component-analysis/<int:pk>/element-suggestions/',
         ComponentAnalysisViewSet.as_view({'get': 'element_suggestions'})),
    path('projects/<int:project_pk>/code/component-analysis/<int:pk>/approve/',
         ComponentAnalysisViewSet.as_view({'post': 'approve'})),
    path('projects/<int:project_pk>/code/component-analysis/<int:pk>/reject/',
         ComponentAnalysisViewSet.as_view({'post': 'reject'})),
]
