"""Test cho app `accounts`.

File gốc (`accounts/tests.py`) đang rỗng hoàn toàn. Thêm test cho:
- Đăng ký khách hàng luôn ra role CUSTOMER, is_staff=False (đúng logic trong
  CustomerRegistrationForm.save()).
- Trang hồ sơ khách hàng phải hiển thị ĐÚNG lịch sử sửa chữa thật — đây là
  test hồi quy (regression test) cho đúng bug "2 hàm customer_profile trùng
  tên, bản sau ghi đè bản đúng" vừa sửa ở accounts/views.py. Nếu bug đó quay
  lại (VD: ai đó paste nhầm code cũ vào), test này sẽ FAIL ngay.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from repair.models import Customer, Device, RepairTicket

User = get_user_model()


class CustomerRegistrationTests(TestCase):
    def test_register_creates_customer_role_and_non_staff_user(self):
        response = self.client.post(
            reverse("accounts:register"),
            {
                "username": "khach_moi",
                "email": "khach@example.com",
                "phone_number": "0911111111",
                "password1": "MatKhauManh123!",
                "password2": "MatKhauManh123!",
            },
        )
        user = User.objects.get(username="khach_moi")
        self.assertEqual(user.role, "CUSTOMER")
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertEqual(response.status_code, 302)  # redirect sau khi đăng ký thành công


class CustomerProfileHistoryTests(TestCase):
    """Regression test cho bug 2 hàm customer_profile trùng tên đã sửa."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="chi_hoa", password="MatKhauManh123!", phone_number="0922222222", role="CUSTOMER"
        )
        self.customer = Customer.objects.create(name="Chị Hoa", phone_number="0922222222")
        self.device = Device.objects.create(customer=self.customer, brand="Apple", model_name="iPhone 14")
        self.ticket = RepairTicket.objects.create(device=self.device, issue_description="Vỡ màn hình")

    def test_profile_page_shows_real_repair_history(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("accounts:customer_profile"))
        self.assertEqual(response.status_code, 200)
        # Nếu bug cũ quay lại (bản customer_profile gán cứng repair_history=[]),
        # context này sẽ rỗng dù ticket đã tồn tại -> assertion dưới sẽ fail.
        self.assertEqual(len(response.context["repair_history"]), 1)
        self.assertEqual(response.context["repair_history"][0], self.ticket)