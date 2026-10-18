from django.contrib import admin

from .models import Category, Event, Registration


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    search_fields = ["name"]


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ["title", "category", "venue", "start_at", "capacity", "organiser"]
    list_filter = ["category", "start_at"]
    search_fields = ["title", "venue", "organiser__username"]
    date_hierarchy = "start_at"


@admin.register(Registration)
class RegistrationAdmin(admin.ModelAdmin):
    list_display = ["user", "event", "created_at"]
    list_filter = ["event"]
    search_fields = ["user__username", "event__title"]
