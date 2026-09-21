from decimal import Decimal

from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from django.utils import timezone


class Customer(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="customer_profile",
        verbose_name="Tài khoản đăng nhập (nếu có)",
        help_text="Để trống nếu là khách vãng lai chưa đăng ký tài khoản trên website.",
    )
    name = models.CharField(max_length=100, verbose_name="Tên khách hàng")
    phone_number = models.CharField(max_length=15, unique=True, verbose_name="Số điện thoại")
    address = models.CharField(max_length=255, blank=True, null=True, verbose_name="Địa chỉ")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Ngày tạo")

    class Meta:
        verbose_name = "Khách hàng"
        verbose_name_plural = "Danh sách Khách hàng"

    def __str__(self):
        return f"{self.name} - {self.phone_number}"

    @classmethod
    def get_or_create_for_user(cls, user, *, name=None, phone_number=None):
        customer = getattr(user, "customer_profile", None)
        if customer is not None:
            return customer, False

        phone_number = (phone_number or getattr(user, "phone_number", "") or "").strip()

        if phone_number:
            customer = cls.objects.filter(phone_number=phone_number, user__isnull=True).first()
            if customer is not None:
                customer.user = user
                if name:
                    customer.name = name
                customer.save(update_fields=["user", "name"] if name else ["user"])
                return customer, False

        if not phone_number:
            raise ValueError("Cần số điện thoại để tạo hồ sơ khách hàng mới.")

        customer = cls.objects.create(
            user=user,
            name=name or user.get_full_name() or user.username,
            phone_number=phone_number,
        )
        return customer, True


class Device(models.Model):
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='devices', verbose_name="Khách hàng")
    brand = models.CharField(max_length=50, verbose_name="Hãng sản xuất")
    model_name = models.CharField(max_length=100, verbose_name="Tên dòng máy")
    imei = models.CharField(max_length=20, unique=True, blank=True, null=True, verbose_name="Số IMEI")
    color = models.CharField(max_length=30, blank=True, null=True, verbose_name="Màu sắc")

    class Meta:
        verbose_name = "Thiết bị"
        verbose_name_plural = "Danh sách Thiết bị"

    def __str__(self):
        return f"{self.brand} {self.model_name} ({self.customer.name})"


class RepairTicket(models.Model):
    STATUS_CHOICES = (
        ('PENDING', 'Chờ xử lý'),
        ('IN_PROGRESS', 'Đang sửa chữa'),
        ('DONE', 'Đã hoàn thành'),
        ('DELIVERED', 'Đã giao khách'),
        ('CANCELLED', 'Đã hủy'),
    )

    # Dùng chung cho mọi template để badge trạng thái đồng màu ở mọi trang.
    STATUS_BADGE_CLASS = {
        'PENDING': 'warning text-dark',
        'IN_PROGRESS': 'info text-dark',
        'DONE': 'success',
        'DELIVERED': 'primary',
        'CANCELLED': 'danger',
    }

    # Trạng thái coi như "đã xong việc" -> mới cho khách xem chi phí cuối cùng.
    COST_VISIBLE_STATUSES = ('DONE', 'DELIVERED')

    CHANNEL_CHOICES = (
        ('ONLINE', 'Khách tự đặt lịch online'),
        ('WALK_IN', 'Lễ tân tiếp nhận trực tiếp'),
    )

    code = models.CharField(
        max_length=20, unique=True, blank=True, null=True,
        verbose_name="Mã phiếu sửa chữa",
        help_text="Tự sinh khi lưu, ví dụ SC260900123. Dùng mã này để tra cứu/tìm kiếm.",
    )

    device = models.ForeignKey(Device, on_delete=models.CASCADE, related_name='tickets', verbose_name="Thiết bị")
    technician = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='repair_tasks', verbose_name="Kỹ thuật viên",
    )

    issue_description = models.TextField(verbose_name="Mô tả lỗi")
    notes = models.TextField(blank=True, null=True, verbose_name="Ghi chú thêm")

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING', verbose_name="Trạng thái")
    estimated_cost = models.DecimalField(
        max_digits=10, decimal_places=0, default=0,
        verbose_name="Phí công / phí dự kiến (VNĐ)",
        help_text="Chưa gồm tiền linh kiện — tiền linh kiện được cộng tự động từ mục Linh kiện đã dùng.",
    )

    received_channel = models.CharField(
        max_length=20, choices=CHANNEL_CHOICES, default='WALK_IN',
        verbose_name="Kênh tiếp nhận",
    )
    preferred_time = models.DateTimeField(
        blank=True, null=True,
        verbose_name="Thời gian khách hẹn mang máy đến",
        help_text="Chỉ áp dụng khi khách tự đặt lịch online.",
    )

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Ngày nhận máy")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Cập nhật lần cuối")

    ai_summary = models.TextField(blank=True, null=True, verbose_name="AI Tóm tắt lỗi")
    ai_progress_message = models.TextField(blank=True, null=True, verbose_name="AI Tin nhắn tiến độ")
    ai_service_explanation = models.TextField(blank=True, null=True, verbose_name="AI Giải thích dịch vụ")
    ai_last_generated_at = models.DateTimeField(blank=True, null=True, verbose_name="Thời gian AI tạo lần cuối")

    class Meta:
        verbose_name = "Phiếu sửa chữa"
        verbose_name_plural = "Danh sách Phiếu sửa chữa"

    def __str__(self):
        return f"Phiếu {self.code or f'#{self.id}'} - {self.device} ({self.get_status_display()})"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.code:
            timestamp = (self.created_at or timezone.now()).strftime("%y%m")
            self.code = f"SC{timestamp}{self.pk:05d}"
            super().save(update_fields=["code"])

    @property
    def status_badge_class(self):
        return self.STATUS_BADGE_CLASS.get(self.status, "secondary")

    @property
    def parts_cost(self):
        """Tổng tiền linh kiện đã dùng cho phiếu này."""
        total = Decimal("0")
        for used in self.used_parts.all():
            total += used.subtotal
        return total

    @property
    def total_cost(self):
        """Tổng chi phí = phí công/dự kiến + tiền linh kiện."""
        return (self.estimated_cost or Decimal("0")) + self.parts_cost

    @property
    def is_cost_visible_to_customer(self):
        """Chỉ hiện chi phí cuối cùng cho khách khi KTV/admin đã cập nhật
        trạng thái là 'Đã hoàn thành' hoặc 'Đã giao khách'."""
        return self.status in self.COST_VISIBLE_STATUSES


class Part(models.Model):
    CATEGORY_CHOICES = (
        ('SCREEN', 'Màn hình'),
        ('BATTERY', 'Pin'),
        ('CAMERA', 'Camera'),
        ('SPEAKER', 'Loa / Mic'),
        ('CHARGING', 'Cụm sạc / Cáp'),
        ('CASE', 'Vỏ / Khung'),
        ('OTHER', 'Khác'),
    )

    name = models.CharField(max_length=100, verbose_name="Tên linh kiện")
    category = models.CharField(
        max_length=20, choices=CATEGORY_CHOICES, default='OTHER', verbose_name="Loại linh kiện"
    )
    unit = models.CharField(max_length=20, default="Cái", verbose_name="Đơn vị tính")
    price = models.DecimalField(max_digits=10, decimal_places=0, verbose_name="Giá bán (VNĐ)")
    stock = models.IntegerField(default=0, verbose_name="Số lượng tồn kho")
    min_stock_threshold = models.PositiveIntegerField(
        default=5, verbose_name="Ngưỡng cảnh báo sắp hết hàng",
        help_text="Khi tồn kho <= ngưỡng này, hệ thống sẽ đánh dấu 'Sắp hết hàng'.",
    )
    description = models.TextField(blank=True, null=True, verbose_name="Mô tả / Ghi chú")

    class Meta:
        verbose_name = "Linh kiện"
        verbose_name_plural = "Danh sách Linh kiện"
        ordering = ["category", "name"]

    def __str__(self):
        return f"{self.name} - Tồn: {self.stock}"

    @property
    def is_low_stock(self):
        return self.stock <= self.min_stock_threshold

    @property
    def stock_value(self):
        return self.price * self.stock


class Warranty(models.Model):
    code = models.CharField(
        max_length=20, unique=True, blank=True, null=True,
        verbose_name="Mã bảo hành",
        help_text="Tự sinh khi lưu, ví dụ BH260900045. Cấp mã này cho khách để tra cứu.",
    )
    ticket = models.OneToOneField(RepairTicket, on_delete=models.CASCADE, related_name='warranty', verbose_name="Phiếu sửa chữa")
    start_date = models.DateField(auto_now_add=True, verbose_name="Ngày bắt đầu")
    end_date = models.DateField(verbose_name="Ngày kết thúc")
    terms = models.TextField(blank=True, null=True, verbose_name="Điều kiện bảo hành")

    class Meta:
        verbose_name = "Bảo hành"
        verbose_name_plural = "Danh sách Bảo hành"

    def __str__(self):
        return f"Bảo hành {self.code or f'phiếu #{self.ticket_id}'}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.code:
            timestamp = (self.start_date or timezone.now().date()).strftime("%y%m")
            self.code = f"BH{timestamp}{self.pk:05d}"
            super().save(update_fields=["code"])

    @property
    def is_active(self):
        return self.end_date >= timezone.now().date()


class TicketPart(models.Model):
    """Bảng trung gian lưu lịch sử linh kiện đã sử dụng cho từng phiếu sửa chữa."""

    ticket = models.ForeignKey(RepairTicket, on_delete=models.CASCADE, related_name="used_parts")
    part = models.ForeignKey(Part, on_delete=models.PROTECT, related_name="usages")
    quantity = models.PositiveIntegerField(default=1, verbose_name="Số lượng")
    unit_price = models.DecimalField(max_digits=10, decimal_places=0, verbose_name="Đơn giá lúc sửa")

    class Meta:
        verbose_name = "Linh kiện đã dùng"
        verbose_name_plural = "Linh kiện đã dùng"

    @property
    def subtotal(self):
        return self.quantity * self.unit_price

    def __str__(self):
        return f"{self.part.name} (x{self.quantity}) - Phiếu #{self.ticket.id}"


class AdminAIChatMessage(models.Model):
    """Lịch sử hội thoại của "Trợ lý AI Quản lý".

    Mỗi tin nhắn (của Quản lý hoặc của AI) được lưu thành 1 dòng, gắn với
    đúng tài khoản Quản lý đã hỏi — nhờ vậy khi quay lại trang, Quản lý vẫn
    xem lại được toàn bộ hội thoại cũ của chính mình (giống Zalo/Messenger),
    và Quản lý này không thấy được lịch sử chat của Quản lý khác.
    """

    SENDER_CHOICES = (
        ('user', 'Quản lý'),
        ('ai', 'Trợ lý AI'),
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='admin_ai_chat_messages',
        verbose_name="Quản lý",
    )
    sender = models.CharField(
        max_length=10, choices=SENDER_CHOICES, verbose_name="Người gửi"
    )
    message = models.TextField(verbose_name="Nội dung")

    # Cho phép frontend biết cần hiển thị dạng bảng/danh sách nào (nếu có).
    data_type = models.CharField(
        max_length=30, blank=True, null=True, verbose_name="Loại dữ liệu"
    )
    data = models.JSONField(
        blank=True, null=True, encoder=DjangoJSONEncoder, verbose_name="Dữ liệu kèm theo"
    )
    suggestions = models.JSONField(
        blank=True, null=True, encoder=DjangoJSONEncoder, verbose_name="Câu hỏi gợi ý tiếp theo"
    )

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Thời gian")

    class Meta:
        verbose_name = "Tin nhắn AI Quản lý"
        verbose_name_plural = "Lịch sử chat AI Quản lý"
        ordering = ["created_at"]

    def __str__(self):
        preview = (self.message or "")[:40]
        return f"[{self.get_sender_display()}] {self.user} - {preview}"