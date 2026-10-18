from .models import Notification


def unread_notifications(request):
    user = request.user
    if not user.is_authenticated:
        return {}
    return {"unread_count": Notification.objects.filter(user=user, read_at__isnull=True).count()}
