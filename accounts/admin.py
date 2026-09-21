"""Admin cho app `accounts`.

Bug NGHIÊM TRỌNG mới sửa lần này — `CustomUserAdmin` trước đây kế thừa
`admin.ModelAdmin` thường (không phải `UserAdmin`). Hậu quả: form thêm/sửa
user trong trang quản trị hiển thị field `password` như một ô nhập chữ
THƯỜNG, và khi lưu, Django ghi thẳng chuỗi đó vào DB — KHÔNG băm
(hash) bằng `set_password()`. Vì `check_password()` lúc đăng nhập luôn so
sánh với bản băm, mọi tài khoản (đặc biệt là tài khoản Kỹ thuật viên, vốn
theo đúng yêu cầu chỉ được Admin tạo trong trang quản trị chứ không tự đăng
ký) tạo theo cách này sẽ KHÔNG BAO GIỜ đăng nhập được — sai mật khẩu dù gõ
đúng. Đổi sang kế thừa `django.contrib.auth.admin.UserAdmin` (dùng đúng
`UserCreationForm`/`UserChangeForm`, tự băm mật khẩu, có ô "mật khẩu 2 lần"
khi tạo mới) để khắc phục triệt để.

Thêm cùng lúc, đúng theo mô tả bài toán ("kỹ thuật viên đăng nhập chung tài
khoản với các vai trò khác, nhưng KHÔNG được tự đăng ký, chỉ do Admin tạo, và
có trang điều khiển RIÊNG do Admin cấp"):
- `fieldsets`/`add_fieldsets` thêm `role`, `phone_number`, `date_of_birth`,
  `avatar` ngay trong form tạo/sửa user — Admin tạo 1 tài khoản Kỹ thuật viên
  chỉ cần chọn role = "Kỹ thuật viên" và đặt mật khẩu, không cần thao tác gì
  khác.
- Field `role` được tách khỏi block phân quyền Django (`is_staff`,
  `is_superuser`, `groups`...) để rõ ràng: `role` quyết định user đó dùng
  giao diện nào (khách hàng / kỹ thuật viên / admin), còn `is_staff` chỉ
  quyết định có được VÀO trang quản trị Django hay không — 2 khái niệm khác
  nhau, dễ nhầm (xem thêm ghi chú ở `repair/permissions.py`).
- `clean()` trong 2 form: nếu chọn role = Kỹ thuật viên thì tự động ép
  `is_staff = False`, `is_superuser = False`. Lý do: đề bài yêu cầu Kỹ thuật
  viên có "trang điều khiển giao diện riêng" (`technician_dashboard`) chứ
  KHÔNG phải trang quản trị Django — nếu vô tình tick `is_staff` cho họ, họ
  sẽ có thêm đường vào `/admin/` ngoài ý muốn dù luồng đăng nhập vẫn ưu tiên
  đưa họ vào `technician_dashboard` trước (xem `accounts/views.unified_login`).
  Việc ép ở tầng form (thay vì tầng model `save()`) để không ảnh hưởng lệnh
  `createsuperuser` hay các role khác.

Bug đã sửa từ trước (giữ nguyên): `NotificationAdmin.raw_id_fields =
('user',)` khiến Jazzmin hiển thị popup chọn user bằng iframe — nhưng Django
mặc định gửi header `X-Frame-Options: DENY` trên MỌI response admin, nên
chính trang admin tự chặn việc nhúng iframe của chính nó. Đổi sang
`autocomplete_fields` (AJAX/select2, không dùng iframe).
"""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import UserChangeForm, UserCreationForm

from .models import CustomUser, NewsAndOffer, Notification


class _TechnicianNoStaffAccessMixin:
    """Dùng chung cho cả 2 form thêm/sửa: role Kỹ thuật viên thì không được
    có quyền vào trang quản trị Django (xem giải thích ở đầu file)."""

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get("role") == "TECHNICIAN":
            cleaned_data["is_staff"] = False
            cleaned_data["is_superuser"] = False
        return cleaned_data


class CustomUserCreationForm(_TechnicianNoStaffAccessMixin, UserCreationForm):
    """Form TẠO MỚI user trong trang quản trị — có ô mật khẩu x2, tự băm."""

    class Meta(UserCreationForm.Meta):
        model = CustomUser
        # is_staff/is_active phải liệt kê ở đây (không chỉ trong add_fieldsets)
        # vì đây là field model thường — không như password1/password2 được
        # UserCreationForm khai báo sẵn như field riêng của form.
        fields = ("username", "email", "phone_number", "role", "is_staff", "is_active")


class CustomUserChangeForm(_TechnicianNoStaffAccessMixin, UserChangeForm):
    """Form SỬA user đã có — giữ nguyên hành vi mật khẩu mặc định của Django
    (ô mật khẩu hiện là link "đổi mật khẩu", không hiển thị/ghi đè trực tiếp)."""

    class Meta(UserChangeForm.Meta):
        model = CustomUser
        fields = "__all__"


@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    add_form = CustomUserCreationForm
    form = CustomUserChangeForm
    model = CustomUser

    list_display = (
        "username", "email", "role", "phone_number",
        "is_staff", "is_active", "has_customer_profile",
    )
    list_filter = ("role", "is_staff", "is_active")
    search_fields = ("username", "email", "phone_number")
    ordering = ("username",)

    fieldsets = (
        (None, {"fields": ("username", "password")}),
        (
            "Thông tin cá nhân",
            {"fields": ("first_name", "last_name", "email", "phone_number", "date_of_birth", "avatar")},
        ),
        (
            "Vai trò trong hệ thống",
            {
                "fields": ("role",),
                "description": (
                    "Quyết định giao diện đăng nhập sau này: 'Kỹ thuật viên' -> "
                    "trang điều khiển riêng; các vai trò còn lại (trừ Khách hàng) "
                    "-> trang quản trị Django (cần tick thêm 'Là nhân viên (staff)' bên dưới)."
                ),
            },
        ),
        (
            "Phân quyền trang quản trị Django",
            {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")},
        ),
        ("Ngày quan trọng", {"fields": ("last_login", "date_joined")}),
    )

    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "username", "email", "phone_number", "role",
                    "password1", "password2", "is_staff", "is_active",
                ),
            },
        ),
    )

    @admin.display(description="Có hồ sơ Khách hàng?", boolean=True)
    def has_customer_profile(self, obj):
        """Cho thấy tài khoản này đã liên kết với repair.Customer hay chưa —
        giúp phân biệt rõ 'Người sử dụng' (tài khoản đăng nhập) với
        'Danh sách khách hàng' (hồ sơ dùng để gắn phiếu sửa) thay vì để 2 bảng
        trông như trùng nhau."""
        return hasattr(obj, "customer_profile") and obj.customer_profile is not None


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("title", "user", "is_read", "created_at")
    list_filter = ("is_read", "created_at")
    search_fields = ("title", "message", "user__username")
    autocomplete_fields = ["user"]  # trước đây là raw_id_fields -> gây bug iframe


@admin.register(NewsAndOffer)
class NewsAndOfferAdmin(admin.ModelAdmin):
    list_display = ("title", "is_offer", "is_active", "created_at")
    list_filter = ("is_offer", "is_active")
    search_fields = ("title",)