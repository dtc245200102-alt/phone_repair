"""URLs cho app `accounts`.

Bug đã sửa: 3 path (`profile/`, `profile/edit/`, `profile/delete/`) bị khai
trùng 2 lần mỗi cái. Không gây lỗi (Django vẫn chạy, dùng bản khai sau), nhưng
dư thừa và dễ gây nhầm lẫn khi maintain — ai đó sửa nhầm bản path phía trên
tưởng là đang sửa route thật, trong khi Django route resolver có thể dùng bản
nào tùy version/thứ tự match. Giữ lại đúng 1 bản mỗi route.
"""

from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("login/", views.unified_login, name="login"),
    path("logout/", auth_views.LogoutView.as_view(next_page="accounts:login"), name="logout"),
    path("register/", views.register_customer, name="register"),
    path("dashboard/", views.customer_dashboard, name="customer_dashboard"),
    path("store/", views.store, name="store"),
    path("news-and-offers/", views.news_and_offers, name="news_and_offers"),
    path("news-and-offers/<int:pk>/", views.news_offer_detail, name="news_offer_detail"),
    path("warranty-check/", views.warranty_check, name="warranty_check"),
    path("notification/<int:pk>/", views.notification_detail, name="notification_detail"),
    path("profile/", views.customer_profile, name="customer_profile"),
    path("profile/edit/", views.customer_profile_edit, name="customer_profile_edit"),
    path("profile/delete/", views.customer_delete_account, name="customer_delete_account"),
]