from django.contrib.auth import views as auth
from django.urls import include, path

urlpatterns = [
    path("login/", auth.LoginView.as_view(template_name="login.html")),
    path("logout/", auth.LogoutView.as_view()),
    path("", include("core.urls")),
]
