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
    def confirmed_count(self):
        # list views annotate `booked` so we don't run one count query per card
        booked = getattr(self, "booked", None)
        if booked is None:
            booked = self.registrations.filter(status=Registration.CONFIRMED).count()
        return booked

    @property
    def waitlist_count(self):
        waiting = getattr(self, "waiting", None)
        if waiting is None:
            waiting = self.registrations.filter(status=Registration.WAITLISTED).count()
        return waiting

    @property
    def seats_left(self):
        return max(self.capacity - self.confirmed_count, 0)

    @property
    def is_full(self):
        return self.seats_left == 0

    @property
    def is_past(self):
        return self.start_at < timezone.now()

    @property
    def fill_percent(self):
        return min(100, round(self.confirmed_count * 100 / self.capacity)) if self.capacity else 100

    @property
    def hue(self):
        # a stable colour per category, used for the card accent
        return (self.category_id * 67) % 360

    def promote_waitlist(self):
        """Move people from the waitlist into free seats, earliest first."""
        free = self.capacity - self.registrations.filter(status=Registration.CONFIRMED).count()
        if free <= 0:
            return
        queue = self.registrations.filter(status=Registration.WAITLISTED).order_by("created_at", "id")
        for reg in queue[:free]:
            reg.status = Registration.CONFIRMED
            reg.save(update_fields=["status"])


class Registration(models.Model):
    CONFIRMED = "confirmed"
    WAITLISTED = "waitlisted"
    STATUS_CHOICES = [(CONFIRMED, "Confirmed"), (WAITLISTED, "Waitlisted")]

    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="registrations")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="registrations"
    )
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=CONFIRMED)
    checked_in = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["event", "user"], name="one_seat_per_user")
        ]

    def __str__(self):
        return f"{self.user} -> {self.event} ({self.status})"

    @property
    def waitlist_position(self):
        if self.status != self.WAITLISTED:
            return 0
        ahead = self.event.registrations.filter(status=self.WAITLISTED).filter(
            models.Q(created_at__lt=self.created_at)
            | models.Q(created_at=self.created_at, id__lt=self.id)
        )
        return ahead.count() + 1


class SavedEvent(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="saved_events"
    )
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="saves")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "event"], name="one_save_per_user")
        ]
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user} saved {self.event}"
