from django.urls import path
from . import views

app_name = "formfiller"

urlpatterns = [
    path("", views.index, name="index"),
    path("api/parse/", views.api_parse, name="api_parse"),
    path("api/submit/", views.api_submit, name="api_submit"),
    path("api/stop/<str:job_id>/", views.api_stop, name="api_stop"),
    path("api/stream/<str:job_id>/", views.api_stream, name="api_stream"),
    # Google authentication
    path("api/google/login/", views.api_google_login, name="api_google_login"),
    path("api/google/auth-status/", views.api_google_auth_status, name="api_google_auth_status"),
    path("api/google/logout/", views.api_google_logout, name="api_google_logout"),
    # Generic web form filler
    path("generic/", views.generic_index, name="generic_index"),
    path("api/generic/parse/", views.api_generic_parse, name="api_generic_parse"),
    path("api/generic/submit/", views.api_generic_submit, name="api_generic_submit"),
]
