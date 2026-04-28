from .models import UserProfile


def current_profile(request):
    if not request.user.is_authenticated:
        return {"current_profile": None}
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    return {"current_profile": profile}
