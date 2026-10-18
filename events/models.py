from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone


class Category(models.Model):
    name = models.CharField(max_length=50, unique=True)

    class Meta:
        verbose_name_plural = "categories"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Event(models.Model):
    title = models.CharField(max_length=120)
    description = models.TextField()
    venue = models.CharField(max_length=120)
    start_at = models.DateTimeField()
    capacity = models.PositiveIntegerField()
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="events")
    organiser = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="hosted_events"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["start_at"]

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("event_detail", args=[self.pk])

    @property
    def seats_left(self):
        # list views annotate `booked` so we don't run one count query per card
        booked = getattr(self, "booked", None)
        if booked is None:
            booked = self.registrations.count()
        return max(self.capacity - booked, 0)

    @property
    def is_full(self):
        return self.seats_left == 0

    @property
    def is_past(self):
        return self.start_at < timezone.now()


class Registration(models.Model):
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="registrations")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="registrations"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["event", "user"], name="one_seat_per_user")
        ]

    def __str__(self):
        return f"{self.user} -> {self.event}"
