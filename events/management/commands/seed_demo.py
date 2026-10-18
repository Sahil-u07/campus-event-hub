from datetime import timedelta

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.utils import timezone

from events.models import Category, Event, Registration

CATEGORIES = ["Tech", "Cultural", "Sports", "Workshop", "Career"]

# title, category, venue, days from now, hour, capacity, description
EVENTS = [
    ("Intro to Django Workshop", "Workshop", "CS Lab 3", 2, 15, 40,
     "Build a small blog from scratch with models, views and templates. Bring a laptop with Python installed."),
    ("Inter-Department Football Cup", "Sports", "Main Ground", 5, 16, 120,
     "Knockout rounds, one team per department. Register your squad of 11 plus 3 substitutes."),
    ("Hack Night 2026", "Tech", "Innovation Centre", 7, 18, 60,
     "Twelve hours, one problem statement, snacks provided. Teams of up to four."),
    ("Resume and LinkedIn Clinic", "Career", "Seminar Hall B", 9, 11, 80,
     "Alumni from three companies review your resume in small groups and answer questions."),
    ("Open Mic Evening", "Cultural", "Amphitheatre", 10, 17, 150,
     "Music, poetry and stand-up. Walk-ins welcome, performers please sign up on the day."),
    ("Machine Learning Study Circle", "Tech", "Library Room 2", 3, 17, 25,
     "Weekly discussion. This week: decision trees and overfitting, with a short live demo."),
    ("Photography Walk", "Cultural", "Campus Gate 1", 12, 7, 30,
     "Early morning golden-hour walk around campus. Phones are fine, cameras welcome."),
    ("Git and GitHub Basics", "Workshop", "CS Lab 1", 4, 14, 3,
     "Branches, commits, pull requests. Small group, hands-on, so seats are limited."),
]


# event title -> how many demo students are confirmed, and how many wait
DEMO_CROWDS = {
    "Git and GitHub Basics": (3, 2),
    "Machine Learning Study Circle": (19, 0),
    "Hack Night 2026": (31, 0),
    "Intro to Django Workshop": (12, 0),
    "Open Mic Evening": (60, 0),
}


class Command(BaseCommand):
    help = "Add a demo host account, categories and a few upcoming events."

    def handle(self, *args, **options):
        host, created = User.objects.get_or_create(username="eventclub")
        if created:
            host.set_unusable_password()
            host.save()

        cats = {name: Category.objects.get_or_create(name=name)[0] for name in CATEGORIES}

        today = timezone.localtime().replace(minute=0, second=0, microsecond=0)
        added = 0
        for title, cat, venue, days, hour, cap, desc in EVENTS:
            _, new = Event.objects.get_or_create(
                title=title,
                defaults=dict(
                    category=cats[cat], venue=venue, capacity=cap, description=desc,
                    start_at=(today + timedelta(days=days)).replace(hour=hour),
                    organiser=host,
                ),
            )
            added += new

        students = []
        for i in range(1, 70):
            u, made = User.objects.get_or_create(username=f"student{i:02d}")
            if made:
                u.set_unusable_password()
                u.save()
            students.append(u)
        for title, (going, waiting) in DEMO_CROWDS.items():
            event = Event.objects.get(title=title)
            if event.registrations.exists():
                continue
            for u in students[:going]:
                Registration.objects.create(event=event, user=u, status=Registration.CONFIRMED)
            for u in students[going:going + waiting]:
                Registration.objects.create(event=event, user=u, status=Registration.WAITLISTED)
        self.stdout.write(f"{added} new event(s) added.")
