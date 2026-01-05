from django.contrib.auth import get_user_model

User = get_user_model()

def acting_access_context(request):
    """
    Provides consistent:
      - manageable_users: direct reports only (profile.manager = request.user)
      - is_acting / acting_user: based on session
    """
    if not request.user.is_authenticated:
        return {}

    manageable_users = (
        User.objects
        .filter(profile__manager=request.user)
        .order_by("username")
    )

    acting_user_id = request.session.get("provisioning_acting_user_id")
    acting_user = None
    is_acting = False

    if acting_user_id:
        acting_user = manageable_users.filter(id=acting_user_id).first()
        if acting_user:
            is_acting = True
        else:
            # session contains invalid/unauthorized id -> clear it
            request.session.pop("provisioning_acting_user_id", None)

    return {
        "manageable_users": manageable_users,
        "acting_user": acting_user,
        "is_acting": is_acting,
    }
