from __future__ import annotations

import datetime
from decimal import Decimal

from django.db.models import Count, F, Q, Sum
from django.utils import timezone

from . import ai_service
from .models import Part, RepairTicket, TicketPart

# ------------------------------------------------------------------
# Ngưỡng "xử lý lâu" - khai báo tập trung tại đây, không hard-code rải rác.
# ------------------------------------------------------------------
PENDING_DELAY_DAYS = 1
IN_PROGRESS_DELAY_DAYS = 2

# Trạng thái coi là "đã xong việc" khi tính doanh thu (đồng bộ với
# RepairTicket.COST_VISIBLE_STATUSES).
REVENUE_STATUSES = ("DONE", "DELIVERED")

STATUS_LABELS = dict(RepairTicket.STATUS_CHOICES)
CATEGORY_LABELS = dict(Part.CATEGORY_CHOICES)

# 15 câu hỏi gợi ý hiển thị dưới dạng nút bấm trên giao diện chat.
QUICK_QUESTIONS = [
    "Hôm nay cửa hàng hoạt động thế nào?",
    "Tuần này cửa hàng hoạt động thế nào?",
    "Tháng này cửa hàng hoạt động thế nào?",
    "Hiển thị các đơn mới trong ngày",
    "Hiển thị các đơn mới trong tuần",
    "Hiển thị các đơn mới trong tháng",
    "Phiếu nào đang xử lý lâu?",
    "Linh kiện nào sắp hết?",
    "Linh kiện nào được sử dụng nhiều nhất?",
    "Dịch vụ sửa chữa nào phổ biến?",
    "Doanh thu hôm nay là bao nhiêu?",
    "Doanh thu tuần này là bao nhiêu?",
    "Doanh thu tháng này là bao nhiêu?",
    "Có vấn đề gì cần Quản lý chú ý?",
    "Đề xuất công việc cần ưu tiên",
]

_SUGGESTIONS = {
    "overview": [
        "Hiển thị các đơn mới trong ngày",
        "Doanh thu hôm nay là bao nhiêu?",
        "Có vấn đề gì cần Quản lý chú ý?",
    ],
    "ticket_list": [
        "Phiếu nào đang xử lý lâu?",
        "Doanh thu hôm nay là bao nhiêu?",
        "Có vấn đề gì cần Quản lý chú ý?",
    ],
    "delayed": [
        "Có vấn đề gì cần Quản lý chú ý?",
        "Đề xuất công việc cần ưu tiên",
        "Hôm nay cửa hàng hoạt động thế nào?",
    ],
    "revenue": [
        "Doanh thu tuần này là bao nhiêu?",
        "Hôm nay cửa hàng hoạt động thế nào?",
        "Đề xuất công việc cần ưu tiên",
    ],
    "low_stock": [
        "Linh kiện nào được sử dụng nhiều nhất?",
        "Đề xuất công việc cần ưu tiên",
        "Có vấn đề gì cần Quản lý chú ý?",
    ],
    "warnings": [
        "Hôm nay cửa hàng hoạt động thế nào?",
        "Linh kiện nào sắp hết?",
        "Phiếu nào đang xử lý lâu?",
    ],
}


def _fmt_vnd(value) -> str:
    value = float(value or 0)
    return f"{value:,.0f}".replace(",", ".")


def _pct_change(current, previous):
    current = float(current or 0)
    previous = float(previous or 0)
    if not previous:
        return None
    return round((current - previous) / previous * 100)


# ------------------------------------------------------------------
# Khoảng thời gian - dùng timezone của Django (settings.TIME_ZONE / USE_TZ),
# KHÔNG hard-code ngày tháng.
# ------------------------------------------------------------------
def _period_range(period: str):
    today = timezone.localdate()
    if period == "week":
        start = today - datetime.timedelta(days=today.weekday())  # Thứ 2 đầu tuần
        return start, today, "tuần này"
    if period == "month":
        start = today.replace(day=1)
        return start, today, "tháng này"
    return today, today, "hôm nay"


def _previous_period_range(period: str):
    today = timezone.localdate()
    if period == "week":
        this_start = today - datetime.timedelta(days=today.weekday())
        prev_start = this_start - datetime.timedelta(days=7)
        prev_end = this_start - datetime.timedelta(days=1)
        return prev_start, prev_end, "tuần trước"
    if period == "month":
        this_start = today.replace(day=1)
        prev_end = this_start - datetime.timedelta(days=1)
        prev_start = prev_end.replace(day=1)
        return prev_start, prev_end, "tháng trước"
    prev = today - datetime.timedelta(days=1)
    return prev, prev, "hôm qua"


# ------------------------------------------------------------------
# Truy vấn dữ liệu thật (Django ORM)
# ------------------------------------------------------------------
def _tickets_in_range(start_date, end_date):
    return RepairTicket.objects.filter(created_at__date__range=(start_date, end_date))


def _revenue_in_range(start_date, end_date) -> Decimal:
    """Doanh thu = phí công (estimated_cost) + tiền linh kiện, tính trên các
    phiếu đã DONE/DELIVERED theo thời điểm hoàn thành lần đầu. Chỉnh sửa ghi
    chú sau khi hoàn tất không làm doanh thu bị chuyển sang ngày khác.
    """
    labor_total = (
        RepairTicket.objects.filter(
            status__in=REVENUE_STATUSES,
            completed_at__date__range=(start_date, end_date),
        ).aggregate(total=Sum("estimated_cost"))["total"]
        or Decimal("0")
    )
    parts_total = (
        TicketPart.objects.filter(
            ticket__status__in=REVENUE_STATUSES,
            ticket__completed_at__date__range=(start_date, end_date),
        ).aggregate(total=Sum(F("quantity") * F("unit_price")))["total"]
        or Decimal("0")
    )
    return labor_total + parts_total


def _delayed_tickets():
    """Phiếu PENDING quá `PENDING_DELAY_DAYS` ngày hoặc IN_PROGRESS quá
    `IN_PROGRESS_DELAY_DAYS` ngày (tính từ `created_at`)."""
    now = timezone.localtime()
    pending_cutoff = now - datetime.timedelta(days=PENDING_DELAY_DAYS)
    in_progress_cutoff = now - datetime.timedelta(days=IN_PROGRESS_DELAY_DAYS)

    qs = (
        RepairTicket.objects.filter(
            Q(status="PENDING", created_at__lte=pending_cutoff)
            | Q(status="IN_PROGRESS", created_at__lte=in_progress_cutoff)
        )
        .select_related("device")
        .order_by("created_at")
    )

    result = []
    for ticket in qs:
        days_processing = (now - ticket.created_at).days
        result.append(
            {
                "code": ticket.code,
                "device": str(ticket.device) if ticket.device_id else "",
                "status": ticket.get_status_display(),
                "days_processing": days_processing,
            }
        )
    return result


def _low_stock_parts():
    return list(Part.objects.filter(stock__lte=F("min_stock_threshold")).order_by("stock"))


def _out_of_stock_parts():
    return list(Part.objects.filter(stock__lte=0).order_by("name"))


def _top_used_parts(start_date, end_date, limit=5):
    rows = (
        TicketPart.objects.filter(ticket__created_at__date__range=(start_date, end_date))
        .values("part__name")
        .annotate(total_qty=Sum("quantity"), ticket_count=Count("ticket", distinct=True))
        .order_by("-total_qty")[:limit]
    )
    return list(rows)


def _serialize_tickets(qs):
    data = []
    for ticket in qs.select_related("device", "device__customer").order_by("-created_at"):
        customer = ticket.device.customer if ticket.device_id else None
        data.append(
            {
                "code": ticket.code,
                "customer": customer.name if customer else "",
                "device": str(ticket.device) if ticket.device_id else "",
                "status": ticket.get_status_display(),
                "created_at": timezone.localtime(ticket.created_at).strftime("%d/%m/%Y %H:%M"),
            }
        )
    return data


def _build_warnings():
    warnings = []

    low_stock = _low_stock_parts()
    if low_stock:
        has_out_of_stock = any(p.stock <= 0 for p in low_stock)
        warnings.append(
            {
                "level": "red" if has_out_of_stock else "orange",
                "text": f"{len(low_stock)} linh kiện dưới mức tồn kho tối thiểu.",
            }
        )

    delayed = _delayed_tickets()
    if delayed:
        warnings.append(
            {
                "level": "orange",
                "text": f"{len(delayed)} phiếu đang xử lý quá thời gian thông thường.",
            }
        )

    today = timezone.localdate()
    today_count = _tickets_in_range(today, today).count()
    last7_start = today - datetime.timedelta(days=7)
    last7_count = _tickets_in_range(last7_start, today - datetime.timedelta(days=1)).count()
    avg7 = last7_count / 7 if last7_count else 0
    if avg7 and today_count > avg7 * 1.5:
        pct = round((today_count / avg7 - 1) * 100)
        warnings.append(
            {
                "level": "yellow",
                "text": (
                    f"Số phiếu mới hôm nay ({today_count}) cao hơn khoảng "
                    f"{pct}% so với trung bình 7 ngày gần nhất."
                ),
            }
        )

    return warnings


def _overview_stats(period: str):
    start, end, label = _period_range(period)
    qs = _tickets_in_range(start, end)

    status_counts = {STATUS_LABELS.get(code, code): 0 for code in STATUS_LABELS}
    for row in qs.values("status").annotate(total=Count("id")):
        status_counts[STATUS_LABELS.get(row["status"], row["status"])] = row["total"]

    return {
        "label": label,
        "total_tickets": qs.count(),
        "status_counts": status_counts,
        "revenue": _revenue_in_range(start, end),
        "low_stock_count": len(_low_stock_parts()),
        "delayed_count": len(_delayed_tickets()),
    }


# ------------------------------------------------------------------
# Nhận diện intent (rule-based theo từ khóa)
# ------------------------------------------------------------------
def _normalize(text: str) -> str:
    return (text or "").strip().lower()


def detect_intent(question: str) -> str:
    q = _normalize(question)

    def has(*keywords):
        return any(kw in q for kw in keywords)

    # Ưu tiên các intent có từ khóa đặc thù trước, tránh nhầm với "tổng quan".
    if has("sắp hết", "nguy cơ hết hàng", "cần nhập thêm"):
        return "LOW_STOCK"
    if has("hết hàng", "hết linh kiện"):
        return "OUT_OF_STOCK"
    if has("sử dụng nhiều nhất", "dùng nhiều nhất"):
        return "TOP_USED_PARTS"
    if has("dịch vụ sửa chữa", "dịch vụ nào phổ biến", "lỗi phổ biến", "lỗi nào phổ biến"):
        return "TOP_SERVICES"
    if has("xử lý lâu", "tồn đọng", "quá lâu", "cần chú ý", "phiếu nào cần chú ý") and has(
        "phiếu", "đơn"
    ):
        return "TICKET_DELAYED"
    if has("bao nhiêu phiếu đang chờ", "đang chờ") and has("phiếu", "đơn"):
        return "TICKET_PENDING"
    if has("phiếu đang sửa", "đang sửa chữa", "đang xử lý") and has("hiển thị", "danh sách"):
        return "TICKET_IN_PROGRESS"
    if has("đã hoàn thành hôm nay", "hoàn thành hôm nay"):
        return "TICKET_COMPLETED"

    if has("doanh thu"):
        if has("tuần"):
            return "REVENUE_WEEK"
        if has("tháng"):
            return "REVENUE_MONTH"
        return "REVENUE_TODAY"

    if has("đơn mới", "phiếu mới") or (has("hiển thị") and has("phiếu", "đơn")):
        if has("tuần"):
            return "TICKET_WEEK"
        if has("tháng"):
            return "TICKET_MONTH"
        return "TICKET_TODAY"

    if has("bao nhiêu phiếu") or (has("có bao nhiêu", "số lượng phiếu")):
        if has("tuần"):
            return "TICKET_WEEK"
        if has("tháng"):
            return "TICKET_MONTH"
        return "TICKET_TODAY"

    if has("vấn đề gì", "cảnh báo"):
        return "WARNINGS"
    if has("ưu tiên", "nên làm gì", "nên chú ý", "đề xuất", "cần chú ý gì"):
        return "RECOMMENDATIONS"

    if has("hoạt động thế nào", "tình hình", "tổng quan"):
        if has("tuần"):
            return "GENERAL_OVERVIEW_WEEK"
        if has("tháng"):
            return "GENERAL_OVERVIEW_MONTH"
        return "GENERAL_OVERVIEW_TODAY"

    return "GENERAL_CHAT"


# ------------------------------------------------------------------
# Các handler - mỗi handler build message (Python) + context (số liệu đã
# tính) rồi mới gọi Gemini viết phần nhận xét.
# ------------------------------------------------------------------
def _handle_overview(question, period):
    stats = _overview_stats(period)

    lines = [f"📊 Tổng quan {stats['label']}", "", f"Tổng số phiếu mới: {stats['total_tickets']}"]
    for label, count in stats["status_counts"].items():
        lines.append(f"{label}: {count}")
    lines += ["", f"💰 Doanh thu: {_fmt_vnd(stats['revenue'])} VNĐ", "", "⚠️ Cần chú ý:"]
    if stats["delayed_count"] or stats["low_stock_count"]:
        if stats["delayed_count"]:
            lines.append(f"{stats['delayed_count']} phiếu đang xử lý lâu.")
        if stats["low_stock_count"]:
            lines.append(f"{stats['low_stock_count']} linh kiện dưới mức tồn kho tối thiểu.")
    else:
        lines.append("Không có vấn đề nổi bật.")
    message = "\n".join(lines)

    context = (
        f"Tổng số phiếu mới {stats['label']}: {stats['total_tickets']}. "
        f"Phân bố trạng thái: {stats['status_counts']}. "
        f"Doanh thu: {_fmt_vnd(stats['revenue'])} VNĐ. "
        f"Số phiếu xử lý lâu: {stats['delayed_count']}. "
        f"Số linh kiện dưới ngưỡng tồn kho: {stats['low_stock_count']}."
    )
    comment = ai_service.generate_admin_chat_response(question, context)

    return {
        "message": f"{message}\n\n💡 {comment}",
        "data_type": "statistics",
        "data": {
            "label": stats["label"],
            "total_tickets": stats["total_tickets"],
            "status_counts": stats["status_counts"],
            "revenue": float(stats["revenue"]),
            "delayed_count": stats["delayed_count"],
            "low_stock_count": stats["low_stock_count"],
        },
        "suggestions": _SUGGESTIONS["overview"],
    }


def _handle_ticket_list(question, period):
    start, end, label = _period_range(period)
    qs = _tickets_in_range(start, end)
    count = qs.count()
    data = _serialize_tickets(qs)

    message = f"{label.capitalize()} có {count} phiếu sửa chữa mới."
    context = f"Số phiếu mới {label}: {count}."
    comment = ai_service.generate_admin_chat_response(question, context)

    return {
        "message": f"{message}\n\n{comment}",
        "data_type": "ticket_list",
        "data": data,
        "suggestions": _SUGGESTIONS["ticket_list"],
    }


def _handle_ticket_pending(question):
    qs = RepairTicket.objects.filter(status="PENDING")
    count = qs.count()
    data = _serialize_tickets(qs)
    message = f"Hiện có {count} phiếu đang chờ xử lý."
    comment = ai_service.generate_admin_chat_response(
        question, f"Số phiếu đang chờ xử lý hiện tại: {count}."
    )
    return {
        "message": f"{message}\n\n{comment}",
        "data_type": "ticket_list",
        "data": data,
        "suggestions": _SUGGESTIONS["ticket_list"],
    }


def _handle_ticket_in_progress(question):
    qs = RepairTicket.objects.filter(status="IN_PROGRESS")
    count = qs.count()
    data = _serialize_tickets(qs)
    message = f"Hiện có {count} phiếu đang sửa chữa."
    comment = ai_service.generate_admin_chat_response(
        question, f"Số phiếu đang sửa chữa hiện tại: {count}."
    )
    return {
        "message": f"{message}\n\n{comment}",
        "data_type": "ticket_list",
        "data": data,
        "suggestions": _SUGGESTIONS["ticket_list"],
    }


def _handle_ticket_completed_today(question):
    today = timezone.localdate()
    qs = RepairTicket.objects.filter(
        status__in=REVENUE_STATUSES,
        completed_at__date=today,
    )
    count = qs.count()
    data = _serialize_tickets(qs)
    message = f"Hôm nay có {count} phiếu đã hoàn thành."
    comment = ai_service.generate_admin_chat_response(
        question, f"Số phiếu hoàn thành hôm nay: {count}."
    )
    return {
        "message": f"{message}\n\n{comment}",
        "data_type": "ticket_list",
        "data": data,
        "suggestions": _SUGGESTIONS["ticket_list"],
    }


def _handle_ticket_delayed(question):
    delayed = _delayed_tickets()
    count = len(delayed)
    threshold_note = (
        f"(Chờ xử lý quá {PENDING_DELAY_DAYS} ngày hoặc Đang sửa chữa quá "
        f"{IN_PROGRESS_DELAY_DAYS} ngày)"
    )
    if count:
        message = f"Có {count} phiếu đang xử lý quá thời gian thông thường {threshold_note}."
    else:
        message = f"Hiện không có phiếu nào xử lý quá thời gian thông thường {threshold_note}."

    context = (
        f"Số phiếu xử lý lâu: {count}. Ngưỡng áp dụng: PENDING quá "
        f"{PENDING_DELAY_DAYS} ngày, IN_PROGRESS quá {IN_PROGRESS_DELAY_DAYS} ngày."
    )
    comment = ai_service.generate_admin_chat_response(question, context)

    return {
        "message": f"{message}\n\n{comment}",
        "data_type": "ticket_delayed",
        "data": delayed,
        "suggestions": _SUGGESTIONS["delayed"],
    }


def _handle_revenue(question, period):
    start, end, label = _period_range(period)
    prev_start, prev_end, prev_label = _previous_period_range(period)
    revenue = _revenue_in_range(start, end)
    prev_revenue = _revenue_in_range(prev_start, prev_end)
    change = _pct_change(revenue, prev_revenue)

    message = f"💰 Doanh thu {label}: {_fmt_vnd(revenue)} VNĐ."
    context_lines = [f"Doanh thu {label}: {_fmt_vnd(revenue)} VNĐ."]
    if prev_revenue:
        context_lines.append(f"Doanh thu {prev_label}: {_fmt_vnd(prev_revenue)} VNĐ.")
        if change is not None:
            direction = "tăng" if change >= 0 else "giảm"
            message += (
                f" So với {prev_label} ({_fmt_vnd(prev_revenue)} VNĐ), "
                f"doanh thu {direction} {abs(change)}%."
            )
            context_lines.append(f"Tỉ lệ thay đổi so với {prev_label}: {direction} {abs(change)}%.")
    else:
        context_lines.append(f"Chưa có dữ liệu doanh thu {prev_label} để so sánh.")

    comment = ai_service.generate_admin_chat_response(question, "\n".join(context_lines))

    return {
        "message": f"{message}\n\n{comment}",
        "data_type": "revenue",
        "data": {
            "period_label": label,
            "revenue": float(revenue),
            "previous_label": prev_label,
            "previous_revenue": float(prev_revenue),
            "change_percent": change,
        },
        "suggestions": _SUGGESTIONS["revenue"],
    }


def _handle_low_stock(question, only_out_of_stock=False):
    parts = _out_of_stock_parts() if only_out_of_stock else _low_stock_parts()
    count = len(parts)
    data = [
        {
            "name": part.name,
            "category": CATEGORY_LABELS.get(part.category, part.category),
            "stock": part.stock,
            "min_stock_threshold": part.min_stock_threshold,
        }
        for part in parts
    ]
    noun = "hết hàng" if only_out_of_stock else "dưới mức tồn kho tối thiểu"
    message = (
        f"Hiện có {count} linh kiện {noun}."
        if count
        else f"Hiện không có linh kiện nào {noun}."
    )
    if parts:
        context = f"Số linh kiện {noun}: {count}. Danh sách: " + ", ".join(
            f"{p.name} (tồn {p.stock}/ngưỡng {p.min_stock_threshold})" for p in parts[:10]
        )
    else:
        context = f"Không có linh kiện nào {noun}."
    comment = ai_service.generate_admin_chat_response(question, context)

    return {
        "message": f"{message}\n\n{comment}",
        "data_type": "low_stock",
        "data": data,
        "suggestions": _SUGGESTIONS["low_stock"],
    }


def _handle_top_used_parts(question):
    start, end, label = _period_range("month")
    rows = _top_used_parts(start, end, limit=5)
    data = [
        {"name": r["part__name"], "quantity": r["total_qty"], "ticket_count": r["ticket_count"]}
        for r in rows
    ]
    if data:
        message = (
            f"Trong {label}, linh kiện được sử dụng nhiều nhất là "
            f"{data[0]['name']} ({data[0]['quantity']} lượt)."
        )
        context = "Top linh kiện sử dụng nhiều nhất: " + "; ".join(
            f"{d['name']}: {d['quantity']} cái" for d in data
        )
    else:
        message = f"Chưa có đủ dữ liệu sử dụng linh kiện trong {label}."
        context = "Chưa có dữ liệu."
    comment = ai_service.generate_admin_chat_response(question, context)

    return {
        "message": f"{message}\n\n{comment}",
        "data_type": "part_list",
        "data": data,
        "suggestions": _SUGGESTIONS["low_stock"],
    }


def _handle_top_services(question):
    start, end, label = _period_range("month")
    rows = (
        TicketPart.objects.filter(ticket__created_at__date__range=(start, end))
        .values("part__category")
        .annotate(total=Count("id"))
        .order_by("-total")[:5]
    )
    data = [
        {"category": CATEGORY_LABELS.get(r["part__category"], r["part__category"]), "count": r["total"]}
        for r in rows
    ]
    note = "Đây là chỉ số tham khảo dựa trên linh kiện đã sử dụng, không phải thống kê lỗi trực tiếp."
    if data:
        message = (
            f"Trong {label}, nhóm được dùng nhiều nhất là {data[0]['category']} "
            f"({data[0]['count']} lượt). {note}"
        )
        context = "Top nhóm linh kiện (proxy dịch vụ/lỗi): " + "; ".join(
            f"{d['category']}: {d['count']} lượt" for d in data
        )
    else:
        message = f"Chưa có đủ dữ liệu trong {label} để xác định dịch vụ phổ biến."
        context = "Chưa có dữ liệu."
    comment = ai_service.generate_admin_chat_response(question, context)

    return {
        "message": f"{message}\n\n{comment}",
        "data_type": "part_list",
        "data": data,
        "suggestions": _SUGGESTIONS["overview"],
    }


def _handle_warnings(question):
    warnings = _build_warnings()
    icon = {"red": "🔴", "orange": "🟠", "yellow": "🟡"}
    if warnings:
        lines = [f"Quản lý cần chú ý {len(warnings)} vấn đề hôm nay:"]
        lines += [f"{icon.get(w['level'], '⚠️')} {w['text']}" for w in warnings]
        message = "\n".join(lines)
        context = " ".join(w["text"] for w in warnings)
    else:
        message = "Hiện tại chưa phát hiện vấn đề bất thường nào cần chú ý."
        context = "Không có cảnh báo nào."
    comment = ai_service.generate_admin_chat_response(question, context)

    return {
        "message": f"{message}\n\n{comment}",
        "data_type": "warning",
        "data": warnings,
        "suggestions": _SUGGESTIONS["warnings"],
    }


def _handle_recommendations(question):
    items = []

    delayed = _delayed_tickets()
    if delayed:
        items.append(f"Kiểm tra {len(delayed)} phiếu đang xử lý quá lâu.")

    low_stock = _low_stock_parts()
    if low_stock:
        names = ", ".join(p.name for p in low_stock[:3])
        items.append(f"Bổ sung linh kiện sắp hết: {names}.")

    today = timezone.localdate()
    today_count = _tickets_in_range(today, today).count()
    last7_start = today - datetime.timedelta(days=7)
    last7_count = _tickets_in_range(last7_start, today - datetime.timedelta(days=1)).count()
    avg7 = last7_count / 7 if last7_count else 0
    if avg7 and today_count > avg7 * 1.5:
        items.append("Theo dõi lượng phiếu mới vì số phiếu hôm nay cao hơn mức trung bình.")

    if items:
        message = "Những việc Quản lý nên ưu tiên:\n" + "\n".join(
            f"{i}. {item}" for i, item in enumerate(items, start=1)
        )
        context = " ".join(items)
    else:
        message = "Hiện chưa có việc gì cấp bách cần ưu tiên đặc biệt."
        context = "Không có việc cần ưu tiên."
    comment = ai_service.generate_admin_chat_response(question, context)

    return {
        "message": f"{message}\n\n{comment}",
        "data_type": "recommendation",
        "data": items,
        "suggestions": _SUGGESTIONS["warnings"],
    }


def _handle_general_chat(_question):
    return {
        "message": (
            "Tôi chưa có dữ liệu phù hợp trong hệ thống để trả lời chính xác "
            "câu hỏi này. Quản lý có thể thử một trong các câu hỏi gợi ý bên dưới."
        ),
        "data_type": "text",
        "data": None,
        "suggestions": QUICK_QUESTIONS[:4],
    }


_PERIOD_BY_INTENT = {
    "GENERAL_OVERVIEW_TODAY": "today",
    "GENERAL_OVERVIEW_WEEK": "week",
    "GENERAL_OVERVIEW_MONTH": "month",
    "TICKET_TODAY": "today",
    "TICKET_WEEK": "week",
    "TICKET_MONTH": "month",
    "REVENUE_TODAY": "today",
    "REVENUE_WEEK": "week",
    "REVENUE_MONTH": "month",
}


def handle_question(question: str) -> dict:
    """Điểm vào chính: nhận câu hỏi tiếng Việt của Quản lý, trả về dict
    chuẩn hoá để `views.py` lưu lịch sử chat + trả JSON cho frontend."""
    intent = detect_intent(question)

    if intent.startswith("GENERAL_OVERVIEW_"):
        return _handle_overview(question, _PERIOD_BY_INTENT[intent])
    if intent in ("TICKET_TODAY", "TICKET_WEEK", "TICKET_MONTH"):
        return _handle_ticket_list(question, _PERIOD_BY_INTENT[intent])
    if intent == "TICKET_PENDING":
        return _handle_ticket_pending(question)
    if intent == "TICKET_IN_PROGRESS":
        return _handle_ticket_in_progress(question)
    if intent == "TICKET_COMPLETED":
        return _handle_ticket_completed_today(question)
    if intent == "TICKET_DELAYED":
        return _handle_ticket_delayed(question)
    if intent in ("REVENUE_TODAY", "REVENUE_WEEK", "REVENUE_MONTH"):
        return _handle_revenue(question, _PERIOD_BY_INTENT[intent])
    if intent == "LOW_STOCK":
        return _handle_low_stock(question, only_out_of_stock=False)
    if intent == "OUT_OF_STOCK":
        return _handle_low_stock(question, only_out_of_stock=True)
    if intent == "TOP_USED_PARTS":
        return _handle_top_used_parts(question)
    if intent == "TOP_SERVICES":
        return _handle_top_services(question)
    if intent == "WARNINGS":
        return _handle_warnings(question)
    if intent == "RECOMMENDATIONS":
        return _handle_recommendations(question)

    return _handle_general_chat(question)
