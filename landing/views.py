from django.conf import settings
from django.core.mail import send_mail
from django.shortcuts import render


def home(request):
    return render(request, "landing/home.html")


def demo(request):
    return render(request, "landing/demo.html")


def pricing(request):
    return render(request, "landing/pricing.html")


def about(request):
    return render(request, "landing/about.html")


def contact(request):
    """
    Прост контакт / request demo – праща имейл и показва success съобщение.
    """
    success = False

    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        company = request.POST.get("company", "").strip()
        role = request.POST.get("role", "").strip()
        email = request.POST.get("email", "").strip()
        message = request.POST.get("message", "").strip()

        if name and company and email:
            subject = f"[DataNaut demo] {name} – {company}"
            body = (
                f"Name: {name}\n"
                f"Company: {company}\n"
                f"Role: {role}\n"
                f"Email: {email}\n\n"
                f"Message:\n{message}"
            )

            send_mail(
                subject,
                body,
                getattr(settings, "DEFAULT_FROM_EMAIL", "no-reply@datanaut.local"),
                [getattr(settings, "CONTACT_NOTIFY_EMAIL", "your.email@example.com")],
                fail_silently=True,
            )
            success = True

    return render(request, "landing/contact.html", {"success": success})


# ---------- PERSONA ПАНЕЛИ ----------

def for_trading_desks(request):
    return render(request, "landing/for_trading_desks.html")


def for_cfo(request):
    return render(request, "landing/for_cfo.html")


def for_investors(request):
    return render(request, "landing/for_investors.html")

def how_it_works(request):
    return render(request, "landing/how_it_works.html")

