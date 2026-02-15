from __future__ import annotations

from django.urls import path

from camera_roll_sounds_api.camera_roll_sounds.views import (
    job_status,
    process_image,
    serve_audio,
)

# All URLs will be prefixed with api/camera_roll_sounds/
urlpatterns = [
    path("process-image/", process_image, name="process-image"),
    path("job/<str:job_id>/", job_status, name="job-status"),
    path("audio/<str:filename>", serve_audio, name="serve-audio"),
]
