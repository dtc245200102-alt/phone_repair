from django.urls import path

from . import views


urlpatterns = [
    # -----------------------------
    # Trợ lý AI
    # -----------------------------
    path("ai/", views.ai_diagnose_view, name="ai_diagnose"),

    # -----------------------------
    # Tiến độ sửa chữa (khách hàng)
    # -----------------------------
    path("progress/", views.repair_progress_view, name="repair_progress"),

    # -----------------------------
    # Đặt lịch sửa chữa
    # -----------------------------
    path("booking/", views.booking_view, name="booking"),

    # -----------------------------
    # API đặt lịch / chat
    # -----------------------------
    path("api/booking/", views.create_booking_view, name="create_booking_api"),
    path("api/chat/", views.api_chat_endpoint, name="api_chat"),

    # -----------------------------
    # Khu vực Kỹ thuật viên
    # -----------------------------
    path("technician/", views.technician_dashboard_view, name="technician_dashboard"),

    # Trang tổng của 1 phiếu (thông tin + nút "Nhận phiếu" + link sang từng
    # chức năng riêng bên dưới).
    path(
        "technician/ticket/<int:ticket_id>/",
        views.technician_ticket_detail_view,
        name="technician_ticket_detail",
    ),

    # Mỗi chức năng của kỹ thuật viên giờ có URL/trang RIÊNG:
    path(
        "technician/ticket/<int:ticket_id>/status/",
        views.technician_status_update_view,
        name="technician_status_update",
    ),
    path(
        "technician/ticket/<int:ticket_id>/parts/",
        views.technician_parts_view,
        name="technician_parts",
    ),
    path(
        "technician/ticket/<int:ticket_id>/ai-summary/",
        views.technician_ai_summary_view,
        name="technician_ai_summary",
    ),
    path(
        "technician/ticket/<int:ticket_id>/ai-progress/",
        views.technician_ai_progress_view,
        name="technician_ai_progress",
    ),
    path(
        "technician/ticket/<int:ticket_id>/ai-explain/",
        views.technician_ai_explain_view,
        name="technician_ai_explain",
    ),

    # -----------------------------
    # API JSON (AJAX / app di động) - giữ nguyên cho tích hợp ngoài
    # -----------------------------
    path(
        "api/ticket/<int:ticket_id>/ai-summary/",
        views.ai_summarize_api,
        name="ai_summarize_api",
    ),
    path(
        "api/ticket/<int:ticket_id>/ai-progress/",
        views.send_progress_update_api,
        name="send_progress_update_api",
    ),

    # -----------------------------
    # Khu vực Admin/Quản lý
    # -----------------------------
    path(
        "admin-panel/ai-insight/",
        views.admin_ai_insight_view,
        name="admin_ai_insight",
    ),
    path(
        "api/admin/ai-insight/",
        views.admin_ai_insight_api,
        name="admin_ai_insight_api",
    ),

    # -----------------------------
    # Trợ lý AI Quản lý (chat riêng cho Quản lý/Admin)
    # -----------------------------
    path(
        "admin-panel/ai-chat/",
        views.admin_ai_chat_view,
        name="admin_ai_chat",
    ),
    path(
        "api/admin/ai-chat/",
        views.admin_ai_chat_api,
        name="admin_ai_chat_api",
    ),
]