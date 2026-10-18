import csv
from datetime import timedelta
from datetime import timezone as dt_timezone

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count, F, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import EventForm, SignupForm
from .models import Category, Event, Notification, Registration, SavedEvent

PAGE_SIZE = 9
SORTS = {"soonest", "popular"}
WHEN_CHOICES = {"today", "week", "later"}


def with_counts(events):
    """Attach confirmed (`booked`) and waitlisted (`waiting`) counts to a queryset."""
    return events.select_related("category").annotate(
        booked=Count("registrations", filter=Q(registrations__status=Registration.CONFIRMED)),
        waiting=Count("registrations", filter=Q(registrations__status=Registration.WAITLISTED)),
    )


def read_filters(params):
    sort = params.get("sort", "")
    when = params.get("when", "")
    return {
        "q": params.get("q", "").strip(),
        "category": params.get("category", ""),
        "sort": sort if sort in SORTS else "soonest",
        "when": when if when in WHEN_CHOICES else "",
        "available": params.get("available") == "1",
    }


def upcoming_events(f):
    now = timezone.now()
    events = with_counts(Event.objects.filter(start_at__gte=now))
    if f["q"]:
        events = events.filter(
            Q(title__icontains=f["q"]) | Q(description__icontains=f["q"]) | Q(venue__icontains=f["q"])
        )
    if f["category"].isdecimal():
        events = events.filter(category_id=int(f["category"]))
    if f["when"] == "today":
        end_of_day = timezone.localtime(now).replace(hour=23, minute=59, second=59, microsecond=999999)
        events = events.filter(start_at__lte=end_of_day)
    elif f["when"] == "week":
        events = events.filter(start_at__lte=now + timedelta(days=7))
    elif f["when"] == "later":
        events = events.filter(start_at__gt=now + timedelta(days=7))
    if f["available"]:
        events = events.filter(booked__lt=F("capacity"))
    if f["sort"] == "popular":
        return events.order_by("-booked", "start_at")
    return events.order_by("start_at")


def read_page(params):
    raw = params.get("page", "")
    return max(int(raw), 1) if raw.isdecimal() else 1


def page_of(events, page):
    total = events.count()
    start = (page - 1) * PAGE_SIZE
    return list(events[start:start + PAGE_SIZE]), total, start + PAGE_SIZE < total


def saved_ids_for(user):
    if not user.is_authenticated:
        return set()
    return set(SavedEvent.objects.filter(user=user).values_list("event_id", flat=True))


def event_to_dict(e, saved_ids):
    return {
        "id": e.pk,
        "title": e.title,
        "venue": e.venue,
        "category": e.category.name,
        "when": timezone.localtime(e.start_at).strftime("%a, %d %b %Y, %I:%M %p"),
        "seats_left": e.seats_left,
        "capacity": e.capacity,
        "fill_percent": e.fill_percent,
        "waitlist_count": e.waitlist_count,
        "hue": e.hue,
        "saved": e.pk in saved_ids,
        "url": e.get_absolute_url(),
    }


def home(request):
    filters = read_filters(request.GET)
    events, total, has_next = page_of(upcoming_events(filters), 1)
    saved = saved_ids_for(request.user)
    for e in events:
        e.saved = e.pk in saved
    return render(request, "home.html", {
        "events": events,
        "total": total,
        "has_next": has_next,
        "categories": Category.objects.all(),
        "filters": filters,
    })


def event_detail(request, pk):
    event = get_object_or_404(Event.objects.select_related("category", "organiser"), pk=pk)
    reg = None
    saved = False
    if request.user.is_authenticated:
        reg = event.registrations.filter(user=request.user).first()
        saved = SavedEvent.objects.filter(user=request.user, event=event).exists()
    return render(request, "event_detail.html", {
        "event": event,
        "state": reg.status if reg else "none",
        "position": reg.waitlist_position if reg else 0,
        "saved": saved,
        "is_owner": request.user.is_authenticated and request.user.id == event.organiser_id,
    })


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
        with transaction.atomic():
            Event.objects.select_for_update().get(pk=event.pk)  # same lock the register/cancel views take
            form.save()
            event.promote_waitlist()  # a bigger capacity may free seats
        messages.success(request, "Event updated.")
        return redirect(event)
    return render(request, "event_form.html", {"form": form, "heading": "Edit event"})


@login_required
def event_delete(request, pk):
    event = get_object_or_404(Event, pk=pk)
    if event.organiser_id != request.user.id:
        raise PermissionDenied
    if request.method == "POST":
        for reg in event.registrations.select_related("user").exclude(user=request.user):
            Notification.send(reg.user, f'"{event.title}" was cancelled by the host.')
        event.delete()
        messages.success(request, "Event deleted.")
        return redirect("my_events")
    return render(request, "event_confirm_delete.html", {"event": event})


@login_required
def my_events(request):
    regs = (
        Registration.objects.filter(user=request.user)
        .select_related("event__category")
        .order_by("event__start_at")
    )
    hosted = with_counts(Event.objects.filter(organiser=request.user)).order_by("start_at")
    return render(request, "my_events.html", {
        "going": [r for r in regs if r.status == Registration.CONFIRMED],
        "waiting": [r for r in regs if r.status == Registration.WAITLISTED],
        "hosted": hosted,
    })


@login_required
def saved_events(request):
    events = with_counts(Event.objects.filter(saves__user=request.user)).order_by("start_at")
    events = list(events)
    for e in events:
        e.saved = True
    return render(request, "saved.html", {"events": events})


@login_required
def notifications(request):
    items = list(Notification.objects.filter(user=request.user)[:50])
    unread = {n.pk for n in items if n.read_at is None}
    Notification.objects.filter(user=request.user, read_at__isnull=True).update(read_at=timezone.now())
    return render(request, "notifications.html", {"items": items, "unread": unread})


def signup(request):
    form = SignupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        login(request, form.save())
        messages.success(request, "Welcome aboard.")
        return redirect("home")
    return render(request, "registration/signup.html", {"form": form})


# ---- organiser tools -------------------------------------------------------

def _owned_event_or_403(request, pk):
    event = get_object_or_404(Event, pk=pk)
    if event.organiser_id != request.user.id:
        raise PermissionDenied
    return event


@login_required
def event_attendees(request, pk):
    event = _owned_event_or_403(request, pk)
    regs = event.registrations.select_related("user").order_by("created_at", "id")
    going = [r for r in regs if r.status == Registration.CONFIRMED]
    waiting = [r for r in regs if r.status == Registration.WAITLISTED]
    return render(request, "attendees.html", {
        "event": event,
        "going": going,
        "waiting": waiting,
        "checked_in": sum(r.checked_in for r in going),
    })


def _safe_cell(value):
    # stop spreadsheet apps from running a username like "=HYPERLINK(...)" as a formula
    text = str(value)
    return "'" + text if text.startswith(("=", "+", "-", "@", "\t", "\r")) else text


@login_required
def event_attendees_csv(request, pk):
    event = _owned_event_or_403(request, pk)
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="attendees-event-{event.pk}.csv"'
    writer = csv.writer(response)
    writer.writerow(["Username", "Status", "Checked in", "Registered at"])
    regs = event.registrations.select_related("user").order_by("status", "created_at", "id")
    for r in regs:
        writer.writerow([
            _safe_cell(r.user.username),
            r.status,
            "yes" if r.checked_in else "no",
            timezone.localtime(r.created_at).strftime("%Y-%m-%d %H:%M"),
        ])
    return response


def _ics_text(value):
    return (
        str(value).replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
        .replace("\r", "").replace("\n", "\\n")
    )


def _ics_fold(line):
    # calendar apps expect lines of at most 75 characters, continued with a leading space
    parts = [line[:75]] + [" " + line[i:i + 74] for i in range(75, len(line), 74)]
    return "\r\n".join(parts)


def event_calendar(request, pk):
    event = get_object_or_404(Event, pk=pk)
    fmt = "%Y%m%dT%H%M%SZ"
    start = event.start_at.astimezone(dt_timezone.utc)
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Campus Event Hub//EN",
        "BEGIN:VEVENT",
        f"UID:event-{event.pk}@campus-event-hub",
        f"DTSTAMP:{timezone.now().astimezone(dt_timezone.utc).strftime(fmt)}",
        f"DTSTART:{start.strftime(fmt)}",
        # events have no end time, so the calendar entry is two hours long
        f"DTEND:{(start + timedelta(hours=2)).strftime(fmt)}",
        f"SUMMARY:{_ics_text(event.title)}",
        f"DESCRIPTION:{_ics_text(event.description)}",
        f"LOCATION:{_ics_text(event.venue)}",
        "END:VEVENT",
        "END:VCALENDAR",
    ]
    body = "\r\n".join(_ics_fold(line) for line in lines) + "\r\n"
    response = HttpResponse(body, content_type="text/calendar; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="event-{event.pk}.ics"'
    return response


# ---- JSON API --------------------------------------------------------------

def _json_error(message, status=400):
    return JsonResponse({"error": message}, status=status)


def api_events(request):
    page = read_page(request.GET)
    events, total, has_next = page_of(upcoming_events(read_filters(request.GET)), page)
    saved = saved_ids_for(request.user)
    return JsonResponse({
        "events": [event_to_dict(e, saved) for e in events],
        "total": total,
        "has_next": has_next,
        "page": page,
    })


def _state_response(event, state, position=0):
    return JsonResponse({"state": state, "seats_left": event.seats_left, "position": position})


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
        status = Registration.WAITLISTED if event.is_full else Registration.CONFIRMED
        reg = Registration.objects.create(event=event, user=request.user, status=status)
    return _state_response(event, status, reg.waitlist_position)


@require_POST
def api_cancel(request, pk):
    if not request.user.is_authenticated:
        return _json_error("Please log in first.", 401)
    with transaction.atomic():
        event = get_object_or_404(Event.objects.select_for_update(), pk=pk)
        reg = event.registrations.filter(user=request.user).first()
        if reg is None:
            return _json_error("You are not registered for this event.")
        freed_a_seat = reg.status == Registration.CONFIRMED
        reg.delete()
        if freed_a_seat:
            event.promote_waitlist()
    return _state_response(event, "none")


@require_POST
def api_save(request, pk):
    if not request.user.is_authenticated:
        return _json_error("Please log in to save events.", 401)
    event = get_object_or_404(Event, pk=pk)
    _, created = SavedEvent.objects.get_or_create(user=request.user, event=event)
    if not created:
        SavedEvent.objects.filter(user=request.user, event=event).delete()
    return JsonResponse({"saved": created})


@require_POST
def api_checkin(request, pk):
    if not request.user.is_authenticated:
        return _json_error("Please log in first.", 401)
    reg = get_object_or_404(Registration.objects.select_related("event"), pk=pk)
    if reg.event.organiser_id != request.user.id:
        return _json_error("Only the host can check people in.", 403)
    if reg.status != Registration.CONFIRMED:
        return _json_error("Waitlisted people can't be checked in.")
    reg.checked_in = not reg.checked_in
    reg.save(update_fields=["checked_in"])
    return JsonResponse({"checked_in": reg.checked_in})
