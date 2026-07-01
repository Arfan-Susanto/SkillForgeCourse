from django import forms
from django.db.models import Q

from accounts.models import User
from enrollments.models import InstructorWithdraw

from .models import Course, CourseDiscussion, CourseReview


class CourseForm(forms.ModelForm):
    class Meta:
        model = Course
        fields = ["title", "description", "price", "youtube_url", "thumbnail", "instructor"]
        widgets = {
            "title": forms.TextInput(attrs={"class": "mt-1 w-full rounded-xl border border-slate-200 bg-white px-4 py-3 text-slate-900 shadow-sm outline-none transition placeholder:text-slate-400 focus:border-brand-500 focus:ring-4 focus:ring-brand-100", "placeholder": "Judul kursus"}),
            "description": forms.Textarea(attrs={"rows": 6, "class": "mt-1 w-full rounded-xl border border-slate-200 bg-white px-4 py-3 text-slate-900 shadow-sm outline-none transition placeholder:text-slate-400 focus:border-brand-500 focus:ring-4 focus:ring-brand-100", "placeholder": "Jelaskan isi, manfaat, dan target peserta kursus"}),
            "price": forms.NumberInput(attrs={"min": "0", "step": "0.01", "class": "mt-1 w-full rounded-xl border border-slate-200 bg-white px-4 py-3 text-slate-900 shadow-sm outline-none transition placeholder:text-slate-400 focus:border-brand-500 focus:ring-4 focus:ring-brand-100", "placeholder": "0"}),
            "youtube_url": forms.URLInput(attrs={"class": "mt-1 w-full rounded-xl border border-slate-200 bg-white px-4 py-3 text-slate-900 shadow-sm outline-none transition placeholder:text-slate-400 focus:border-brand-500 focus:ring-4 focus:ring-brand-100", "placeholder": "https://www.youtube.com/watch?v=..."}),
            "thumbnail": forms.ClearableFileInput(attrs={"class": "mt-1 block w-full cursor-pointer rounded-xl border border-dashed border-slate-300 bg-slate-50 px-4 py-3 text-sm text-slate-700 file:mr-4 file:rounded-lg file:border-0 file:bg-slate-900 file:px-4 file:py-2 file:text-sm file:font-semibold file:text-white hover:border-brand-400 hover:bg-brand-50"}),
            "instructor": forms.Select(attrs={"class": "mt-1 w-full rounded-xl border border-slate-200 bg-white px-4 py-3 text-slate-900 shadow-sm outline-none transition focus:border-brand-500 focus:ring-4 focus:ring-brand-100"}),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)

        instructor_queryset = User.objects.filter(Q(role=User.ROLE_INSTRUCTOR) | Q(is_staff=True) | Q(is_superuser=True))
        if user is not None and not user.is_staff and not user.is_superuser:
            instructor_queryset = instructor_queryset.filter(pk=user.pk)

        self.fields["instructor"].queryset = instructor_queryset.order_by("username")
        for field in self.fields.values():
            base = field.widget.attrs.get("class", "")
            if isinstance(field.widget, (forms.TextInput, forms.URLInput, forms.Textarea, forms.Select)):
                field.widget.attrs["class"] = base


class CourseDiscussionForm(forms.ModelForm):
    class Meta:
        model = CourseDiscussion
        fields = ["message"]
        widgets = {
            "message": forms.Textarea(
                attrs={
                    "rows": 4,
                    "class": "w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-slate-900 shadow-sm outline-none transition placeholder:text-slate-400 focus:border-brand-500 focus:ring-4 focus:ring-brand-100",
                    "placeholder": "Tanyakan atau diskusikan sesuatu tentang course ini...",
                }
            )
        }


class CourseReviewForm(forms.ModelForm):
    class Meta:
        model = CourseReview
        fields = ["rating", "comment"]
        widgets = {
            "rating": forms.Select(
                attrs={
                    "class": "w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-slate-900 shadow-sm outline-none transition focus:border-brand-500 focus:ring-4 focus:ring-brand-100",
                }
            ),
            "comment": forms.Textarea(
                attrs={
                    "rows": 4,
                    "class": "mt-3 w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-slate-900 shadow-sm outline-none transition placeholder:text-slate-400 focus:border-brand-500 focus:ring-4 focus:ring-brand-100",
                    "placeholder": "Berikan pendapatmu tentang course ini...",
                }
            ),
        }


class InstructorWithdrawForm(forms.ModelForm):
    class Meta:
        model = InstructorWithdraw
        fields = ["amount", "bank_name", "account_name", "account_number", "note"]
        widgets = {
            "amount": forms.NumberInput(
                attrs={
                    "min": "0",
                    "step": "0.01",
                    "class": "mt-1 w-full rounded-xl border border-slate-200 bg-white px-4 py-3 text-slate-900 shadow-sm outline-none transition placeholder:text-slate-400 focus:border-brand-500 focus:ring-4 focus:ring-brand-100",
                    "placeholder": "0",
                }
            ),
            "bank_name": forms.TextInput(
                attrs={
                    "class": "mt-1 w-full rounded-xl border border-slate-200 bg-white px-4 py-3 text-slate-900 shadow-sm outline-none transition placeholder:text-slate-400 focus:border-brand-500 focus:ring-4 focus:ring-brand-100",
                    "placeholder": "BCA / BRI / Mandiri",
                }
            ),
            "account_name": forms.TextInput(
                attrs={
                    "class": "mt-1 w-full rounded-xl border border-slate-200 bg-white px-4 py-3 text-slate-900 shadow-sm outline-none transition placeholder:text-slate-400 focus:border-brand-500 focus:ring-4 focus:ring-brand-100",
                    "placeholder": "Nama pemilik rekening",
                }
            ),
            "account_number": forms.TextInput(
                attrs={
                    "class": "mt-1 w-full rounded-xl border border-slate-200 bg-white px-4 py-3 text-slate-900 shadow-sm outline-none transition placeholder:text-slate-400 focus:border-brand-500 focus:ring-4 focus:ring-brand-100",
                    "placeholder": "Nomor rekening",
                }
            ),
            "note": forms.Textarea(
                attrs={
                    "rows": 4,
                    "class": "mt-1 w-full rounded-xl border border-slate-200 bg-white px-4 py-3 text-slate-900 shadow-sm outline-none transition placeholder:text-slate-400 focus:border-brand-500 focus:ring-4 focus:ring-brand-100",
                    "placeholder": "Catatan opsional untuk admin",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        self.available_balance = kwargs.pop("available_balance", None)
        super().__init__(*args, **kwargs)

    def clean_amount(self):
        amount = self.cleaned_data["amount"]
        if amount <= 0:
            raise forms.ValidationError("Jumlah withdraw harus lebih besar dari 0.")
        if self.available_balance is not None and amount > self.available_balance:
            raise forms.ValidationError(
                "Jumlah withdraw melebihi saldo yang tersedia.",
                code="exceeds_balance",
            )
        return amount

