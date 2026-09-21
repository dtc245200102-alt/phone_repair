"""Permission theo đúng 4 vai trong accounts.CustomUser.ROLE_CHOICES.

Lượt trước mình tạm dùng `IsAdminUser` (chỉ kiểm tra `is_staff`) cho các
ViewSet vì chưa thấy `accounts/models.py`. Giờ đã biết `CustomUser.role` gồm
MANAGER / RECEPTIONIST / TECHNICIAN / CASHIER / CUSTOMER, thay bằng permission
đúng nghiệp vụ (đề bài mục 3.1.1: "phân quyền quản lý, lễ tân, kỹ thuật viên,
thu ngân").

LƯU Ý QUAN TRỌNG: `role` KHÔNG tự động đồng bộ với `is_staff`. Khi tạo tài
khoản nhân viên trong Django Admin, phải tick `is_staff=True` THỦ CÔNG ngoài
việc chọn role, nếu không họ sẽ không thể đăng nhập vào /admin/ dù có role
đúng — đây là 1 bẫy dễ gặp khi demo, nên nhớ.
"""

from rest_framework.permissions import SAFE_METHODS, BasePermission

MANAGER = "MANAGER"
RECEPTIONIST = "RECEPTIONIST"
TECHNICIAN = "TECHNICIAN"
CASHIER = "CASHIER"


class HasRole(BasePermission):
    """Cho phép nếu user thuộc 1 trong các role liệt kê ở `allowed_roles`.

    Quản lý (MANAGER) và superuser luôn được phép, không cần liệt kê lại ở
    từng ViewSet con.
    """

    allowed_roles: tuple = ()

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated):
            return False
        role = getattr(user, "role", None)
        if user.is_superuser or role == MANAGER:
            return True
        return role in self.allowed_roles


class IsReceptionistOrManager(HasRole):
    """Lễ tân: tiếp nhận khách hàng, thiết bị, phiếu sửa mới."""

    allowed_roles = (RECEPTIONIST,)


class IsTechnicianOrManager(HasRole):
    """Kỹ thuật viên: cập nhật ghi chú kỹ thuật, trạng thái, linh kiện đã dùng."""

    allowed_roles = (TECHNICIAN,)


class IsCashierOrManager(HasRole):
    """Thu ngân: chốt phí sửa chữa, phát hành bảo hành."""

    allowed_roles = (CASHIER,)

class IsManager(HasRole):
    """Chỉ Quản lý (role=MANAGER) hoặc superuser — dùng cho khu vực/API chỉ
    dành riêng cho Admin, ví dụ báo cáo AI tổng quan vận hành (doanh thu, lỗi
    phổ biến, linh kiện dùng nhiều — mục 3.1.1.8 đề bài).

    `allowed_roles = ()` vì `HasRole.has_permission` đã tự cho phép
    MANAGER/superuser ở nhánh đầu tiên; không role nào khác được thêm vào
    đây, nên các role còn lại (kể cả Lễ tân, Thu ngân, Kỹ thuật viên) đều bị
    chặn — đúng nghĩa "riêng cho Admin".
    """

    allowed_roles = ()


class AnyStaffRoleReadOnly(BasePermission):
    """Mọi nhân viên (4 role) được XEM; chỉ Quản lý được SỬA.

    Dùng cho dữ liệu nhiều vai trò cần xem nhưng chỉ 1 vai trò được sửa — ví
    dụ: kho linh kiện (kỹ thuật viên cần xem tồn kho để báo khách, nhưng
    không được tự ý sửa giá/nhập kho).
    """

    staff_roles = (MANAGER, RECEPTIONIST, TECHNICIAN, CASHIER)

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated):
            return False
        role = getattr(user, "role", None)
        if request.method in SAFE_METHODS:
            return user.is_superuser or role in self.staff_roles
        return user.is_superuser or role == MANAGER