"""web_qa 项目成员权限（镜像 code_analysis.IsCodeProjectMember）。"""

from rest_framework import permissions

from projects.models import ProjectMember


class IsWebQaProjectMember(permissions.BasePermission):
    """通过 URL project_pk 判定项目成员身份；对象级通过所属项目反查。"""

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
        project = self._project_of(obj)
        if project is None:
            return False
        return ProjectMember.objects.filter(
            project=project,
            user=request.user,
            role__in=['owner', 'admin', 'member'],
        ).exists()

    @staticmethod
    def _project_of(obj):
        project = getattr(obj, 'project', None)
        if project is not None:
            return project
        suite = getattr(obj, 'suite', None)
        if suite is not None:
            return getattr(suite, 'project', None)
        return None
