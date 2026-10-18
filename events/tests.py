from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Category, Event, Registration


def make_event(organiser, **kw):
    cat = kw.pop("category", None) or Category.objects.get_or_create(name="Tech")[0]
    data = dict(
        title="Hack Night",
        description="Build something in one night.",
        venue="Lab 2",
        start_at=timezone.now() + timedelta(days=3),
        capacity=2,
        category=cat,
        organiser=organiser,
    )
    data.update(kw)
    return Event.objects.create(**data)


class ModelTests(TestCase):
    def setUp(self):
        self.host = User.objects.create_user("host", password="pw12345!")
        self.event = make_event(self.host)

    def test_seats_left_drops_with_registrations(self):
        self.assertEqual(self.event.seats_left, 2)
        u = User.objects.create_user("a", password="pw12345!")
        Registration.objects.create(event=self.event, user=u)
        self.assertEqual(self.event.seats_left, 1)

    def test_same_user_cannot_register_twice_at_db_level(self):
        u = User.objects.create_user("a", password="pw12345!")
        Registration.objects.create(event=self.event, user=u)
        with self.assertRaises(Exception):
            Registration.objects.create(event=self.event, user=u)


class RegisterApiTests(TestCase):
    def setUp(self):
        self.host = User.objects.create_user("host", password="pw12345!")
        self.u1 = User.objects.create_user("u1", password="pw12345!")
        self.u2 = User.objects.create_user("u2", password="pw12345!")
        self.u3 = User.objects.create_user("u3", password="pw12345!")
        self.event = make_event(self.host, capacity=2)
        self.reg = reverse("api_register", args=[self.event.pk])
        self.cancel = reverse("api_cancel", args=[self.event.pk])

    def test_anonymous_gets_401(self):
        r = self.client.post(self.reg)
        self.assertEqual(r.status_code, 401)

    def test_get_not_allowed(self):
        self.client.force_login(self.u1)
        self.assertEqual(self.client.get(self.reg).status_code, 405)

    def test_register_returns_seats_left(self):
        self.client.force_login(self.u1)
        r = self.client.post(self.reg)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"registered": True, "seats_left": 1})

    def test_double_register_is_rejected(self):
        self.client.force_login(self.u1)
        self.client.post(self.reg)
        r = self.client.post(self.reg)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(Registration.objects.count(), 1)

    def test_full_event_rejects_new_registration(self):
        for u in (self.u1, self.u2):
            self.client.force_login(u)
            self.client.post(self.reg)
        self.client.force_login(self.u3)
        r = self.client.post(self.reg)
        self.assertEqual(r.status_code, 400)
        self.assertIn("full", r.json()["error"].lower())

    def test_past_event_rejects_registration(self):
        past = make_event(self.host, start_at=timezone.now() - timedelta(days=1))
        self.client.force_login(self.u1)
        r = self.client.post(reverse("api_register", args=[past.pk]))
        self.assertEqual(r.status_code, 400)

    def test_cancel_frees_a_seat(self):
        self.client.force_login(self.u1)
        self.client.post(self.reg)
        r = self.client.post(self.cancel)
        self.assertEqual(r.json(), {"registered": False, "seats_left": 2})

    def test_cancel_without_registration_is_rejected(self):
        self.client.force_login(self.u1)
        self.assertEqual(self.client.post(self.cancel).status_code, 400)


class ListApiTests(TestCase):
    def setUp(self):
        host = User.objects.create_user("host", password="pw12345!")
        self.tech = Category.objects.create(name="Tech")
        self.art = Category.objects.create(name="Art")
        make_event(host, title="Python Workshop", category=self.tech)
        make_event(host, title="Poster Making", category=self.art)
        make_event(
            host,
            title="Old Meetup",
            category=self.tech,
            start_at=timezone.now() - timedelta(days=5),
        )

    def titles(self, **params):
        r = self.client.get(reverse("api_events"), params)
        self.assertEqual(r.status_code, 200)
        return [e["title"] for e in r.json()["events"]]

    def test_lists_upcoming_only(self):
        self.assertCountEqual(self.titles(), ["Python Workshop", "Poster Making"])

    def test_search_by_text(self):
        self.assertEqual(self.titles(q="python"), ["Python Workshop"])

    def test_filter_by_category(self):
        self.assertEqual(self.titles(category=self.art.pk), ["Poster Making"])

    def test_bad_category_value_is_ignored(self):
        self.assertEqual(len(self.titles(category="abc")), 2)
        self.assertEqual(len(self.titles(category="\u00b2")), 2)  # superscript two


class EventPageTests(TestCase):
    def setUp(self):
        self.host = User.objects.create_user("host", password="pw12345!")
        self.other = User.objects.create_user("other", password="pw12345!")
        self.event = make_event(self.host)

    def test_home_and_detail_render(self):
        self.assertContains(self.client.get(reverse("home")), "Hack Night")
        r = self.client.get(reverse("event_detail", args=[self.event.pk]))
        self.assertContains(r, "Lab 2")

    def test_create_requires_login(self):
        r = self.client.get(reverse("event_create"))
        self.assertEqual(r.status_code, 302)
        self.assertIn("/login/", r["Location"])

    def test_create_sets_logged_in_user_as_organiser(self):
        cat = Category.objects.create(name="Sports")
        self.client.force_login(self.other)
        when = (timezone.now() + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M")
        r = self.client.post(
            reverse("event_create"),
            dict(title="Cricket", description="Friendly", venue="Ground",
                 start_at=when, capacity=20, category=cat.pk),
        )
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Event.objects.get(title="Cricket").organiser, self.other)

    def test_capacity_must_be_positive(self):
        cat = Category.objects.create(name="Sports")
        self.client.force_login(self.other)
        when = (timezone.now() + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M")
        r = self.client.post(
            reverse("event_create"),
            dict(title="Cricket", description="x", venue="Ground",
                 start_at=when, capacity=0, category=cat.pk),
        )
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Event.objects.filter(title="Cricket").exists())

    def test_new_event_cannot_start_in_the_past(self):
        cat = Category.objects.create(name="Sports")
        self.client.force_login(self.other)
        when = (timezone.now() - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")
        r = self.client.post(
            reverse("event_create"),
            dict(title="Cricket", description="x", venue="Ground",
                 start_at=when, capacity=5, category=cat.pk),
        )
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Event.objects.filter(title="Cricket").exists())

    def test_only_owner_can_edit_or_delete(self):
        self.client.force_login(self.other)
        self.assertEqual(
            self.client.get(reverse("event_edit", args=[self.event.pk])).status_code, 403
        )
        self.assertEqual(
            self.client.post(reverse("event_delete", args=[self.event.pk])).status_code, 403
        )
        self.assertTrue(Event.objects.filter(pk=self.event.pk).exists())

    def test_owner_can_delete(self):
        self.client.force_login(self.host)
        r = self.client.post(reverse("event_delete", args=[self.event.pk]))
        self.assertEqual(r.status_code, 302)
        self.assertFalse(Event.objects.filter(pk=self.event.pk).exists())

    def test_capacity_cannot_drop_below_registered(self):
        u = User.objects.create_user("a", password="pw12345!")
        v = User.objects.create_user("b", password="pw12345!")
        Registration.objects.create(event=self.event, user=u)
        Registration.objects.create(event=self.event, user=v)
        self.client.force_login(self.host)
        when = self.event.start_at.astimezone().strftime("%Y-%m-%dT%H:%M")
        r = self.client.post(
            reverse("event_edit", args=[self.event.pk]),
            dict(title="Hack Night", description="x", venue="Lab 2",
                 start_at=when, capacity=1, category=self.event.category.pk),
        )
        self.assertEqual(r.status_code, 200)
        self.event.refresh_from_db()
        self.assertEqual(self.event.capacity, 2)

    def test_my_events_lists_registered_and_hosted(self):
        Registration.objects.create(event=self.event, user=self.other)
        self.client.force_login(self.other)
        self.assertContains(self.client.get(reverse("my_events")), "Hack Night")


class SignupTests(TestCase):
    def test_signup_creates_user_and_logs_in(self):
        r = self.client.post(
            reverse("signup"),
            dict(username="newbie", password1="Str0ng-pass-9", password2="Str0ng-pass-9"),
        )
        self.assertEqual(r.status_code, 302)
        self.assertTrue(User.objects.filter(username="newbie").exists())
        self.assertIn("_auth_user_id", self.client.session)
