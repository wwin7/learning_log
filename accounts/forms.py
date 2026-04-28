from django import forms
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.models import User

from .models import UserProfile


class UserProfileForm(forms.ModelForm):
    username = forms.CharField(max_length=150, label="用户名")

    class Meta:
        model = UserProfile
        fields = ["avatar", "weekly_target", "signature"]
        labels = {
            "avatar": "头像",
            "weekly_target": "每周目标笔记数",
            "signature": "个性签名",
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        self.user = user
        self.fields["signature"].widget.attrs.update(
            {"placeholder": "一句简短签名（最多56字）", "maxlength": 56}
        )
        if user:
            self.fields["username"].initial = user.username

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        if User.objects.exclude(pk=self.user.pk).filter(username=username).exists():
            raise forms.ValidationError("该用户名已被占用")
        return username

    def save(self, commit=True):
        profile = super().save(commit=False)
        self.user.username = self.cleaned_data["username"]
        if commit:
            self.user.save(update_fields=["username"])
            profile.user = self.user
            profile.save()
        return profile


class PasswordForm(PasswordChangeForm):
    old_password = forms.CharField(label="当前密码", widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}))
    new_password1 = forms.CharField(label="新密码", widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))
    new_password2 = forms.CharField(label="确认新密码", widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))
