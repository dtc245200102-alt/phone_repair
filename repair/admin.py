"""Cấu hình Django Admin cho ứng dụng repair."""

from decimal import Decimal, InvalidOperation

from django import forms
from django.contrib import admin
from django.utils.html import format_html

from .models import (
    Customer,
    Device,
    Part,
    RepairTicket,
    TicketPart,
    Warranty,
)


class HasAccountFilter(admin.SimpleListFilter):
    """Lọc khách hàng theo tài khoản đăng nhập."""

    title = "Tài khoản đăng nhập"
    parameter_name = "has_account"

    def lookups(self, request, model_admin):
        return (
            ("yes", "Đã có tài khoản"),
            ("no", "Khách vãng lai (chưa có)"),
        )

    def queryset(self, request, queryset):
        if self.value() == "yes":
            return queryset.exclude(user__isnull=True)

        if self.value() == "no":
            return queryset.filter(user__isnull=True)

        return queryset


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    """Quản lý khách hàng."""

    list_display = (
        "name",
        "phone_number",
        "email",
        "linked_account",
        "created_at",
    )

    search_fields = (
        "name",
        "phone_number",
        "user__username",
        "user__email",
    )

    list_filter = (HasAccountFilter,)

    autocomplete_fields = ["user"]

    @admin.display(description="Tài khoản đăng nhập", boolean=True)
    def linked_account(self, obj):
        return obj.user_id is not None

    @admin.display(description="Email")
    def email(self, obj):
        if obj.user_id and obj.user.email:
            return obj.user.email

        return "—"


@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    """Quản lý thiết bị."""

    list_display = (
        "brand",
        "model_name",
        "imei",
        "customer",
        "customer_phone",
    )

    search_fields = (
        "imei",
        "model_name",
        "customer__name",
        "customer__phone_number",
        "customer__user__email",
    )

    autocomplete_fields = ["customer"]

    @admin.display(description="SĐT khách hàng")
    def customer_phone(self, obj):
        return obj.customer.phone_number


class TicketPartInline(admin.TabularInline):
    """Linh kiện được sử dụng trong phiếu sửa chữa."""

    model = TicketPart
    extra = 1
    autocomplete_fields = ["part"]


class FreeTextMoneyField(forms.CharField):
    """
    Ô nhập tiền tự do.

    Chấp nhận:
    1.500.000
    1500000
    1,500,000
    """

    def __init__(self, *args, **kwargs):
        kwargs.setdefault(
            "widget",
            forms.TextInput(
                attrs={
                    "placeholder": (
                        "VD: 1.500.000 hoặc 1500000"
                    )
                }
            ),
        )

        kwargs.setdefault(
            "help_text",
            (
                "Có thể nhập dấu chấm hoặc dấu phẩy phân cách "
                "hàng nghìn."
            ),
        )

        super().__init__(*args, **kwargs)

    def clean(self, value):
        raw_value = super().clean(value)

        digits_only = "".join(
            char
            for char in (raw_value or "")
            if char.isdigit()
        )

        if not digits_only:
            raise forms.ValidationError(
                "Vui lòng nhập số tiền hợp lệ."
            )

        try:
            return Decimal(digits_only)
        except InvalidOperation as exc:
            raise forms.ValidationError(
                "Số tiền không hợp lệ."
            ) from exc


class RepairTicketAdminForm(forms.ModelForm):
    """Form chỉnh sửa phiếu sửa chữa trong Admin."""

    estimated_cost = FreeTextMoneyField(
        label="Phí dự kiến (VNĐ)"
    )

    class Meta:
        model = RepairTicket
        fields = "__all__"


@admin.register(RepairTicket)
class RepairTicketAdmin(admin.ModelAdmin):
    """
    Quản lý phiếu sửa chữa.

    Admin có thể chỉnh sửa:
    - Thiết bị
    - Kỹ thuật viên
    - Mô tả lỗi
    - Ghi chú
    - Trạng thái
    - Phí dự kiến
    - Kênh tiếp nhận
    - Thời gian mong muốn

    Thông tin khách hàng được lấy tự động từ thiết bị.
    """

    form = RepairTicketAdminForm

    list_display = (
        "code",
        "device",
        "customer_name",
        "customer_phone",
        "technician",
        "status",
        "received_channel",
        "estimated_cost",
        "created_at",
    )

    # Cho phép Admin sửa nhanh trạng thái ngay tại danh sách.
    list_editable = ("status",)

    list_filter = (
        "status",
        "received_channel",
        "created_at",
        "technician",
    )

    search_fields = (
        "code",
        "device__imei",
        "device__model_name",
        "device__customer__name",
        "device__customer__phone_number",
        "device__customer__user__email",
        "device__customer__user__username",
        "issue_description",
    )

    autocomplete_fields = (
        "device",
        "technician",
    )

    inlines = [TicketPartInline]

    # Những thông tin hệ thống / AI / khách hàng chỉ xem.
    readonly_fields = (
        "code",
        "customer_name",
        "customer_phone",
        "customer_email",
        "customer_address",
        "ai_summary",
        "ai_progress_message",
        "ai_service_explanation",
        "ai_last_generated_at",
    )

    fieldsets = (
        (
            "Thông tin phiếu sửa chữa",
            {
                "fields": (
                    "code",
                    "status",
                )
            },
        ),
        (
            "Thông tin khách hàng",
            {
                "description": (
                    "Thông tin khách hàng được lấy tự động "
                    "từ thiết bị của phiếu."
                ),
                "fields": (
                    "customer_name",
                    "customer_phone",
                    "customer_email",
                    "customer_address",
                ),
            },
        ),
        (
            "Thiết bị & kỹ thuật viên",
            {
                "fields": (
                    "device",
                    "technician",
                )
            },
        ),
        (
            "SỬA ĐƠN KHÁCH HÀNG",
            {
                "description": (
                    "Admin có thể cập nhật tình trạng, "
                    "nội dung sửa chữa và chi phí của đơn."
                ),
                "fields": (
                    "issue_description",
                    "notes",
                    "estimated_cost",
                ),
            },
        ),
        (
            "Tiếp nhận",
            {
                "fields": (
                    "received_channel",
                    "preferred_time",
                )
            },
        ),
        (
            "Thông tin AI",
            {
                "classes": ("collapse",),
                "fields": (
                    "ai_summary",
                    "ai_progress_message",
                    "ai_service_explanation",
                    "ai_last_generated_at",
                ),
            },
        ),
    )

    @admin.display(description="Khách hàng")
    def customer_name(self, obj):
        """Hiển thị tên khách hàng của phiếu."""
        if not obj.device or not obj.device.customer:
            return "—"

        return obj.device.customer.name

    @admin.display(description="SĐT khách hàng")
    def customer_phone(self, obj):
        """Hiển thị số điện thoại khách hàng."""
        if not obj.device or not obj.device.customer:
            return "—"

        return obj.device.customer.phone_number

    @admin.display(description="Email khách hàng")
    def customer_email(self, obj):
        """Hiển thị email tài khoản khách hàng."""
        if not obj.device or not obj.device.customer:
            return "—"

        customer = obj.device.customer
        user = getattr(customer, "user", None)

        if user and user.email:
            return user.email

        return "—"

    @admin.display(description="Địa chỉ khách hàng")
    def customer_address(self, obj):
        """Hiển thị địa chỉ khách hàng."""
        if not obj.device or not obj.device.customer:
            return "—"

        return obj.device.customer.address or "—"


class PartAdminForm(forms.ModelForm):
    """Form quản lý giá linh kiện."""

    price = FreeTextMoneyField(
        label="Giá bán (VNĐ)"
    )

    class Meta:
        model = Part
        fields = "__all__"


class PartUsageInline(admin.TabularInline):
    """Lịch sử linh kiện đã được sử dụng."""

    model = TicketPart
    extra = 0
    can_delete = False

    fields = (
        "ticket",
        "quantity",
        "unit_price",
        "subtotal_display",
    )

    readonly_fields = (
        "ticket",
        "quantity",
        "unit_price",
        "subtotal_display",
    )

    @admin.display(description="Thành tiền")
    def subtotal_display(self, obj):
        return f"{obj.subtotal:,.0f} đ"

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Part)
class PartAdmin(admin.ModelAdmin):
    """Quản lý linh kiện."""

    form = PartAdminForm

    list_display = (
        "name",
        "category",
        "unit",
        "formatted_price",
        "stock_badge",
        "stock_value_display",
    )

    list_filter = ("category",)

    search_fields = (
        "name",
        "description",
    )

    inlines = [PartUsageInline]

    @admin.display(description="Giá bán")
    def formatted_price(self, obj):
        return f"{obj.price:,.0f} đ"

    @admin.display(description="Tình trạng tồn kho")
    def stock_badge(self, obj):
        if obj.stock <= 0:
            color = "#dc3545"
            text = f"Hết hàng ({obj.stock})"
        elif obj.is_low_stock:
            color = "#fd7e14"
            text = (
                f"Sắp hết "
                f"({obj.stock}/{obj.min_stock_threshold})"
            )
        else:
            color = "#198754"
            text = f"Còn hàng ({obj.stock})"

        return format_html(
            '<b style="color:{};">{}</b>',
            color,
            text,
        )

    @admin.display(description="Giá trị tồn kho")
    def stock_value_display(self, obj):
        return f"{obj.stock_value:,.0f} đ"


@admin.register(Warranty)
class WarrantyAdmin(admin.ModelAdmin):
    """Quản lý bảo hành."""

    list_display = (
        "code",
        "ticket",
        "customer_name",
        "customer_phone",
        "end_date",
        "active_badge",
    )

    list_filter = (
        "start_date",
        "end_date",
    )

    search_fields = (
        "code",
        "ticket__code",
        "ticket__device__customer__name",
        "ticket__device__customer__phone_number",
        "ticket__device__customer__user__email",
    )

    readonly_fields = ("code",)

    autocomplete_fields = ["ticket"]

    @admin.display(description="Khách hàng")
    def customer_name(self, obj):
        return obj.ticket.device.customer.name

    @admin.display(description="SĐT khách hàng")
    def customer_phone(self, obj):
        return obj.ticket.device.customer.phone_number

    @admin.display(description="Hiệu lực", boolean=True)
    def active_badge(self, obj):
        return obj.is_active