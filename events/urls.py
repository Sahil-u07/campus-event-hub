from django.contrib.auth import views as auth_views
from django.urls import path

from . import views
from .forms import LoginForm

urlpatterns = [
    path("", views.home, name="home"),
    path("events/new/", views.event_create, name="event_create"),
    path("events/<int:pk>/", views.event_detail, name="event_detail"),
    path("events/<int:pk>/edit/", views.event_edit, name="event_edit"),
    path("events/<int:pk>/delete/", views.event_delete, name="event_delete"),
    path("events/<int:pk>/attendees/", views.event_attendees, name="event_attendees"),
    path("events/<int:pk>/attendees.csv", views.event_attendees_csv, name="event_attendees_csv"),
    path("events/<int:pk>/calendar.ics", views.event_calendar, name="event_calendar"),
    path("mine/", views.my_events, name="my_events"),
    path("saved/", views.saved_events, name="saved_events"),
    path("signup/", views.signup, name="signup"),
    path("login/", auth_views.LoginView.as_view(authentication_form=LoginForm), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("api/events/", views.api_events, name="api_events"),
    path("api/events/<int:pk>/register/", views.api_register, name="api_register"),
    path("api/events/<int:pk>/cancel/", views.api_cancel, name="api_cancel"),
    path("api/events/<int:pk>/save/", views.api_save, name="api_save"),
    path("api/registrations/<int:pk>/checkin/", views.api_checkin, name="api_checkin"),
]
