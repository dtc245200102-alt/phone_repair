from .models import Notification

def notifications_context(request):
    """Cung cấp số lượng và danh sách thông báo mới nhất cho mọi template."""
    if request.user.is_authenticated:
        unread_count = Notification.objects.filter(user=request.user, is_read=False).count()
        recent_notifications = Notification.objects.filter(user=request.user)[:5]
        return {
            'unread_notifications_count': unread_count,
            'recent_notifications': recent_notifications,
        }
    return {}