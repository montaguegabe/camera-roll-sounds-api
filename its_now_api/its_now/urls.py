from __future__ import annotations

from django.urls import path

from its_now_api.its_now.views import (
    job_status,
    process_image,
    serve_audio,
    usage_status,
)

# All URLs will be prefixed with /api/its_now/
urlpatterns = [
    path("process-image/", process_image, name="process-image"),
    path("process-images/", process_image, name="process-images"),
    path("job/<str:job_id>/", job_status, name="job-status"),
    path("audio/<str:filename>", serve_audio, name="serve-audio"),
    path("usage/", usage_status, name="usage-status"),
]
