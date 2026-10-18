from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.contrib.auth.models import User
from django.utils import timezone

from .models import Event


class EventForm(forms.ModelForm):
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
        for name, field in self.fields.items():
            css = "form-select" if name == "category" else "form-control"
            field.widget.attrs["class"] = css

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
            booked = self.instance.registrations.count()
            if cap < booked:
                raise forms.ValidationError(
                    f"{booked} people have already registered, so capacity cannot go below that."
                )
        return cap


class LoginForm(AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-control"


class SignupForm(UserCreationForm):
    class Meta:
        model = User
        fields = ["username"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-control"
