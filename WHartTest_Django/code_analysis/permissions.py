from rest_framework import permissions

from projects.models import ProjectMember


class IsCodeProjectMember(permissions.BasePermission):
    """
    code_analysis 模块的项目成员权限检查。

    - has_permission：通过 URL 中 project_pk（兼容 pk）判定当前用户是否为项目成员；
    - has_object_permission：通过对象反查所属项目判定成员关系（superuser 直接放行）。
    """

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True

        project_pk = view.kwargs.get('project_pk') or view.kwargs.get('pk')
        if not project_pk:
            return False
        try:
            project_pk = int(project_pk)
        except (TypeError, ValueError):
            return False

        return ProjectMember.objects.filter(
            project_id=project_pk,
            user=request.user,
            role__in=['owner', 'admin', 'member'],
        ).exists()

    def has_object_permission(self, request, view, obj):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True

        project = self.get_project_from_object(obj)
        if project is None:
            return False
        return ProjectMember.objects.filter(
            project=project,
            user=request.user,
            role__in=['owner', 'admin', 'member'],
        ).exists()

    @staticmethod
    def get_project_from_object(obj):
        """从对象中提取所属项目，兼容 CodeProject / Task / Suggestion / CodeFile。"""
        project = getattr(obj, 'project', None)
        if project is not None:
            return project
        cp = getattr(obj, 'code_project', None)
        if cp is not None:
            return getattr(cp, 'project', None)
        return None
