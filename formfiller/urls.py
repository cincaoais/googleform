from django.urls import path
from . import views

app_name = "formfiller"

urlpatterns = [
    path("", views.index, name="index"),
    path("api/parse/", views.api_parse, name="api_parse"),
    path("api/submit/", views.api_submit, name="api_submit"),
    path("api/stop/<str:job_id>/", views.api_stop, name="api_stop"),
    path("api/stream/<str:job_id>/", views.api_stream, name="api_stream"),
]
