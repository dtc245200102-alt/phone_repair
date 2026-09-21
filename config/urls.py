from django.contrib import admin
from django.shortcuts import redirect
from django.urls import include, path

from django.conf import settings
from django.conf.urls.static import static


def home_redirect(request):
    """
    Điều hướng trang chủ theo trạng thái đăng nhập.
    """
    if not request.user.is_authenticated:
        return redirect("accounts:login")

    if getattr(request.user, "role", None) == "TECHNICIAN" and not request.user.is_superuser:
        return redirect("technician_dashboard")

    if request.user.is_staff:
        return redirect("admin:index")

    return redirect("accounts:customer_dashboard")


def admin_login_redirect(request):
    """
    Không sử dụng trang đăng nhập mặc định của Django Admin.

    Tất cả người dùng được đưa về cổng đăng nhập chung.
    Sau khi đăng nhập:
        - Admin -> /admin/
        - Khách hàng -> /account/dashboard/
    """
    return redirect("accounts:login")


urlpatterns = [
    # Trang đăng nhập Admin được chuyển về cổng đăng nhập chung
    path(
        "admin/login/",
        admin_login_redirect,
        name="admin_login_redirect",
    ),

    # Django Admin
    path("admin/", admin.site.urls),

    # Trang chủ
    path("", home_redirect, name="home"),

    # Các chức năng sửa chữa / AI
    path("", include("repair.urls")),

    # Hệ thống tài khoản
    path("account/", include("accounts.urls")),
]
urlpatterns += static(
    settings.MEDIA_URL,
    document_root=settings.MEDIA_ROOT
)