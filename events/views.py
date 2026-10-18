from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import EventForm, SignupForm
from .models import Category, Event, Registration


def upcoming_events(q="", category=""):
    events = (
        Event.objects.filter(start_at__gte=timezone.now())
        .select_related("category")
        .annotate(booked=Count("registrations"))
    )
    if q:
        events = events.filter(
            Q(title__icontains=q) | Q(description__icontains=q) | Q(venue__icontains=q)
        )
    if category.isdecimal():
        events = events.filter(category_id=int(category))
    return events


def event_to_dict(e):
    return {
        "id": e.pk,
        "title": e.title,
        "venue": e.venue,
        "category": e.category.name,
        "when": timezone.localtime(e.start_at).strftime("%a, %d %b %Y, %I:%M %p"),
        "seats_left": e.seats_left,
        "url": e.get_absolute_url(),
    }


def home(request):
    q = request.GET.get("q", "").strip()
    category = request.GET.get("category", "")
    return render(request, "home.html", {
        "events": upcoming_events(q, category),
        "categories": Category.objects.all(),
        "q": q,
        "category": category,
    })


def event_detail(request, pk):
    event = get_object_or_404(Event.objects.select_related("category", "organiser"), pk=pk)
    registered = (
        request.user.is_authenticated
        and event.registrations.filter(user=request.user).exists()
    )
    return render(request, "event_detail.html", {"event": event, "registered": registered})


@login_required
def event_create(request):
    form = EventForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        event = form.save(commit=False)
        event.organiser = request.user
        event.save()
        messages.success(request, "Your event is live.")
        return redirect(event)
    return render(request, "event_form.html", {"form": form, "heading": "Host an event"})


@login_required
def event_edit(request, pk):
    event = get_object_or_404(Event, pk=pk)
    if event.organiser_id != request.user.id:
        raise PermissionDenied
    form = EventForm(request.POST or None, instance=event)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Event updated.")
        return redirect(event)
    return render(request, "event_form.html", {"form": form, "heading": "Edit event"})


@login_required
def event_delete(request, pk):
    event = get_object_or_404(Event, pk=pk)
    if event.organiser_id != request.user.id:
        raise PermissionDenied
    if request.method == "POST":
        event.delete()
        messages.success(request, "Event deleted.")
        return redirect("my_events")
    return render(request, "event_confirm_delete.html", {"event": event})


@login_required
def my_events(request):
    registered = (
        Event.objects.filter(registrations__user=request.user)
        .select_related("category")
        .order_by("start_at")
    )
    hosted = (
        Event.objects.filter(organiser=request.user)
        .select_related("category")
        .annotate(booked=Count("registrations"))
        .order_by("start_at")
    )
    return render(request, "my_events.html", {"registered": registered, "hosted": hosted})


def signup(request):
    form = SignupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        login(request, form.save())
        messages.success(request, "Welcome aboard.")
        return redirect("home")
    return render(request, "registration/signup.html", {"form": form})


def api_events(request):
    events = upcoming_events(
        request.GET.get("q", "").strip(), request.GET.get("category", "")
    )
    return JsonResponse({"events": [event_to_dict(e) for e in events]})


def _json_error(message, status=400):
    return JsonResponse({"error": message}, status=status)


@require_POST
def api_register(request, pk):
    if not request.user.is_authenticated:
        return _json_error("Please log in to register.", 401)
    with transaction.atomic():
        # lock the row so two people can't both take the last seat
        event = get_object_or_404(Event.objects.select_for_update(), pk=pk)
        if event.is_past:
            return _json_error("This event has already happened.")
        if event.registrations.filter(user=request.user).exists():
            return _json_error("You are already registered.")
        if event.is_full:
            return _json_error("Sorry, this event is full.")
        Registration.objects.create(event=event, user=request.user)
    return JsonResponse({"registered": True, "seats_left": event.seats_left})


@require_POST
def api_cancel(request, pk):
    if not request.user.is_authenticated:
        return _json_error("Please log in first.", 401)
    event = get_object_or_404(Event, pk=pk)
    deleted, _ = Registration.objects.filter(event=event, user=request.user).delete()
    if not deleted:
        return _json_error("You are not registered for this event.")
    return JsonResponse({"registered": False, "seats_left": event.seats_left})
