from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth import login, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm

from .forms import PasswordForm, UserProfileForm
from .models import UserProfile

def register(request):
    """Register a new user."""
    if request.method != 'POST':
        # Display blank registration form.
        form = UserCreationForm()
    else:
        # Process completed form.
        form = UserCreationForm(data=request.POST)
        if form.is_valid():
            new_user = form.save()
            # Log the user in and then redirect to home page.
            login(request, new_user)
            messages.success(request, '注册成功，欢迎加入学习日志系统。')
            return redirect('learning_logs:index')
    
    # Display a blank or invalid form.
    context = {'form': form}
    return render(request, 'registration/register.html', context)


@login_required
def settings_view(request):
    profile, _ = UserProfile.objects.get_or_create(user=request.user)

    if request.method == "POST":
        form_type = request.POST.get("form_type")
        if form_type == "profile":
            profile_form = UserProfileForm(request.POST, request.FILES, instance=profile, user=request.user)
            password_form = PasswordForm(request.user)
            if profile_form.is_valid():
                profile_form.save()
                messages.success(request, "个人信息已更新。")
                return redirect("accounts:settings")
        elif form_type == "password":
            profile_form = UserProfileForm(instance=profile, user=request.user)
            password_form = PasswordForm(request.user, request.POST)
            if password_form.is_valid():
                user = password_form.save()
                update_session_auth_hash(request, user)
                messages.success(request, "密码修改成功。")
                return redirect("accounts:settings")
        else:
            profile_form = UserProfileForm(instance=profile, user=request.user)
            password_form = PasswordForm(request.user)
    else:
        profile_form = UserProfileForm(instance=profile, user=request.user)
        password_form = PasswordForm(request.user)

    context = {
        "profile_form": profile_form,
        "password_form": password_form,
        "profile": profile,
    }
    return render(request, "accounts/settings.html", context)
