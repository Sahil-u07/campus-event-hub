from django.contrib import admin

from .models import Category, Event, Registration, SavedEvent


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
    list_display = ["user", "event", "status", "checked_in", "created_at"]
    list_filter = ["status", "checked_in", "event"]
    search_fields = ["user__username", "event__title"]


@admin.register(SavedEvent)
class SavedEventAdmin(admin.ModelAdmin):
    list_display = ["user", "event", "created_at"]
    search_fields = ["user__username", "event__title"]
