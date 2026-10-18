import csv
import io
from datetime import timedelta
from datetime import timezone as dt_timezone

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Category, Event, Notification, Registration, SavedEvent


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


def make_user(name):
    return User.objects.create_user(name, password="pw12345!")


def register(event, user, status=Registration.CONFIRMED):
    return Registration.objects.create(event=event, user=user, status=status)


class ModelTests(TestCase):
    def setUp(self):
        self.host = make_user("host")
        self.event = make_event(self.host)

    def test_seats_left_drops_with_confirmed_registrations(self):
        self.assertEqual(self.event.seats_left, 2)
        register(self.event, make_user("a"))
        self.assertEqual(self.event.seats_left, 1)

    def test_waitlisted_people_do_not_use_seats(self):
        register(self.event, make_user("a"), Registration.WAITLISTED)
        self.assertEqual(self.event.seats_left, 2)

    def test_same_user_cannot_register_twice_at_db_level(self):
        u = make_user("a")
        register(self.event, u)
        with self.assertRaises(Exception):
            register(self.event, u)

    def test_promote_waitlist_fills_free_seats_in_order(self):
        first, second, third = make_user("a"), make_user("b"), make_user("c")
        r1 = register(self.event, first, Registration.WAITLISTED)
        r2 = register(self.event, second, Registration.WAITLISTED)
        r3 = register(self.event, third, Registration.WAITLISTED)
        self.event.promote_waitlist()
        for r in (r1, r2, r3):
            r.refresh_from_db()
        self.assertEqual(
            [r1.status, r2.status, r3.status],
            ["confirmed", "confirmed", "waitlisted"],
        )


class RegisterApiTests(TestCase):
    def setUp(self):
        self.host = make_user("host")
        self.u1, self.u2, self.u3 = make_user("u1"), make_user("u2"), make_user("u3")
        self.event = make_event(self.host, capacity=2)
        self.reg = reverse("api_register", args=[self.event.pk])
        self.cancel = reverse("api_cancel", args=[self.event.pk])

    def post_as(self, user, url):
        self.client.force_login(user)
        return self.client.post(url)

    def test_anonymous_gets_401(self):
        self.assertEqual(self.client.post(self.reg).status_code, 401)

    def test_get_not_allowed(self):
        self.client.force_login(self.u1)
        self.assertEqual(self.client.get(self.reg).status_code, 405)

    def test_register_returns_confirmed_state(self):
        r = self.post_as(self.u1, self.reg)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"state": "confirmed", "seats_left": 1, "position": 0})

    def test_double_register_is_rejected(self):
        self.post_as(self.u1, self.reg)
        r = self.post_as(self.u1, self.reg)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(Registration.objects.count(), 1)

    def test_full_event_puts_person_on_waitlist(self):
        self.post_as(self.u1, self.reg)
        self.post_as(self.u2, self.reg)
        r = self.post_as(self.u3, self.reg)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"state": "waitlisted", "seats_left": 0, "position": 1})

    def test_waitlist_positions_follow_join_order(self):
        for u in (self.u1, self.u2):
            self.post_as(u, self.reg)
        self.post_as(self.u3, self.reg)
        late = make_user("late")
        r = self.post_as(late, self.reg)
        self.assertEqual(r.json()["position"], 2)

    def test_past_event_rejects_registration(self):
        past = make_event(self.host, start_at=timezone.now() - timedelta(days=1))
        r = self.post_as(self.u1, reverse("api_register", args=[past.pk]))
        self.assertEqual(r.status_code, 400)

    def test_cancel_frees_a_seat(self):
        self.post_as(self.u1, self.reg)
        r = self.post_as(self.u1, self.cancel)
        self.assertEqual(r.json(), {"state": "none", "seats_left": 2, "position": 0})

    def test_cancel_promotes_first_person_on_waitlist(self):
        self.post_as(self.u1, self.reg)
        self.post_as(self.u2, self.reg)
        self.post_as(self.u3, self.reg)  # waitlisted
        r = self.post_as(self.u1, self.cancel)
        self.assertEqual(r.json()["seats_left"], 0)
        self.assertEqual(
            Registration.objects.get(user=self.u3).status, Registration.CONFIRMED
        )

    def test_leaving_the_waitlist_does_not_free_a_seat(self):
        self.post_as(self.u1, self.reg)
        self.post_as(self.u2, self.reg)
        self.post_as(self.u3, self.reg)  # waitlisted
        r = self.post_as(self.u3, self.cancel)
        self.assertEqual(r.json(), {"state": "none", "seats_left": 0, "position": 0})
        self.assertEqual(Registration.objects.count(), 2)

    def test_cancel_without_registration_is_rejected(self):
        self.assertEqual(self.post_as(self.u1, self.cancel).status_code, 400)


class ListApiTests(TestCase):
    def setUp(self):
        self.host = make_user("host")
        self.tech = Category.objects.create(name="Tech")
        self.art = Category.objects.create(name="Art")
        make_event(self.host, title="Python Workshop", category=self.tech)
        make_event(self.host, title="Poster Making", category=self.art)
        make_event(
            self.host,
            title="Old Meetup",
            category=self.tech,
            start_at=timezone.now() - timedelta(days=5),
        )

    def get(self, **params):
        r = self.client.get(reverse("api_events"), params)
        self.assertEqual(r.status_code, 200)
        return r.json()

    def titles(self, **params):
        return [e["title"] for e in self.get(**params)["events"]]

    def test_lists_upcoming_only(self):
        self.assertCountEqual(self.titles(), ["Python Workshop", "Poster Making"])

    def test_search_by_text(self):
        self.assertEqual(self.titles(q="python"), ["Python Workshop"])

    def test_filter_by_category(self):
        self.assertEqual(self.titles(category=self.art.pk), ["Poster Making"])

    def test_bad_category_value_is_ignored(self):
        self.assertEqual(len(self.titles(category="abc")), 2)
        self.assertEqual(len(self.titles(category="²")), 2)  # superscript two

    def test_default_order_is_soonest_first(self):
        make_event(self.host, title="Tomorrow", start_at=timezone.now() + timedelta(days=1))
        self.assertEqual(self.titles()[0], "Tomorrow")

    def test_popular_sort_puts_most_registered_first(self):
        quiet = make_event(self.host, title="Quiet", capacity=10)
        busy = make_event(
            self.host, title="Busy", capacity=10,
            start_at=timezone.now() + timedelta(days=9),
        )
        register(busy, make_user("a"))
        register(busy, make_user("b"))
        register(quiet, make_user("c"))
        self.assertEqual(self.titles(sort="popular")[:2], ["Busy", "Quiet"])

    def test_week_filter_excludes_later_events(self):
        make_event(self.host, title="Far away", start_at=timezone.now() + timedelta(days=20))
        self.assertNotIn("Far away", self.titles(when="week"))
        self.assertIn("Far away", self.titles(when="later"))
        self.assertIn("Python Workshop", self.titles(when="week"))

    def test_today_filter_only_returns_todays_events(self):
        end_of_day = timezone.localtime().replace(hour=23, minute=59, second=0, microsecond=0)
        if end_of_day - timezone.now() < timedelta(minutes=3):
            self.skipTest("too close to midnight")
        make_event(self.host, title="Tonight", start_at=end_of_day)
        self.assertEqual(self.titles(when="today"), ["Tonight"])

    def test_available_filter_hides_full_events(self):
        full = make_event(self.host, title="Sold out", capacity=1)
        register(full, make_user("a"))
        self.assertNotIn("Sold out", self.titles(available="1"))
        self.assertIn("Sold out", self.titles())

    def test_available_filter_ignores_waitlisted_people(self):
        e = make_event(self.host, title="Has room", capacity=2)
        register(e, make_user("a"), Registration.WAITLISTED)
        self.assertIn("Has room", self.titles(available="1"))

    def test_paging(self):
        for i in range(10):
            make_event(self.host, title=f"Extra {i}", start_at=timezone.now() + timedelta(days=5, hours=i))
        first = self.get()
        self.assertEqual((len(first["events"]), first["has_next"], first["total"]), (9, True, 12))
        second = self.get(page=2)
        self.assertEqual((len(second["events"]), second["has_next"]), (3, False))

    def test_bad_page_value_falls_back_to_first_page(self):
        self.assertEqual(len(self.get(page="abc")["events"]), 2)
        self.assertEqual(self.get(page=99)["events"], [])

    def test_saved_flag_is_per_user(self):
        user = make_user("fan")
        SavedEvent.objects.create(user=user, event=Event.objects.get(title="Poster Making"))
        self.assertTrue(all(e["saved"] is False for e in self.get()["events"]))
        self.client.force_login(user)
        flags = {e["title"]: e["saved"] for e in self.get()["events"]}
        self.assertEqual(flags, {"Python Workshop": False, "Poster Making": True})


class EventPageTests(TestCase):
    def setUp(self):
        self.host = make_user("host")
        self.other = make_user("other")
        self.event = make_event(self.host)

    def form_data(self, **kw):
        cat = self.event.category
        when = (timezone.now() + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M")
        data = dict(title="Cricket", description="Friendly", venue="Ground",
                    start_at=when, capacity=20, category=cat.pk)
        data.update(kw)
        return data

    def test_home_and_detail_render(self):
        self.assertContains(self.client.get(reverse("home")), "Hack Night")
        r = self.client.get(reverse("event_detail", args=[self.event.pk]))
        self.assertContains(r, "Lab 2")

    def test_home_keeps_filters_from_the_url(self):
        r = self.client.get(reverse("home"), {"q": "nomatch"})
        self.assertNotContains(r, "Hack Night")
        self.assertContains(r, 'value="nomatch"')

    def test_detail_shows_waitlist_state_for_waitlisted_user(self):
        register(self.event, make_user("a"))
        register(self.event, make_user("b"))
        register(self.event, self.other, Registration.WAITLISTED)
        self.client.force_login(self.other)
        r = self.client.get(reverse("event_detail", args=[self.event.pk]))
        self.assertContains(r, 'data-state="waitlisted"')

    def test_create_requires_login(self):
        r = self.client.get(reverse("event_create"))
        self.assertEqual(r.status_code, 302)
        self.assertIn("/login/", r["Location"])

    def test_create_sets_logged_in_user_as_organiser(self):
        self.client.force_login(self.other)
        r = self.client.post(reverse("event_create"), self.form_data())
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Event.objects.get(title="Cricket").organiser, self.other)

    def test_capacity_must_be_positive(self):
        self.client.force_login(self.other)
        r = self.client.post(reverse("event_create"), self.form_data(capacity=0))
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Event.objects.filter(title="Cricket").exists())

    def test_new_event_cannot_start_in_the_past(self):
        self.client.force_login(self.other)
        when = (timezone.now() - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")
        r = self.client.post(reverse("event_create"), self.form_data(start_at=when))
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

    def edit(self, **kw):
        self.client.force_login(self.host)
        when = timezone.localtime(self.event.start_at).strftime("%Y-%m-%dT%H:%M")
        data = dict(title="Hack Night", description="x", venue="Lab 2", start_at=when,
                    capacity=2, category=self.event.category.pk)
        data.update(kw)
        return self.client.post(reverse("event_edit", args=[self.event.pk]), data)

    def test_capacity_cannot_drop_below_confirmed_count(self):
        register(self.event, make_user("a"))
        register(self.event, make_user("b"))
        r = self.edit(capacity=1)
        self.assertEqual(r.status_code, 200)
        self.event.refresh_from_db()
        self.assertEqual(self.event.capacity, 2)

    def test_waitlisted_people_do_not_block_lowering_capacity(self):
        register(self.event, make_user("a"))
        register(self.event, make_user("b"), Registration.WAITLISTED)
        self.assertEqual(self.edit(capacity=1).status_code, 302)

    def test_raising_capacity_promotes_the_waitlist(self):
        register(self.event, make_user("a"))
        register(self.event, make_user("b"))
        waiting = register(self.event, make_user("c"), Registration.WAITLISTED)
        self.edit(capacity=3)
        waiting.refresh_from_db()
        self.assertEqual(waiting.status, Registration.CONFIRMED)

    def test_my_events_lists_going_waitlist_and_hosted(self):
        register(self.event, self.other)
        other_event = make_event(self.host, title="Waitlist Party", capacity=1)
        register(other_event, make_user("x"))
        register(other_event, self.other, Registration.WAITLISTED)
        self.client.force_login(self.other)
        r = self.client.get(reverse("my_events"))
        self.assertContains(r, "Hack Night")
        self.assertContains(r, "Waitlist Party")


class SavedEventTests(TestCase):
    def setUp(self):
        self.host = make_user("host")
        self.user = make_user("fan")
        self.event = make_event(self.host)
        self.url = reverse("api_save", args=[self.event.pk])

    def test_anonymous_gets_401(self):
        self.assertEqual(self.client.post(self.url).status_code, 401)

    def test_get_not_allowed(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_toggle_saves_then_unsaves(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.post(self.url).json(), {"saved": True})
        self.assertEqual(SavedEvent.objects.count(), 1)
        self.assertEqual(self.client.post(self.url).json(), {"saved": False})
        self.assertEqual(SavedEvent.objects.count(), 0)

    def test_saved_page_requires_login(self):
        r = self.client.get(reverse("saved_events"))
        self.assertEqual(r.status_code, 302)

    def test_saved_page_lists_only_my_saved_events(self):
        other_event = make_event(self.host, title="Not Mine")
        SavedEvent.objects.create(user=self.user, event=self.event)
        SavedEvent.objects.create(user=make_user("else"), event=other_event)
        self.client.force_login(self.user)
        r = self.client.get(reverse("saved_events"))
        self.assertContains(r, "Hack Night")
        self.assertNotContains(r, "Not Mine")


class CalendarTests(TestCase):
    def setUp(self):
        self.event = make_event(
            make_user("host"),
            title="Intro, to; Django",
            description="Line one\nLine two",
            start_at=timezone.now().replace(microsecond=0) + timedelta(days=2),
        )

    def test_ics_download_has_event_details(self):
        r = self.client.get(reverse("event_calendar", args=[self.event.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r["Content-Type"].startswith("text/calendar"))
        body = r.content.decode()
        self.assertIn("BEGIN:VEVENT", body)
        self.assertIn("SUMMARY:Intro\\, to\\; Django", body)
        self.assertIn("DESCRIPTION:Line one\\nLine two", body)
        self.assertIn("LOCATION:Lab 2", body)
        stamp = self.event.start_at.astimezone(dt_timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.assertIn(f"DTSTART:{stamp}", body)
        self.assertIn("\r\n", body)

    def test_ics_for_missing_event_is_404(self):
        self.assertEqual(self.client.get(reverse("event_calendar", args=[9999])).status_code, 404)


class DashboardTests(TestCase):
    def setUp(self):
        self.host = make_user("host")
        self.other = make_user("other")
        self.event = make_event(self.host, capacity=1)
        self.going = register(self.event, make_user("alice"))
        self.waiting = register(self.event, make_user("bob"), Registration.WAITLISTED)
        self.page = reverse("event_attendees", args=[self.event.pk])
        self.csv = reverse("event_attendees_csv", args=[self.event.pk])

    def test_anonymous_is_sent_to_login(self):
        self.assertEqual(self.client.get(self.page).status_code, 302)

    def test_non_owner_is_forbidden(self):
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(self.page).status_code, 403)
        self.assertEqual(self.client.get(self.csv).status_code, 403)

    def test_owner_sees_confirmed_and_waitlisted_people(self):
        self.client.force_login(self.host)
        r = self.client.get(self.page)
        self.assertContains(r, "alice")
        self.assertContains(r, "bob")

    def test_check_in_toggles_for_owner(self):
        url = reverse("api_checkin", args=[self.going.pk])
        self.client.force_login(self.host)
        self.assertEqual(self.client.post(url).json(), {"checked_in": True})
        self.assertEqual(self.client.post(url).json(), {"checked_in": False})

    def test_check_in_is_owner_only(self):
        url = reverse("api_checkin", args=[self.going.pk])
        self.assertEqual(self.client.post(url).status_code, 401)
        self.client.force_login(self.other)
        self.assertEqual(self.client.post(url).status_code, 403)
        self.going.refresh_from_db()
        self.assertFalse(self.going.checked_in)

    def test_waitlisted_person_cannot_be_checked_in(self):
        self.client.force_login(self.host)
        r = self.client.post(reverse("api_checkin", args=[self.waiting.pk]))
        self.assertEqual(r.status_code, 400)

    def test_csv_download_lists_everyone(self):
        self.client.force_login(self.host)
        r = self.client.get(self.csv)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r["Content-Type"].startswith("text/csv"))
        self.assertIn("attachment", r["Content-Disposition"])
        rows = list(csv.reader(io.StringIO(r.content.decode())))
        self.assertEqual(rows[0], ["Username", "Status", "Checked in", "Registered at"])
        self.assertEqual({row[0]: row[1] for row in rows[1:]}, {"alice": "confirmed", "bob": "waitlisted"})

    def test_csv_neutralises_spreadsheet_formulas(self):
        evil = User.objects.create_user("+cmd", password="pw12345!")
        register(self.event, evil, Registration.WAITLISTED)
        self.client.force_login(self.host)
        body = self.client.get(self.csv).content.decode()
        self.assertIn("'+cmd", body)
        self.assertNotIn("\n+cmd", body)


class SignupTests(TestCase):
    def test_signup_creates_user_and_logs_in(self):
        r = self.client.post(
            reverse("signup"),
            dict(username="newbie", password1="Str0ng-pass-9", password2="Str0ng-pass-9"),
        )
        self.assertEqual(r.status_code, 302)
        self.assertTrue(User.objects.filter(username="newbie").exists())
        self.assertIn("_auth_user_id", self.client.session)

    def test_custom_404_page_is_used(self):
        with self.settings(DEBUG=False):
            r = self.client.get("/definitely/not/here/")
        self.assertEqual(r.status_code, 404)
        self.assertContains(r, "Page not found", status_code=404)


class AuthPageTests(TestCase):
    def test_wrong_login_shows_a_clear_error_summary(self):
        r = self.client.post(reverse("login"), {"username": "nobody", "password": "wrong-pass-1"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'id="form-errors"')
        self.assertContains(r, 'role="alert"')
        self.assertContains(r, "Wrong username or password")
        self.assertContains(r, reverse("signup"))  # points people without an account to sign up

    def test_signup_with_a_weak_password_lists_every_problem_at_the_top(self):
        r = self.client.post(
            reverse("signup"),
            {"username": "weakling", "password1": "12345678", "password2": "12345678"},
        )
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'id="form-errors"')
        self.assertContains(r, "This password is too common.")
        self.assertContains(r, "This password is entirely numeric.")
        self.assertFalse(User.objects.filter(username="weakling").exists())

    def test_invalid_fields_are_marked_for_screen_readers(self):
        r = self.client.post(
            reverse("signup"),
            {"username": "ok_name", "password1": "Str0ng-pass-9", "password2": "different"},
        )
        self.assertContains(r, 'aria-invalid="true"')

    def test_password_rules_are_short_hints_not_a_long_list(self):
        r = self.client.get(reverse("signup"))
        self.assertContains(r, "At least 8 characters")
        self.assertNotContains(r, "can’t be too similar to your other personal information")

    def test_inputs_have_autofill_hints(self):
        login = self.client.get(reverse("login")).content.decode()
        self.assertIn('autocomplete="username"', login)
        self.assertIn('autocomplete="current-password"', login)
        signup = self.client.get(reverse("signup")).content.decode()
        self.assertIn('autocomplete="new-password"', signup)

    def test_signed_in_user_is_sent_away_from_the_login_page(self):
        self.client.force_login(make_user("already"))
        r = self.client.get(reverse("login"))
        self.assertRedirects(r, reverse("home"), fetch_redirect_response=False)

    def test_login_then_next_page_shows_the_user_over_https_behind_a_proxy(self):
        make_user("sahil")
        with self.settings(
            SESSION_COOKIE_SECURE=True, CSRF_COOKIE_SECURE=True,
            SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https"),
        ):
            proxy = {"secure": True, "HTTP_X_FORWARDED_PROTO": "https"}
            r = self.client.post(
                reverse("login"), {"username": "sahil", "password": "pw12345!"}, **proxy
            )
            self.assertEqual(r.status_code, 302)
            home = self.client.get(reverse("home"), **proxy)
        self.assertContains(home, "Log out")
        self.assertContains(home, "sahil")

    def test_login_with_next_goes_back_to_that_page(self):
        make_user("sahil")
        event = make_event(make_user("host"))
        url = reverse("event_detail", args=[event.pk])
        r = self.client.post(
            reverse("login") + f"?next={url}", {"username": "sahil", "password": "pw12345!", "next": url}
        )
        self.assertRedirects(r, url, fetch_redirect_response=False)


class HostedDatabaseUrlTests(TestCase):
    def test_supabase_pooler_option_is_removed_from_the_url(self):
        from campushub.settings import _clean_db_url

        cleaned = _clean_db_url("postgres://u:p@h:6543/db?sslmode=require&supa=base-pooler.x")
        self.assertIn("sslmode=require", cleaned)
        self.assertNotIn("supa=", cleaned)

    def test_empty_value_stays_empty(self):
        from campushub.settings import _clean_db_url

        self.assertEqual(_clean_db_url(""), "")


class SignupPasswordErrorPlacementTests(TestCase):
    def post(self, p1, p2):
        return self.client.post(reverse("signup"), {"username": "someone", "password1": p1, "password2": p2})

    def test_password_rule_errors_point_at_the_password_field(self):
        form = self.post("12345678", "12345678").context["form"]
        self.assertIn("This password is too common.", form.errors["password1"])
        self.assertNotIn("password2", form.errors)

    def test_mismatch_error_stays_on_the_confirmation_field(self):
        form = self.post("Str0ng-pass-9", "Str0ng-pass-8").context["form"]
        self.assertIn("password2", form.errors)
        self.assertNotIn("password1", form.errors)


class NotificationTests(TestCase):
    def setUp(self):
        self.host = make_user("host")
        self.u1, self.u2, self.u3 = make_user("u1"), make_user("u2"), make_user("u3")
        self.event = make_event(self.host, title="Hack Night", capacity=1)
        register(self.event, self.u1)
        self.waiting = register(self.event, self.u2, Registration.WAITLISTED)
        register(self.event, self.u3, Registration.WAITLISTED)

    def cancel_as(self, user):
        self.client.force_login(user)
        return self.client.post(reverse("api_cancel", args=[self.event.pk]))

    def test_promoted_person_is_notified_and_nobody_else(self):
        self.cancel_as(self.u1)
        mine = Notification.objects.filter(user=self.u2)
        self.assertEqual(mine.count(), 1)
        self.assertIn("Hack Night", mine[0].message)
        self.assertIn("seat", mine[0].message)
        self.assertEqual(mine[0].url, self.event.get_absolute_url())
        self.assertFalse(Notification.objects.filter(user__in=[self.u1, self.u3, self.host]).exists())

    def test_raising_capacity_notifies_the_people_it_promotes(self):
        self.client.force_login(self.host)
        when = timezone.localtime(self.event.start_at).strftime("%Y-%m-%dT%H:%M")
        self.client.post(reverse("event_edit", args=[self.event.pk]), dict(
            title="Hack Night", description="x", venue="Lab 2", start_at=when,
            capacity=3, category=self.event.category.pk))
        self.assertEqual(Notification.objects.filter(message__contains="seat").count(), 2)

    def test_deleting_an_event_tells_everyone_registered_but_not_the_host(self):
        self.client.force_login(self.host)
        self.client.post(reverse("event_delete", args=[self.event.pk]))
        who = set(Notification.objects.values_list("user__username", flat=True))
        self.assertEqual(who, {"u1", "u2", "u3"})
        self.assertIn("cancelled", Notification.objects.first().message)

    def test_page_requires_login(self):
        self.assertEqual(self.client.get(reverse("notifications")).status_code, 302)

    def test_page_lists_only_my_notifications_and_marks_them_read(self):
        Notification.objects.create(user=self.u2, message="For u2")
        Notification.objects.create(user=self.u3, message="For u3")
        self.client.force_login(self.u2)
        r = self.client.get(reverse("notifications"))
        self.assertContains(r, "For u2")
        self.assertNotContains(r, "For u3")
        self.assertFalse(Notification.objects.get(user=self.u2).read_at is None)
        self.assertTrue(Notification.objects.get(user=self.u3).read_at is None)

    def test_bell_shows_unread_count_until_the_page_is_opened(self):
        Notification.objects.create(user=self.u2, message="one")
        Notification.objects.create(user=self.u2, message="two")
        self.client.force_login(self.u2)
        self.assertContains(self.client.get(reverse("home")), 'data-unread="2"')
        self.client.get(reverse("notifications"))
        self.assertContains(self.client.get(reverse("home")), 'data-unread="0"')

    def test_bell_is_hidden_for_visitors(self):
        self.assertNotContains(self.client.get(reverse("home")), "data-unread")


class EmailNotificationTests(TestCase):
    def setUp(self):
        self.host = make_user("host")
        self.event = make_event(self.host, title="Hack Night", capacity=1)

    def promote(self, user):
        reg = register(self.event, user, Registration.WAITLISTED)
        self.event.promote_waitlist()
        return reg

    def test_email_is_sent_when_mail_is_configured_and_the_user_has_an_address(self):
        user = User.objects.create_user("mailme", email="mailme@example.com", password="pw12345!")
        with self.settings(EMAIL_HOST="smtp.example.com"):
            self.promote(user)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["mailme@example.com"])
        self.assertIn("Hack Night", mail.outbox[0].subject)

    def test_no_email_when_mail_is_not_configured(self):
        user = User.objects.create_user("mailme", email="mailme@example.com", password="pw12345!")
        with self.settings(EMAIL_HOST=""):
            self.promote(user)
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(Notification.objects.filter(user=user).count(), 1)

    def test_no_email_when_the_user_gave_no_address(self):
        with self.settings(EMAIL_HOST="smtp.example.com"):
            self.promote(make_user("noaddress"))
        self.assertEqual(len(mail.outbox), 0)

    def test_a_failing_mail_server_does_not_break_the_promotion(self):
        user = User.objects.create_user("mailme", email="mailme@example.com", password="pw12345!")
        with self.settings(EMAIL_HOST="smtp.example.com", EMAIL_BACKEND="events.tests.BrokenBackend"):
            reg = self.promote(user)
        reg.refresh_from_db()
        self.assertEqual(reg.status, Registration.CONFIRMED)
        self.assertEqual(Notification.objects.filter(user=user).count(), 1)

    def test_signup_accepts_an_optional_email(self):
        base = {"password1": "Str0ng-pass-9", "password2": "Str0ng-pass-9"}
        self.client.post(reverse("signup"), {"username": "with_mail", "email": "a@example.com", **base})
        self.client.logout()
        self.client.post(reverse("signup"), {"username": "no_mail", **base})
        self.assertEqual(User.objects.get(username="with_mail").email, "a@example.com")
        self.assertTrue(User.objects.filter(username="no_mail").exists())


from django.core import mail  # noqa: E402
from django.core.mail.backends.base import BaseEmailBackend  # noqa: E402


class BrokenBackend(BaseEmailBackend):
    def send_messages(self, email_messages):
        raise OSError("mail server is down")
