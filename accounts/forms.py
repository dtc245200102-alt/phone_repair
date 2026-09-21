"""Forms cho app `accounts`.

Cập nhật: `CustomerRegistrationForm.save()` giờ tự động liên kết tài khoản mới
với `repair.Customer` (theo số điện thoại):
- Nếu đã có `Customer` với đúng SĐT này (VD: lễ tân từng tạo hồ sơ cho khách
  vãng lai trước đó) -> gắn tài khoản mới vào hồ sơ đó luôn, không tạo bản ghi
  trùng.
- Nếu chưa có -> tạo mới 1 `Customer` gắn sẵn `user`.
Nhờ vậy khách tự đăng ký web sẽ thấy đúng lịch sử sửa chữa/bảo hành ngay từ
đầu, không cần đợi dò theo SĐT như cơ chế fallback ở `accounts/views.py`.

Lưu ý: chỉ tạo/gắn khi có `phone_number` (field này đang để trống được ở
model `CustomUser`) — không tạo `Customer` với SĐT rỗng vì `Customer.phone_number`
là `unique=True`, tạo 2 bản ghi rỗng sẽ vỡ ràng buộc unique.
"""

from django import forms
from django.contrib.auth.forms import UserCreationForm

from .models import CustomUser


class CustomerRegistrationForm(UserCreationForm):

    class Meta:
        model = CustomUser

        fields = (
            'username',
            'email',
            'phone_number'
        )

        widgets = {

            'username': forms.TextInput(
                attrs={
                    'class': 'form-control form-control-lg',
                    'placeholder': 'Tên đăng nhập',
                    'autocomplete': 'username',
                }
            ),

            'email': forms.EmailInput(
                attrs={
                    'class': 'form-control form-control-lg',
                    'placeholder': 'Email của bạn',
                    'autocomplete': 'email',
                }
            ),

            'phone_number': forms.TextInput(
                attrs={
                    'class': 'form-control form-control-lg',
                    'placeholder': 'Số điện thoại',
                    'autocomplete': 'tel',
                }
            ),
        }

    def __init__(self, *args, **kwargs):

        super().__init__(*args, **kwargs)

        self.fields['password1'].widget.attrs.update({
            'class': 'form-control form-control-lg',
            'placeholder': 'Mật khẩu',
            'autocomplete': 'new-password',
        })

        self.fields['password2'].widget.attrs.update({
            'class': 'form-control form-control-lg',
            'placeholder': 'Nhập lại mật khẩu',
            'autocomplete': 'new-password',
        })

    def save(self, commit=True):

        from repair.models import Customer

        user = super().save(commit=False)

        user.role = 'CUSTOMER'
        user.is_staff = False
        user.is_superuser = False

        if commit:

            user.save()

            if user.phone_number:

                customer, _ = Customer.objects.get_or_create(
                    phone_number=user.phone_number,
                    defaults={
                        "name":
                            user.get_full_name()
                            or user.username
                    },
                )

                if customer.user_id is None:

                    customer.user = user

                    customer.save(
                        update_fields=["user"]
                    )

        return user


class CustomerProfileForm(forms.ModelForm):

    class Meta:
        model = CustomUser
        fields = ('first_name', 'last_name', 'date_of_birth', 'avatar')
        labels = {
            'first_name': 'Tên',
            'last_name': 'Họ và tên đệm',
            'date_of_birth': 'Ngày sinh',
            'avatar': 'Ảnh đại diện',
        }
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nhập tên'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nhập họ và tên đệm'}),
            'date_of_birth': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'avatar': forms.ClearableFileInput(attrs={'class': 'form-control', 'accept': 'image/*'}),
        }