from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.contrib.auth.models import User
from django.utils import timezone

from .models import Event, Registration


class BootstrapFormMixin:
    """Give every field the Bootstrap look."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            css = "form-select" if isinstance(field.widget, forms.Select) else "form-control"
            field.widget.attrs["class"] = css


class EventForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Event
        fields = ["title", "category", "description", "venue", "start_at", "capacity"]
        widgets = {
            "start_at": forms.DateTimeInput(
                attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"
            ),
            "description": forms.Textarea(attrs={"rows": 5}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["start_at"].input_formats = ["%Y-%m-%dT%H:%M"]

    def clean_start_at(self):
        when = self.cleaned_data["start_at"]
        if not self.instance.pk and when < timezone.now():
            raise forms.ValidationError("Pick a date and time in the future.")
        return when

    def clean_capacity(self):
        cap = self.cleaned_data["capacity"]
        if cap < 1:
            raise forms.ValidationError("Capacity must be at least 1.")
        if self.instance.pk:
            booked = self.instance.registrations.filter(status=Registration.CONFIRMED).count()
            if cap < booked:
                raise forms.ValidationError(
                    f"{booked} people are already confirmed, so capacity cannot go below that."
                )
        return cap


class LoginForm(BootstrapFormMixin, AuthenticationForm):
    error_messages = {
        **AuthenticationForm.error_messages,
        "invalid_login": (
            "Wrong username or password. Check for typos, or create an account "
            "if you have not signed up on this site yet."
        ),
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].widget.attrs["autofocus"] = True


class SignupForm(BootstrapFormMixin, UserCreationForm):
    class Meta:
        model = User
        fields = ["username", "email"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["email"].help_text = "Optional. Only used to email you when a waitlist seat opens up."
        self.fields["email"].widget.attrs["autocomplete"] = "email"
        self.fields["username"].help_text = "Letters, digits and @ . + - _ only, with no spaces."
        self.fields["password1"].help_text = "At least 8 characters. Not a common password and not only numbers."
        self.fields["password2"].help_text = "Type the same password again."

    def add_error(self, field, error):
        # Django files the password-rule errors under the confirmation box. When both boxes
        # match, any error on the confirmation is a rule error, so show it under "Password".
        if field == "password2" and self.cleaned_data.get("password1") == self.data.get("password2"):
            field = "password1"
        super().add_error(field, error)
