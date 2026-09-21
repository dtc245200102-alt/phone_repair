import logging
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib import admin
from django.contrib.auth.decorators import login_required
from django.db.models import Count, F, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
import json
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from .ai_service import chat_with_ai
from django.db import IntegrityError
from django.utils.dateparse import parse_datetime

from accounts.models import Notification
from . import admin_ai_service, ai_service
from .models import (
    AdminAIChatMessage,
    Customer,
    Device,
    Part,
    RepairTicket,
    TicketPart,
    Warranty,
)
from .permissions import (
    AnyStaffRoleReadOnly,
    IsCashierOrManager,
    IsManager,
    IsReceptionistOrManager,
    IsTechnicianOrManager,
)
from .serializers import (
    CustomerSerializer,
    DeviceSerializer,
    PartSerializer,
    RepairTicketSerializer,
    TicketPartSerializer,
    WarrantySerializer,
)

logger = logging.getLogger(__name__)


# ==========================================
# 1. DRF API VIEWSETS (Quản lý Data API)
# ==========================================


class CustomerViewSet(viewsets.ModelViewSet):
    """Dữ liệu khách hàng — Lễ tân tiếp nhận, Quản lý toàn quyền."""

    queryset = Customer.objects.all()
    serializer_class = CustomerSerializer
    permission_classes = [IsReceptionistOrManager]


class DeviceViewSet(viewsets.ModelViewSet):
    queryset = Device.objects.all()
    serializer_class = DeviceSerializer
    permission_classes = [IsReceptionistOrManager]


class RepairTicketViewSet(viewsets.ModelViewSet):
    """Nhân viên (bất kỳ role nào) xem tất cả phiếu; khách hàng chỉ xem phiếu
    của chính mình. Việc TẠO/SỬA/XÓA phiếu chỉ dành cho nhân viên (không phải
    role CUSTOMER) — chi tiết vai trò nào sửa trường gì (VD: chỉ Thu ngân sửa
    `estimated_cost`) nên làm ở tầng serializer/form khi có UI cụ thể hơn.
    """

    serializer_class = RepairTicketSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        # FIX: trước đây trả nhầm Warranty.objects.all() (copy-paste lỗi).
        if user.is_staff:
            return RepairTicket.objects.all()
        return RepairTicket.objects.filter(device__customer__user=user)

    def get_permissions(self):
        if self.action in ("create", "update", "partial_update", "destroy"):
            return [IsAuthenticated(), _StaffWriteOnly()]
        return [IsAuthenticated()]


class _StaffWriteOnly(IsAuthenticated):
    """Chặn role CUSTOMER khỏi tạo/sửa/xóa phiếu qua API (chỉ 4 role nhân viên)."""

    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False
        role = getattr(request.user, "role", None)
        return request.user.is_superuser or role in ("MANAGER", "RECEPTIONIST", "TECHNICIAN", "CASHIER")


class PartViewSet(viewsets.ModelViewSet):
    """Kho linh kiện — mọi nhân viên được xem, chỉ Quản lý được sửa/xóa/thêm."""

    queryset = Part.objects.all()
    serializer_class = PartSerializer
    permission_classes = [AnyStaffRoleReadOnly]


class TicketPartViewSet(viewsets.ModelViewSet):
    """Linh kiện đã dùng cho từng phiếu — Kỹ thuật viên ghi nhận."""

    queryset = TicketPart.objects.select_related("part", "ticket")
    serializer_class = TicketPartSerializer
    permission_classes = [IsTechnicianOrManager]

    def perform_create(self, serializer):
        ticket_part = serializer.save()
        part = ticket_part.part
        part.stock = max(0, part.stock - ticket_part.quantity)
        part.save(update_fields=["stock"])


class WarrantyViewSet(viewsets.ModelViewSet):
    """Thu ngân phát hành bảo hành; khách hàng chỉ xem bảo hành của mình."""

    serializer_class = WarrantySerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.is_staff:
            return Warranty.objects.all()
        # FIX: trước đây lọc theo phone_number (dễ lệch nếu user chưa cập
        # nhật đúng SĐT) -> đổi sang lọc theo liên kết tài khoản thật, đồng
        # bộ với RepairTicketViewSet.
        return Warranty.objects.filter(ticket__device__customer__user=user)

    def get_permissions(self):
        if self.action in ("create", "update", "partial_update", "destroy"):
            return [IsCashierOrManager()]
        return [IsAuthenticated()]


# ==========================================
# 2. DRF API ENDPOINTS (AJAX & API Đặt lịch)
# ==========================================


@api_view(["POST"])
def ai_diagnose_api(request):
    """API chẩn đoán lỗi bằng AI (ngôn ngữ dễ hiểu cho khách), dùng cho AJAX/App."""
    issue_description = request.data.get("issue", "")
    if not issue_description:
        return Response({"error": "Vui lòng cung cấp mô tả lỗi"}, status=400)
    result = ai_service.explain_service(issue_description)
    return Response({"diagnosis": result})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def create_booking_view(request):
    """API Đặt lịch sửa chữa — khách hàng đã đăng nhập tự gửi yêu cầu."""
    name = (request.data.get("customer_name") or "").strip()
    phone = (request.data.get("phone_number") or "").strip()
    brand = (request.data.get("brand") or "").strip()
    model_name = (request.data.get("model_name") or "").strip()
    imei = (request.data.get("imei") or "").strip()
    color = (request.data.get("color") or "").strip()
    issue_desc = (request.data.get("issue_description") or "").strip()
    notes = (request.data.get("notes") or "").strip()
    preferred_time_raw = (request.data.get("preferred_time") or "").strip()

    if not all([phone, brand, model_name, issue_desc]):
        return Response(
            {"error": "Vui lòng điền đầy đủ: số điện thoại, hãng máy, dòng máy và mô tả lỗi."},
            status=400,
        )

    preferred_time = None
    if preferred_time_raw:
        preferred_time = parse_datetime(preferred_time_raw)
        if preferred_time is None:
            return Response({"error": "Thời gian hẹn không hợp lệ."}, status=400)
        if timezone.is_naive(preferred_time):
            preferred_time = timezone.make_aware(preferred_time)

    try:
        customer, _ = Customer.get_or_create_for_user(
            request.user, name=name or None, phone_number=phone
        )

        device_lookup = {"customer": customer, "imei": imei} if imei else None
        if device_lookup:
            device, _ = Device.objects.get_or_create(
                **device_lookup,
                defaults={"brand": brand, "model_name": model_name, "color": color or None},
            )
        else:
            device, _ = Device.objects.get_or_create(
                customer=customer, brand=brand, model_name=model_name, imei=None,
                defaults={"color": color or None},
            )

        ticket = RepairTicket.objects.create(
            device=device,
            issue_description=issue_desc,
            notes=notes or None,
            status='PENDING',
            received_channel='ONLINE',
            preferred_time=preferred_time,
        )
    except ValueError as exc:
        return Response({"error": str(exc)}, status=400)
    except IntegrityError:
        return Response(
            {"error": "Số điện thoại này đã được dùng cho một tài khoản/hồ sơ khách hàng khác."},
            status=400,
        )
    except Exception:
        logger.exception("Lỗi khi tạo phiếu đặt lịch (user=%s, phone=%s)", request.user.pk, phone)
        return Response({"error": "Có lỗi xảy ra, vui lòng thử lại sau."}, status=500)

    return Response(
        {
            "success": True,
            "message": "Đặt lịch thành công! Trung tâm sẽ liên hệ để xác nhận.",
            "ticket_id": ticket.id,
            "ticket_code": ticket.code,
        },
        status=201,
    )


@api_view(["POST"])
@permission_classes([IsTechnicianOrManager])
def ai_summarize_api(request, ticket_id):
    """Chức năng AI số 1: AI tóm tắt tình trạng máy từ ghi chú kỹ thuật."""
    try:
        ticket = RepairTicket.objects.select_related("device__customer").get(pk=ticket_id)
    except RepairTicket.DoesNotExist:
        return Response({"error": "Không tìm thấy phiếu sửa chữa."}, status=404)

    summary = ai_service.summarize_device_condition(
        ticket.issue_description, ticket.notes or ""
    )
    ticket.ai_summary = summary
    ticket.ai_last_generated_at = timezone.now()
    ticket.save(update_fields=["ai_summary", "ai_last_generated_at"])
    return Response({"summary": summary})


@api_view(["POST"])
@permission_classes([IsTechnicianOrManager])
def send_progress_update_api(request, ticket_id):
    """Chức năng AI số 2: AI sinh tin nhắn cập nhật tiến độ cho khách."""
    try:
        ticket = RepairTicket.objects.select_related("device__customer").get(pk=ticket_id)
    except RepairTicket.DoesNotExist:
        return Response({"error": "Không tìm thấy phiếu sửa chữa."}, status=404)

    device_info = ai_service.DeviceInfo(brand=ticket.device.brand, model_name=ticket.device.model_name)
    message = ai_service.generate_progress_message(
        customer_name=ticket.device.customer.name,
        device=device_info,
        status_display=ticket.get_status_display(),
        notes=ticket.notes or "",
        issue_description=ticket.issue_description,
        ai_summary=ticket.ai_summary or "",
    )
    ticket.ai_progress_message = message
    ticket.ai_last_generated_at = timezone.now()
    ticket.save(update_fields=["ai_progress_message", "ai_last_generated_at"])
    _notify_ticket_update(
        ticket,
        title=f"Phiếu {ticket.code}: cập nhật tiến độ sửa chữa",
        message=message,
    )
    return Response({"message": message})


def _compute_admin_insight_data():
    status_display_map = dict(RepairTicket.STATUS_CHOICES)
    status_counts_raw = (
        RepairTicket.objects.values("status")
        .annotate(total=Count("id"))
        .order_by("-total")
    )
    status_counts = {
        status_display_map.get(row["status"], row["status"]): row["total"]
        for row in status_counts_raw
    }

    total_revenue = (
        RepairTicket.objects.filter(status__in=["DONE", "DELIVERED"]).aggregate(
            total=Sum("estimated_cost")
        )["total"]
        or Decimal("0")
    )

    category_display_map = dict(Part.CATEGORY_CHOICES)
    top_issue_categories_raw = (
        TicketPart.objects.values("part__category")
        .annotate(total=Count("id"))
        .order_by("-total")[:5]
    )
    top_issue_categories = [
        (category_display_map.get(row["part__category"], row["part__category"]), row["total"])
        for row in top_issue_categories_raw
    ]

    top_used_parts_raw = (
        TicketPart.objects.values("part__name")
        .annotate(total_qty=Sum("quantity"))
        .order_by("-total_qty")[:5]
    )
    top_used_parts = [(row["part__name"], row["total_qty"]) for row in top_used_parts_raw]

    low_stock_parts = list(
        Part.objects.filter(stock__lte=F("min_stock_threshold")).order_by("stock")
    )

    return {
        "status_counts": status_counts,
        "total_revenue": total_revenue,
        "top_issue_categories": top_issue_categories,
        "top_used_parts": top_used_parts,
        "low_stock_parts": low_stock_parts,
    }


@api_view(["POST"])
@permission_classes([IsManager])
def admin_ai_insight_api(request):
    data = _compute_admin_insight_data()
    report = ai_service.generate_admin_insight_report(
        status_counts=data["status_counts"],
        total_revenue=data["total_revenue"],
        top_issue_categories=data["top_issue_categories"],
        top_used_parts=data["top_used_parts"],
        low_stock_parts=[part.name for part in data["low_stock_parts"]],
    )
    return Response({"report": report})


# ==========================================
# 3. HTML TEMPLATE VIEWS
# ==========================================


@login_required(login_url="accounts:login")
def ai_diagnose_view(request):
    result = None
    if request.method == "POST":
        symptom = request.POST.get("symptom", "").strip()
        if symptom:
            result = ai_service.explain_service(symptom)
    return render(request, "repair/index.html", {"result": result})


@login_required(login_url="accounts:login")
def booking_view(request):
    if request.user.is_staff:
        return redirect("admin:index")
    return render(
        request,
        "repair/booking.html",
        {
            "prefill_name": request.user.get_full_name() or request.user.username,
            "prefill_phone": request.user.phone_number or "",
        },
    )


@login_required(login_url="accounts:login")
def repair_progress_view(request):
    """Khách hàng CHỈ xem được các phiếu sửa chữa thuộc về tài khoản của
    chính mình (lọc theo `device__customer__user=request.user` — không ai
    khác chọc vào được phiếu của khách khác qua view này)."""

    tickets = RepairTicket.objects.filter(
        device__customer__user=request.user
    ).select_related(
        "device",
        "device__customer",
        "technician",
    ).prefetch_related(
        "used_parts__part",
    ).order_by("-created_at")

    return render(
        request,
        "repair/progress.html",
        {
            "tickets": tickets,
        },
    )


def _is_technician_or_manager(user):
    """Kỹ thuật viên hoặc Quản lý (hoặc superuser) mới được vào khu vực kỹ thuật."""
    role = getattr(user, "role", None)
    return bool(user.is_authenticated) and (user.is_superuser or role in ("TECHNICIAN", "MANAGER"))


def _notify_ticket_update(
    ticket,
    title,
    message,
    audience="all",
):
    
    User = get_user_model()
    recipients = []

    customer_user = getattr(
        ticket.device.customer,
        "user",
        None,
    )

    # Gửi đúng cho khách hàng sở hữu phiếu.
    if audience in ("customer", "all"):
        if customer_user is not None:
            recipients.append(customer_user)

    # Gửi cho Admin / Quản lý.
    if audience in ("admin", "all"):
        admin_users = User.objects.filter(
            Q(role="MANAGER") | Q(is_superuser=True)
        )

        if customer_user is not None:
            admin_users = admin_users.exclude(
                pk=customer_user.pk
            )

        recipients.extend(admin_users)

    if not recipients:
        return

    notifications = [
        Notification(
            user=user,
            ticket=ticket,
            title=title,
            message=message,
        )
        for user in recipients
    ]

    Notification.objects.bulk_create(notifications)


def _get_ticket_for_technician(request, ticket_id):
   
    ticket = get_object_or_404(
        RepairTicket.objects.select_related("device", "device__customer", "technician"),
        pk=ticket_id,
    )
    return ticket


def _notify_ticket_update(ticket, title, message, audience="all"):
   
    User = get_user_model()
    recipients = []

    customer_user = getattr(ticket.device.customer, "user", None)
    if audience in ("all", "customer") and customer_user is not None:
        recipients.append(customer_user)

    if audience in ("all", "admin"):
        admin_qs = User.objects.filter(Q(role="MANAGER") | Q(is_superuser=True))
        if recipients:
            admin_qs = admin_qs.exclude(pk=recipients[0].pk)
        recipients.extend(admin_qs)

    if not recipients:
        return

    Notification.objects.bulk_create(
        [Notification(user=user, title=title, message=message) for user in recipients]
    )


@login_required(login_url="accounts:login")
def technician_dashboard_view(request):
   
    if not _is_technician_or_manager(request.user):
        return redirect("accounts:login")

    status_filter = request.GET.get("status", "")
    q = request.GET.get("q", "").strip()

    tickets = RepairTicket.objects.select_related(
        "device", "device__customer", "technician"
    ).order_by("-created_at")

    if getattr(request.user, "role", None) == "TECHNICIAN" and not request.user.is_superuser:
        tickets = tickets.filter(
            Q(technician=request.user) | Q(technician__isnull=True)
        )

    if status_filter:
        tickets = tickets.filter(status=status_filter)

    if q:
        tickets = tickets.filter(
            Q(code__icontains=q)
            | Q(device__customer__name__icontains=q)
            | Q(device__customer__phone_number__icontains=q)
            | Q(device__imei__icontains=q)
        )

    stats = {
        "pending": RepairTicket.objects.filter(status="PENDING").count(),
        "in_progress": RepairTicket.objects.filter(status="IN_PROGRESS").count(),
        "done_today": RepairTicket.objects.filter(
            status="DONE", updated_at__date=timezone.now().date()
        ).count(),
        "mine": RepairTicket.objects.filter(technician=request.user).count(),
    }

    return render(
        request,
        "technician/dashboard.html",
        {
            "tickets": tickets,
            "status_filter": status_filter,
            "q": q,
            "status_choices": RepairTicket.STATUS_CHOICES,
            "stats": stats,
        },
    )


@login_required(login_url="accounts:login")
def technician_ticket_detail_view(request, ticket_id):
   
    if not _is_technician_or_manager(request.user):
        return redirect("accounts:login")

    ticket = _get_ticket_for_technician(request, ticket_id)

    if request.method == "POST" and request.POST.get("action") == "claim":
        ticket.technician = request.user
        ticket.save(update_fields=["technician"])
        return redirect("technician_ticket_detail", ticket_id=ticket.id)

    used_parts = ticket.used_parts.select_related("part").order_by("id")

    return render(
        request,
        "technician/ticket_detail.html",
        {
            "ticket": ticket,
            "used_parts": used_parts,
        },
    )


@login_required(login_url="accounts:login")
def technician_status_update_view(request, ticket_id):
   
    if not _is_technician_or_manager(request.user):
        return redirect("accounts:login")

    ticket = _get_ticket_for_technician(request, ticket_id)
    error = None

    if request.method == "POST":
        new_status = request.POST.get("status")
        notes = request.POST.get("notes", "").strip()
        cost_raw = request.POST.get("estimated_cost", "").strip()

        if new_status not in dict(RepairTicket.STATUS_CHOICES):
            error = "Trạng thái không hợp lệ."
        else:
            if cost_raw:
                try:
                    ticket.estimated_cost = Decimal(cost_raw)
                except Exception:
                    error = "Phí công/dự kiến không hợp lệ, vui lòng nhập số."

            if error is None:
                ticket.status = new_status
                ticket.notes = notes
                if not ticket.technician_id:
                    ticket.technician = request.user
                ticket.save()

                _notify_ticket_update(
                    ticket,
                    title=f"Phiếu {ticket.code}: cập nhật trạng thái",
                    message=(
                        f"Phiếu sửa chữa {ticket.code} ({ticket.device.brand} "
                        f"{ticket.device.model_name}) vừa chuyển sang trạng thái "
                        f'"{ticket.get_status_display()}".'
                        + (f" Ghi chú: {notes}" if notes else "")
                    ),
                )
                return redirect("technician_status_update", ticket_id=ticket.id)

    return render(
        request,
        "technician/status_update.html",
        {
            "ticket": ticket,
            "status_choices": RepairTicket.STATUS_CHOICES,
            "error": error,
        },
    )


@login_required(login_url="accounts:login")
def technician_parts_view(request, ticket_id):
    """CHỨC NĂNG RIÊNG: ghi nhận linh kiện đã dùng cho phiếu (tự trừ kho)."""
    if not _is_technician_or_manager(request.user):
        return redirect("accounts:login")

    ticket = _get_ticket_for_technician(request, ticket_id)
    error = None

    if request.method == "POST":
        part_id = request.POST.get("part_id")
        quantity_raw = request.POST.get("quantity", "1")
        try:
            part = Part.objects.get(pk=part_id)
            quantity = max(1, int(quantity_raw))
        except (Part.DoesNotExist, ValueError, TypeError):
            part = None
            quantity = 0

        if part is None:
            error = "Vui lòng chọn linh kiện hợp lệ."
        elif quantity > part.stock:
            error = f"Kho chỉ còn {part.stock} {part.unit}, không đủ để dùng {quantity}."
        else:
            TicketPart.objects.create(
                ticket=ticket, part=part, quantity=quantity, unit_price=part.price
            )
            part.stock = max(0, part.stock - quantity)
            part.save(update_fields=["stock"])
            if not ticket.technician_id:
                ticket.technician = request.user
                ticket.save(update_fields=["technician"])

            _notify_ticket_update(
                ticket,
                title=f"Phiếu {ticket.code}: đã thêm linh kiện",
                message=(
                    f"Phiếu {ticket.code} vừa được thêm {quantity} {part.unit} "
                    f"\"{part.name}\" ({(part.price * quantity):,.0f} đ). "
                    f"Tổng chi phí hiện tại có thể đã thay đổi."
                ),
            )
            return redirect("technician_parts", ticket_id=ticket.id)

    used_parts = ticket.used_parts.select_related("part").order_by("id")
    available_parts = Part.objects.all().order_by("category", "name")

    return render(
        request,
        "technician/parts_update.html",
        {
            "ticket": ticket,
            "used_parts": used_parts,
            "available_parts": available_parts,
            "error": error,
        },
    )


@login_required(login_url="accounts:login")
def technician_ai_summary_view(request, ticket_id):
    if not _is_technician_or_manager(request.user):
        return redirect("accounts:login")

    ticket = _get_ticket_for_technician(request, ticket_id)
    error = None
    draft_summary = None

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "generate":
            try:
                draft_summary = ai_service.summarize_device_condition(
                    ticket.issue_description, ticket.notes or ""
                )
            except Exception:
                logger.exception("Lỗi khi tạo AI tóm tắt cho phiếu #%s", ticket.id)
                error = "Không thể tạo tóm tắt AI lúc này, vui lòng thử lại."

        elif action in ("save", "send_customer", "send_admin"):
            summary = (request.POST.get("summary") or "").strip()
            if not summary:
                error = "Nội dung tóm tắt đang trống."
                draft_summary = summary
            else:
                ticket.ai_summary = summary
                ticket.ai_last_generated_at = timezone.now()
                ticket.save(update_fields=["ai_summary", "ai_last_generated_at"])

                if action == "send_customer":
                    _notify_ticket_update(
                        ticket,
                        title=f"Phiếu {ticket.code}: cập nhật tóm tắt tình trạng máy",
                        message=summary,
                        audience="customer",
                    )
                elif action == "send_admin":
                    _notify_ticket_update(
                        ticket,
                        title=f"Phiếu {ticket.code}: cập nhật tóm tắt tình trạng máy",
                        message=summary,
                        audience="admin",
                    )

                return redirect("technician_ai_summary", ticket_id=ticket.id)

    return render(
        request,
        "technician/ai_summary.html",
        {"ticket": ticket, "error": error, "draft_summary": draft_summary},
    )


@login_required(login_url="accounts:login")
def technician_ai_progress_view(request, ticket_id):
   
    if not _is_technician_or_manager(request.user):
        return redirect("accounts:login")

    ticket = _get_ticket_for_technician(
        request,
        ticket_id,
    )

    error = None
    draft_message = None

    if request.method == "POST":
        action = request.POST.get("action")

        # ==========================================
        # 1. GEMINI TẠO TIN NHẮN
        # ==========================================
        if action == "generate":
            try:
                device_info = ai_service.DeviceInfo(
                    brand=ticket.device.brand,
                    model_name=ticket.device.model_name,
                )

                draft_message = (
                    ai_service.generate_progress_message(
                        customer_name=ticket.device.customer.name,
                        device=device_info,
                        status_display=ticket.get_status_display(),
                        notes=ticket.notes or "",
                        issue_description=ticket.issue_description,
                        ai_summary=ticket.ai_summary or "",
                    )
                )

            except Exception:
                logger.exception(
                    "Lỗi tạo AI progress cho ticket #%s",
                    ticket.id,
                )

                error = (
                    "Không thể tạo tin nhắn bằng AI lúc này. "
                    "Vui lòng kiểm tra Gemini API và thử lại."
                )

        # ==========================================
        # 2. LƯU / GỬI TIN NHẮN
        # ==========================================
        elif action in (
            "save",
            "send_customer",
            "send_admin",
            "send_all",
        ):
            message = (
                request.POST.get("message") or ""
            ).strip()

            if not message:
                error = "Nội dung tin nhắn không được để trống."
                draft_message = message

            else:
                # ----------------------------------
                # LƯU NỘI DUNG VÀO PHIẾU
                # ----------------------------------
                ticket.ai_progress_message = message
                ticket.ai_last_generated_at = timezone.now()

                ticket.save(
                    update_fields=[
                        "ai_progress_message",
                        "ai_last_generated_at",
                    ]
                )

                title = (
                    f"Phiếu {ticket.code}: "
                    f"cập nhật tiến độ sửa chữa"
                )

                # ----------------------------------
                # CHỈ LƯU - KHÔNG GỬI
                # ----------------------------------
                if action == "save":
                    pass

                # ----------------------------------
                # GỬI KHÁCH HÀNG
                # ----------------------------------
                elif action == "send_customer":
                    _notify_ticket_update(
                        ticket=ticket,
                        title=title,
                        message=message,
                        audience="customer",
                    )

                # ----------------------------------
                # GỬI ADMIN
                # ----------------------------------
                elif action == "send_admin":
                    _notify_ticket_update(
                        ticket=ticket,
                        title=title,
                        message=message,
                        audience="admin",
                    )

                # ----------------------------------
                # GỬI CẢ KHÁCH + ADMIN
                # ----------------------------------
                elif action == "send_all":
                    _notify_ticket_update(
                        ticket=ticket,
                        title=title,
                        message=message,
                        audience="all",
                    )

                return redirect(
                    "technician_ai_progress",
                    ticket_id=ticket.id,
                )

    return render(
        request,
        "technician/ai_progress.html",
        {
            "ticket": ticket,
            "error": error,
            "draft_message": draft_message,
        },
    )


@login_required(login_url="accounts:login")
def technician_ai_explain_view(request, ticket_id):
    if not _is_technician_or_manager(request.user):
        return redirect("accounts:login")

    ticket = _get_ticket_for_technician(request, ticket_id)
    error = None
    draft_explanation = None

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "generate":
            try:
                draft_explanation = ai_service.explain_service(
                    ticket.issue_description, ticket.notes or ""
                )
            except Exception:
                logger.exception("Lỗi khi tạo giải thích dịch vụ cho phiếu #%s", ticket.id)
                error = "Không thể tạo giải thích dịch vụ lúc này, vui lòng thử lại."

        elif action in ("save", "send_customer", "send_admin"):
            explanation = (request.POST.get("explanation") or "").strip()
            if not explanation:
                error = "Nội dung giải thích đang trống."
                draft_explanation = explanation
            else:
                ticket.ai_service_explanation = explanation
                ticket.ai_last_generated_at = timezone.now()
                ticket.save(update_fields=["ai_service_explanation", "ai_last_generated_at"])

                if action == "send_customer":
                    _notify_ticket_update(
                        ticket,
                        title=f"Phiếu {ticket.code}: giải thích dịch vụ sửa chữa",
                        message=explanation,
                        audience="customer",
                    )
                elif action == "send_admin":
                    _notify_ticket_update(
                        ticket,
                        title=f"Phiếu {ticket.code}: giải thích dịch vụ sửa chữa",
                        message=explanation,
                        audience="admin",
                    )

                return redirect("technician_ai_explain", ticket_id=ticket.id)

    return render(
        request,
        "technician/ai_explain.html",
        {"ticket": ticket, "error": error, "draft_explanation": draft_explanation},
    )


def _is_manager_or_admin(user):
    role = getattr(user, "role", None)
    return bool(user.is_authenticated) and (user.is_superuser or role == "MANAGER")


@login_required(login_url="accounts:login")
def admin_ai_insight_view(request):
    if not _is_manager_or_admin(request.user):
        return redirect("accounts:login")

    data = _compute_admin_insight_data()

    ai_report = None
    ai_error = None
    if request.method == "POST" and request.POST.get("action") == "generate_ai_report":
        try:
            ai_report = ai_service.generate_admin_insight_report(
                status_counts=data["status_counts"],
                total_revenue=data["total_revenue"],
                top_issue_categories=data["top_issue_categories"],
                top_used_parts=data["top_used_parts"],
                low_stock_parts=[part.name for part in data["low_stock_parts"]],
            )
        except Exception:
            logger.exception("Lỗi khi tạo báo cáo AI cho Admin")
            ai_error = "Không thể tạo báo cáo AI lúc này, vui lòng thử lại."

    # Dùng lại `each_context` của Django Admin để trang này có đầy đủ
    # sidebar/topmenu (Accounts, Repair, ...) giống hệt các trang admin
    # khác, thay vì render với sidebar trống.
    context = admin.site.each_context(request)
    context.update({
        "title": "Báo cáo AI tổng quan vận hành",
        "status_counts": data["status_counts"],
        "total_revenue": data["total_revenue"],
        "top_issue_categories": data["top_issue_categories"],
        "top_used_parts": data["top_used_parts"],
        "low_stock_parts": data["low_stock_parts"],
        "ai_report": ai_report,
        "ai_error": ai_error,
    })
    return render(request, "admin_panel/ai_dashboard.html", context)


# ==========================================
# TRỢ LÝ AI QUẢN LÝ (khung chat riêng cho Quản lý/Admin)
# ==========================================
@login_required(login_url="accounts:login")
def admin_ai_chat_view(request):
   
    if not _is_manager_or_admin(request.user):
        return redirect("accounts:login")

    history_qs = AdminAIChatMessage.objects.filter(user=request.user).order_by("created_at")
    history_data = [
        {
            "sender": msg.sender,
            "message": msg.message,
            "data_type": msg.data_type,
            "data": msg.data,
            "suggestions": msg.suggestions,
            "created_at": timezone.localtime(msg.created_at).strftime("%H:%M"),
        }
        for msg in history_qs
    ]

    # Dùng lại `each_context` của Django Admin để trang này có đầy đủ
    # sidebar/topmenu (Accounts, Repair, ...) giống hệt các trang admin
    # khác, thay vì render với sidebar trống.
    context = admin.site.each_context(request)
    context.update({
        "title": "Trợ lý AI Quản lý",
        "has_history": bool(history_data),
        "history_json": history_data,
        "quick_questions": admin_ai_service.QUICK_QUESTIONS,
    })
    return render(request, "admin_panel/ai_chat.html", context)


@login_required(login_url="accounts:login")
def admin_ai_chat_api(request):
    
    if not _is_manager_or_admin(request.user):
        return JsonResponse(
            {"success": False, "message": "Bạn không có quyền sử dụng Trợ lý AI Quản lý."},
            status=403,
        )

    if request.method != "POST":
        return JsonResponse(
            {"success": False, "message": "Phương thức không hợp lệ."}, status=405
        )

    try:
        payload = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse(
            {"success": False, "message": "Dữ liệu gửi lên không hợp lệ."}, status=400
        )

    question = (payload.get("message") or "").strip()
    if not question:
        return JsonResponse(
            {"success": False, "message": "Vui lòng nhập câu hỏi."}, status=400
        )

    # Lưu câu hỏi của Quản lý trước, để lịch sử chat không bị mất nội dung
    # câu hỏi ngay cả khi bước gọi AI bên dưới gặp lỗi.
    AdminAIChatMessage.objects.create(user=request.user, sender="user", message=question)

    try:
        result = admin_ai_service.handle_question(question)
    except Exception:
        logger.exception("Lỗi khi xử lý câu hỏi của Trợ lý AI Quản lý")
        return JsonResponse(
            {
                "success": False,
                "message": "Có lỗi xảy ra khi xử lý câu hỏi, vui lòng thử lại.",
            },
            status=500,
        )

    ai_message = AdminAIChatMessage.objects.create(
        user=request.user,
        sender="ai",
        message=result.get("message", ""),
        data_type=result.get("data_type"),
        data=result.get("data"),
        suggestions=result.get("suggestions"),
    )

    return JsonResponse(
        {
            "success": True,
            "sender": "ai",
            "message": ai_message.message,
            "data_type": ai_message.data_type,
            "data": ai_message.data,
            "suggestions": ai_message.suggestions,
            "created_at": timezone.localtime(ai_message.created_at).strftime("%H:%M"),
        }
    )


@csrf_exempt
def api_chat_endpoint(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Lỗi kết nối'}, status=400)

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({'error': 'Dữ liệu gửi lên không hợp lệ.'}, status=400)

    try:
        ai_reply = chat_with_ai(data.get('message', ''))
    except Exception:
        logger.exception("Lỗi khi gọi AI chat")
        return JsonResponse({'error': 'Có lỗi xảy ra, vui lòng thử lại sau.'}, status=500)

    return JsonResponse({'reply': ai_reply})