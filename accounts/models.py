from django.contrib.auth.models import AbstractUser
from django.db import models
from django.conf import settings


class CustomUser(AbstractUser):
    ROLE_CHOICES = (
        ('CUSTOMER', 'Khách hàng'),
        ('MANAGER', 'Quản lý'),
        ('RECEPTIONIST', 'Lễ tân'),
        ('TECHNICIAN', 'Kỹ thuật viên'),
        ('CASHIER', 'Thu ngân'),
    )

    role = models.CharField(
        max_length=20,
        choices=ROLE_CHOICES,
        default='CUSTOMER'
    )

    # Số điện thoại đăng ký
    phone_number = models.CharField(
        max_length=15,
        blank=True,
        null=True,
        verbose_name="Số điện thoại"
    )

    # Ảnh đại diện
    avatar = models.ImageField(
        upload_to='avatars/',
        blank=True,
        null=True,
        verbose_name="Ảnh đại diện"
    )

    # Ngày sinh
    date_of_birth = models.DateField(
        blank=True,
        null=True,
        verbose_name="Ngày sinh"
    )

    def __str__(self):
        return f"{self.username} - {self.get_role_display()}"


class Notification(models.Model):
    """Lưu trữ các thông báo gửi đến người dùng."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
        verbose_name="Người nhận",
    )

    # Gắn thông báo với đúng phiếu sửa chữa.
    # Nhờ đó khách hàng chỉ xem được thông báo thuộc phiếu của mình.
    ticket = models.ForeignKey(
        "repair.RepairTicket",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="notifications",
        verbose_name="Phiếu sửa chữa",
    )

    title = models.CharField(
        max_length=255,
        verbose_name="Tiêu đề thông báo",
    )

    message = models.TextField(
        verbose_name="Nội dung chi tiết",
    )

    is_read = models.BooleanField(
        default=False,
        verbose_name="Trạng thái đã đọc",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Thời gian gửi",
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Thông báo"
        verbose_name_plural = "Quản lý Thông báo"

    def __str__(self):
        return f"[{self.user.username}] - {self.title}"

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Thông báo"
        verbose_name_plural = "Quản lý Thông báo"

    def __str__(self):
        return f"[{self.user.username}] - {self.title}"


class NewsAndOffer(models.Model):
    title = models.CharField(
        max_length=255,
        verbose_name="Tiêu đề"
    )

    content = models.TextField(
        verbose_name="Nội dung"
    )

    # Cần cài đặt Pillow: pip install Pillow
    image = models.ImageField(
        upload_to='news_images/',
        null=True,
        blank=True,
        verbose_name="Hình ảnh minh họa"
    )

    is_offer = models.BooleanField(
        default=False,
        verbose_name="Đánh dấu là Ưu đãi (Màu đỏ)"
    )

    is_active = models.BooleanField(
        default=True,
        verbose_name="Hiển thị bài viết này"
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Ngày đăng"
    )

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Tin tức & Ưu đãi"
        verbose_name_plural = "Quản lý Tin tức & Ưu đãi"

    def __str__(self):
        return self.title