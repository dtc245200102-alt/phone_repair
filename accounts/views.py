"""Views cho app `accounts`.

Bug đã sửa:
- File gốc định nghĩa TRÙNG TÊN `customer_profile`, `customer_profile_edit`,
  `customer_delete_account`, `news_and_offers` (mỗi hàm 2 lần). Python chỉ giữ
  định nghĩa CUỐI CÙNG trong file, các định nghĩa trước bị ghi đè âm thầm.
  Hậu quả: bản `customer_profile` đầu tiên (query `RepairTicket`/`Warranty`
  thật) bị bản thứ hai (gán cứng `repair_history=[]`, `warranty_history=[]`)
  đè lên -> trang hồ sơ khách hàng KHÔNG BAO GIỜ hiển thị lịch sử thật. Đã gộp
  lại thành 1 bản duy nhất, giữ đúng phần truy vấn thật.
- `warranty_check` trước đây chỉ render template, không đọc `request.GET`,
  không tìm kiếm gì cả (form gửi `method="GET"` nhưng view bỏ qua hoàn toàn
  query string) -> tính năng "Tra cứu bảo hành" chỉ là cái vỏ. Đã thêm logic
  tìm theo IMEI hoặc SĐT.
"""

from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.shortcuts import get_object_or_404, redirect, render

from repair.models import Customer, Device, RepairTicket, Warranty

from .forms import CustomerProfileForm, CustomerRegistrationForm
from .models import NewsAndOffer, Notification


def unified_login(request):
    """Đăng nhập chung cho Khách hàng, Kỹ thuật viên và Admin/Nhân viên khác.

    Kỹ thuật viên (role=TECHNICIAN) có khu vực làm việc riêng
    (`technician_dashboard`) thay vì bị đưa vào Django Admin như các role
    nhân viên khác — vì đây là nơi 2 trong 3 chức năng AI của đề bài
    (tóm tắt tình trạng máy, sinh tin nhắn tiến độ) được dùng thực tế.
    """
    if request.user.is_authenticated:
        if getattr(request.user, "role", None) == "TECHNICIAN" and not request.user.is_superuser:
            return redirect("technician_dashboard")
        if request.user.is_staff:
            return redirect("admin:index")
        return redirect("accounts:customer_dashboard")

    if request.method == "POST":
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            if getattr(user, "role", None) == "TECHNICIAN" and not user.is_superuser:
                return redirect("technician_dashboard")
            if user.is_staff:
                return redirect("admin:index")
            return redirect("accounts:customer_dashboard")
    else:
        form = AuthenticationForm()

    return render(request, "accounts/login.html", {"form": form})


def register_customer(request):
    """Đăng ký tài khoản dành riêng cho Khách hàng."""
    if request.user.is_authenticated:
        if request.user.is_staff:
            return redirect("admin:index")
        return redirect("accounts:customer_dashboard")

    if request.method == "POST":
        form = CustomerRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect("accounts:customer_dashboard")
    else:
        form = CustomerRegistrationForm()

    return render(request, "accounts/register.html", {"form": form})


@login_required(login_url="accounts:login")
def customer_dashboard(request):
    """Dashboard dành cho Khách hàng."""
    if request.user.is_staff:
        return redirect("admin:index")
    return render(request, "customer/dashboard.html", {"user": request.user})


@login_required(login_url="accounts:login")
def customer_profile(request):
    """Hồ sơ cá nhân của khách hàng, kèm lịch sử sửa chữa/bảo hành thật.

    (Bản duy nhất sau khi gộp — trước đây có 2 bản trùng tên, bản sau ghi đè
    bản này và luôn trả lịch sử rỗng dù có dữ liệu thật.)
    """
    if request.user.is_staff:
        return redirect("admin:index")

    user = request.user
    # Ưu tiên liên kết trực tiếp qua Customer.user (thêm ở repair/models.py lần
    # này). Nếu chưa có (dữ liệu cũ tạo trước khi có field `user`), dò tạm theo
    # SĐT rồi TỰ GẮN LẠI luôn để lần sau không phải dò nữa (tự "chữa lành" dữ
    # liệu cũ dần dần, không cần chạy script migrate dữ liệu riêng).
    customer = getattr(user, "customer_profile", None)
    if customer is None and user.phone_number:
        customer = Customer.objects.filter(phone_number=user.phone_number, user__isnull=True).first()
        if customer:
            customer.user = user
            customer.save(update_fields=["user"])

    repair_history = RepairTicket.objects.none()
    warranty_history = Warranty.objects.none()
    if customer:
        repair_history = (
            RepairTicket.objects.filter(device__customer=customer)
            .select_related("device", "technician")
            .order_by("-created_at")
        )
        warranty_history = (
            Warranty.objects.filter(ticket__device__customer=customer)
            .select_related("ticket", "ticket__device")
            .order_by("-start_date")
        )

    context = {
        "profile_user": user,
        "customer": customer,
        "repair_history": repair_history,
        "warranty_history": warranty_history,
        "purchase_history": [],  # chưa có model đơn hàng/mua sắm trong hệ thống
    }
    return render(request, "customer/profile.html", context)


@login_required(login_url="accounts:login")
def customer_profile_edit(request):
    """Chỉnh sửa hồ sơ: Họ, Tên, Ngày sinh, Avatar.

    Không cho sửa: username, email, số điện thoại, role (form.Meta.fields đã
    không liệt kê các trường này nên form sẽ tự bỏ qua nếu client cố gửi lên).
    """
    if request.user.is_staff:
        return redirect("admin:index")

    if request.method == "POST":
        form = CustomerProfileForm(request.POST, request.FILES, instance=request.user)
        if form.is_valid():
            form.save()
            return redirect("accounts:customer_profile")
    else:
        form = CustomerProfileForm(instance=request.user)

    return render(
        request, "customer/profile_edit.html", {"form": form, "profile_user": request.user}
    )


@login_required(login_url="accounts:login")
def customer_delete_account(request):
    """Xóa tài khoản khách hàng."""
    if request.user.is_staff:
        return redirect("admin:index")

    if request.method == "POST":
        user = request.user
        logout(request)
        user.delete()
        return redirect("accounts:login")

    return render(request, "customer/profile_delete.html")


@login_required(login_url="accounts:login")
def store(request):
    """Trang Hệ thống cửa hàng dành cho Khách hàng."""
    if request.user.is_staff:
        return redirect("admin:index")
    return render(request, "customer/store.html", {"user": request.user})


@login_required(login_url="accounts:login")
def news_and_offers(request):
    """Danh sách tin tức/ưu đãi đang được kích hoạt."""
    if request.user.is_staff:
        return redirect("admin:index")
    news_list = NewsAndOffer.objects.filter(is_active=True)
    return render(request, "customer/news_offers.html", {"news_list": news_list})


@login_required(login_url="accounts:login")
def news_offer_detail(request, pk):
    """Xem chi tiết 1 tin tức/ưu đãi.

    Trước đây nút "Xem chi tiết" trong `news_offers.html` là 1 thẻ `<button>`
    trơn — không có `href`, không `onclick`, bấm vào không làm gì cả — và
    cũng chưa có view/url/template nào cho trang chi tiết. Thêm mới hoàn toàn.
    """
    if request.user.is_staff:
        return redirect("admin:index")
    item = get_object_or_404(NewsAndOffer, pk=pk, is_active=True)
    return render(request, "customer/news_offer_detail.html", {"item": item})


@login_required(login_url="accounts:login")
def warranty_check(request):
    """Tra cứu bảo hành theo IMEI hoặc số điện thoại.

    Trước đây view này bỏ qua hoàn toàn `request.GET` — form gửi GET nhưng
    không có gì xử lý kết quả tìm kiếm. Giờ đọc `search_code`, tìm theo IMEI
    (Device.imei) trước, không thấy thì thử theo SĐT khách hàng, rồi lấy toàn
    bộ bảo hành liên quan để hiển thị.
    """
    search_code = request.GET.get("search_code", "").strip()
    warranties = None
    searched = bool(search_code)

    if searched:
        warranties = (
            Warranty.objects.filter(ticket__device__imei=search_code)
            .select_related("ticket", "ticket__device", "ticket__device__customer")
        )
        if not warranties.exists():
            warranties = (
                Warranty.objects.filter(ticket__device__customer__phone_number=search_code)
                .select_related("ticket", "ticket__device", "ticket__device__customer")
            )

    context = {
        "user": request.user,
        "search_code": search_code,
        "searched": searched,
        "warranties": warranties,
    }
    return render(request, "customer/warranty_check.html", context)


@login_required(login_url="accounts:login")
def notification_detail(request, pk):
    """Xem chi tiết và đánh dấu đã đọc thông báo."""
    notification = get_object_or_404(Notification, pk=pk, user=request.user)
    if not notification.is_read:
        notification.is_read = True
        notification.save(update_fields=["is_read"])
    return render(request, "customer/notification_detail.html", {"notification": notification})