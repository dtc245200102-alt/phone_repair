import json
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from . import admin_ai_service, ai_service
from .models import Customer, Device, RepairTicket

User = get_user_model()


class CustomerAIChatTests(TestCase):
    def setUp(self):
        self.customer = User.objects.create_user(
            username="ai_customer",
            password="StrongPassword123!",
            role="CUSTOMER",
        )

    def test_chat_api_requires_authentication(self):
        response = self.client.post(
            reverse("api_chat"),
            data=json.dumps({"message": "Máy không sạc được"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)

    def test_chat_api_rejects_empty_and_oversized_messages(self):
        self.client.force_login(self.customer)

        empty_response = self.client.post(
            reverse("api_chat"),
            data=json.dumps({"message": "  "}),
            content_type="application/json",
        )
        long_response = self.client.post(
            reverse("api_chat"),
            data=json.dumps({"message": "a" * 2_001}),
            content_type="application/json",
        )

        self.assertEqual(empty_response.status_code, 400)
        self.assertEqual(long_response.status_code, 400)

    def test_chat_api_checks_csrf_for_logged_in_customers(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.customer)
        page_response = client.get(reverse("ai_diagnose"))
        csrf_token = page_response.cookies["csrftoken"].value

        denied_response = client.post(
            reverse("api_chat"),
            data=json.dumps({"message": "Máy không sạc được"}),
            content_type="application/json",
        )
        with patch("repair.views.chat_with_ai", return_value="Gợi ý an toàn"):
            accepted_response = client.post(
                reverse("api_chat"),
                data=json.dumps({"message": "Máy không sạc được"}),
                content_type="application/json",
                HTTP_X_CSRFTOKEN=csrf_token,
            )

        self.assertEqual(denied_response.status_code, 403)
        self.assertEqual(accepted_response.status_code, 200)

    def test_customer_ai_endpoint_requires_authentication(self):
        response = self.client.post(
            reverse("ai_diagnose_api"),
            data={"issue": "Màn hình không sáng"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)


class TechnicianTicketPrivacyTests(TestCase):
    def setUp(self):
        self.technician = User.objects.create_user(
            username="technician_one",
            password="StrongPassword123!",
            role="TECHNICIAN",
        )
        self.other_technician = User.objects.create_user(
            username="technician_two",
            password="StrongPassword123!",
            role="TECHNICIAN",
        )
        customer = Customer.objects.create(
            name="Khách hàng thử nghiệm",
            phone_number="0900000001",
        )
        device = Device.objects.create(
            customer=customer,
            brand="Apple",
            model_name="iPhone 15",
        )
        self.ticket = RepairTicket.objects.create(
            device=device,
            issue_description="Màn hình không sáng",
            technician=self.technician,
        )

    def test_technician_cannot_open_another_technicians_ticket(self):
        self.client.force_login(self.other_technician)

        response = self.client.get(
            reverse("technician_ticket_detail", args=[self.ticket.pk])
        )

        self.assertEqual(response.status_code, 404)

    def test_ai_api_cannot_read_another_technicians_ticket(self):
        self.client.force_login(self.other_technician)

        response = self.client.post(
            reverse("ai_summarize_api", args=[self.ticket.pk]),
            data={},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 404)


class AIFallbackTests(TestCase):
    def test_explanation_fallback_does_not_claim_a_diagnosis(self):
        with patch.object(ai_service, "_get_client", return_value=None):
            explanation = ai_service.explain_service("Máy không lên nguồn")

        self.assertIn("không phải chẩn đoán", explanation)
        self.assertIn("Máy không lên nguồn", explanation)
        self.assertIn("Chưa thể xác định", explanation)

    def test_summary_fallback_reports_notes_without_inventing_a_diagnosis(
        self,
    ):
        with patch.object(ai_service, "_get_client", return_value=None):
            summary = ai_service.summarize_device_condition(
                "Máy nóng khi sạc",
                "Đã thử cáp sạc khác, hiện tượng vẫn còn",
            )

        self.assertIn("Máy nóng khi sạc", summary)
        self.assertIn("Đã thử cáp sạc khác", summary)
        self.assertIn("kiểm tra trực tiếp", summary)
        self.assertNotIn("IC Nguồn", summary)


class RoleDashboardTests(TestCase):
    def test_customer_dashboard_shows_repair_status(self):
        customer_user = User.objects.create_user(
            username="dashboard_customer",
            password="StrongPassword123!",
            role="CUSTOMER",
        )
        customer = Customer.objects.create(
            user=customer_user,
            name="Khách hàng bảng điều khiển",
            phone_number="0900000002",
        )
        device = Device.objects.create(
            customer=customer,
            brand="Samsung",
            model_name="Galaxy S24",
        )
        ticket = RepairTicket.objects.create(
            device=device,
            issue_description="Pin tụt nhanh",
            status="IN_PROGRESS",
        )
        self.client.force_login(customer_user)

        response = self.client.get(reverse("accounts:customer_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Sửa chữa của bạn")
        self.assertContains(response, ticket.code)
        self.assertEqual(response.context["active_ticket_count"], 1)

    def test_technician_dashboard_renders_work_queue(self):
        technician = User.objects.create_user(
            username="dashboard_technician",
            password="StrongPassword123!",
            role="TECHNICIAN",
        )
        self.client.force_login(technician)

        response = self.client.get(reverse("technician_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Danh sách phiếu")
        self.assertContains(response, "Hoàn thành hôm nay")

    def test_manager_ai_pages_render(self):
        manager = User.objects.create_superuser(
            username="dashboard_manager",
            email="manager@example.com",
            password="StrongPassword123!",
        )
        self.client.force_login(manager)

        chat_response = self.client.get(reverse("admin_ai_chat"))
        report_response = self.client.get(reverse("admin_ai_insight"))

        self.assertEqual(chat_response.status_code, 200)
        self.assertContains(chat_response, "Trợ lý AI Quản lý")
        self.assertEqual(report_response.status_code, 200)
        self.assertContains(report_response, "Báo cáo AI tổng quan vận hành")


class RevenueAccountingTests(TestCase):
    def test_partial_note_update_does_not_persist_unrequested_status(self):
        customer = Customer.objects.create(
            name="Khách hàng cập nhật từng phần",
            phone_number="0900000004",
        )
        device = Device.objects.create(
            customer=customer,
            brand="Apple",
            model_name="iPhone 16 Pro",
        )
        ticket = RepairTicket.objects.create(
            device=device,
            issue_description="Không lên nguồn",
            status="PENDING",
        )
        ticket.status = "DONE"
        ticket.notes = "Đã ghi nhận tình trạng."
        ticket.save(update_fields=["notes"])

        ticket.refresh_from_db()

        self.assertEqual(ticket.status, "PENDING")
        self.assertIsNone(ticket.completed_at)

    def test_editing_completed_ticket_does_not_move_revenue_date(self):
        customer = Customer.objects.create(
            name="Khách hàng doanh thu",
            phone_number="0900000003",
        )
        device = Device.objects.create(
            customer=customer,
            brand="Apple",
            model_name="iPhone 16",
        )
        ticket = RepairTicket.objects.create(
            device=device,
            issue_description="Thay pin",
            status="DONE",
            estimated_cost=Decimal("150000"),
        )
        completed_at = timezone.now() - timedelta(days=1)
        ticket.completed_at = completed_at
        ticket.save(update_fields=["completed_at"])
        ticket.notes = "Đã kiểm tra lại sau khi bàn giao."
        ticket.save(update_fields=["notes"])

        completed_date = timezone.localdate(completed_at)
        today = timezone.localdate()

        self.assertEqual(ticket.completed_at, completed_at)
        self.assertEqual(
            admin_ai_service._revenue_in_range(today, today),
            Decimal("0"),
        )
        self.assertEqual(
            admin_ai_service._revenue_in_range(completed_date, completed_date),
            Decimal("150000"),
        )
