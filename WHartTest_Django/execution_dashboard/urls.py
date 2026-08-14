from django.urls import path

from .views import EventListView, RunSnapshotView

urlpatterns = [
    path(
        "execution-dashboard/runs/<int:run_id>/events/",
        EventListView.as_view(),
        name="execution-dashboard-events",
    ),
    path(
        "execution-dashboard/runs/<int:run_id>/snapshot/",
        RunSnapshotView.as_view(),
        name="execution-dashboard-snapshot",
    ),
]
