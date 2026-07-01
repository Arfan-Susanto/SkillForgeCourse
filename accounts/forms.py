from django import forms
from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.forms import UserCreationForm
from django.core.files.uploadedfile import UploadedFile

from .models import InstructorApplication, User


class RegisterForm(UserCreationForm):
    email = forms.EmailField(required=True)

    class Meta:
        model = User
        fields = ("username", "email", "password1", "password2")

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("A user with that email already exists.")
        return email


class EmailLoginForm(forms.Form):
    email = forms.EmailField()
    password = forms.CharField(widget=forms.PasswordInput)

    def __init__(self, request=None, *args, **kwargs):
        self.request = request
        self.user = None
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned_data = super().clean()
        email = cleaned_data.get("email")
        password = cleaned_data.get("password")

        if email and password:
            self.user = authenticate(request=self.request, email=email, password=password)
            if self.user is None:
                raise forms.ValidationError("Invalid email or password.")

        return cleaned_data

    def get_user(self):
        return self.user


class ForgotPasswordRequestForm(forms.Form):
    email = forms.EmailField()


class OTPVerificationForm(forms.Form):
    otp = forms.CharField(min_length=6, max_length=6)


class ResetPasswordForm(forms.Form):
    new_password = forms.CharField(widget=forms.PasswordInput)
    confirm_password = forms.CharField(widget=forms.PasswordInput)

    def clean_new_password(self):
        password = self.cleaned_data["new_password"]
        validate_password(password)
        return password

    def clean(self):
        cleaned_data = super().clean()
        new_password = cleaned_data.get("new_password")
        confirm_password = cleaned_data.get("confirm_password")
        if new_password and confirm_password and new_password != confirm_password:
            raise forms.ValidationError("Password confirmation does not match.")
        return cleaned_data


class EditProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ("username", "email", "bio", "profile_image")
        widgets = {
            "bio": forms.TextInput(attrs={"maxlength": "100", "class": "mt-1 w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-slate-900 shadow-sm outline-none transition focus:border-brand-500 focus:ring-4 focus:ring-brand-100", "placeholder": "Ringkasan singkat tentang diri Anda (maks 100 karakter)"}),
        }
    
    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        # Allow current user's email
        if User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("A user with that email already exists.")
        return email

    def clean_bio(self):
        bio = self.cleaned_data.get("bio", "").strip()
        if len(bio) > 100:
            raise forms.ValidationError("Bio maksimal 100 karakter.")
        return bio

    def clean_profile_image(self):
        image = self.cleaned_data.get("profile_image")
        if not image:
            return image

        # Only validate brand-new uploads. Existing stored files come back as FieldFile
        # objects when the form is bound to the instance and should not be revalidated here.
        if not isinstance(image, UploadedFile):
            return image

        max_size = 1024 * 1024  # 1MB
        if image.size > max_size:
            raise forms.ValidationError("Ukuran gambar maksimal 1MB.")

        allowed_types = {"image/jpeg", "image/png", "image/webp", "image/gif"}
        if getattr(image, "content_type", "") not in allowed_types:
            raise forms.ValidationError("Format gambar harus JPG, PNG, WEBP, atau GIF.")

        return image


class ChangePasswordForm(forms.Form):
    current_password = forms.CharField(widget=forms.PasswordInput, label="Password Sekarang")
    new_password = forms.CharField(widget=forms.PasswordInput, label="Password Baru")
    confirm_password = forms.CharField(widget=forms.PasswordInput, label="Konfirmasi Password")

    def clean_new_password(self):
        password = self.cleaned_data["new_password"]
        validate_password(password)
        return password

    def clean(self):
        cleaned_data = super().clean()
        new_password = cleaned_data.get("new_password")
        confirm_password = cleaned_data.get("confirm_password")
        if new_password and confirm_password and new_password != confirm_password:
            raise forms.ValidationError("Konfirmasi password tidak sesuai.")
        return cleaned_data


class InstructorApplicationForm(forms.ModelForm):
    class Meta:
        model = InstructorApplication
        fields = ("full_name", "headline", "bio", "portfolio_url", "experience_years", "motivation")
        widgets = {
            "full_name": forms.TextInput(attrs={"class": "mt-1 w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-slate-900 shadow-sm outline-none transition focus:border-brand-500 focus:ring-4 focus:ring-brand-100", "placeholder": "Nama lengkap"}),
            "headline": forms.TextInput(attrs={"class": "mt-1 w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-slate-900 shadow-sm outline-none transition focus:border-brand-500 focus:ring-4 focus:ring-brand-100", "placeholder": "Contoh: Web development instructor"}),
            "bio": forms.Textarea(attrs={"rows": 5, "class": "mt-1 w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-slate-900 shadow-sm outline-none transition focus:border-brand-500 focus:ring-4 focus:ring-brand-100", "placeholder": "Ceritakan pengalaman mengajar dan keahlian Anda"}),
            "portfolio_url": forms.URLInput(attrs={"class": "mt-1 w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-slate-900 shadow-sm outline-none transition focus:border-brand-500 focus:ring-4 focus:ring-brand-100", "placeholder": "https://..."}),
            "experience_years": forms.NumberInput(attrs={"min": "0", "class": "mt-1 w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-slate-900 shadow-sm outline-none transition focus:border-brand-500 focus:ring-4 focus:ring-brand-100", "placeholder": "0"}),
            "motivation": forms.Textarea(attrs={"rows": 5, "class": "mt-1 w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-slate-900 shadow-sm outline-none transition focus:border-brand-500 focus:ring-4 focus:ring-brand-100", "placeholder": "Kenapa Anda ingin menjadi instructor?"}),
        }

    def clean_portfolio_url(self):
        value = self.cleaned_data.get("portfolio_url", "").strip()
        return value
