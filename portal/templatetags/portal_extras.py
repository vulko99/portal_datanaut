from django import template

register = template.Library()


@register.filter
def get_item(obj, key):
    """
    Позволява {{ row|get_item:col.key }} в темплейта.
    Работи и за dict, и за обекти с атрибути.
    """
    if obj is None or key is None:
        return ""

    # dict / mapping
    if hasattr(obj, "get"):
        try:
            return obj.get(key, "")
        except Exception:
            pass

    # fallback – атрибут
    try:
        return getattr(obj, key, "")
    except Exception:
        return ""


@register.filter(name="report_value")
def report_value(obj, key):
    """
    Alias за get_item, ползва се в reports.html:
      {{ row|report_value:col.key }}
    """
    return get_item(obj, key)

@register.filter
def is_portal_admin(user):
    # твоята логика – пример:
    return user.is_superuser or user.is_staff