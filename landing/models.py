# landing/models.py
from django.db import models


class ContactRequest(models.Model):
    PERSONA_TRADING = "trading"
    PERSONA_CFO = "cfo"
    PERSONA_INVESTOR = "investor"
    PERSONA_OTHER = "other"

    PERSONA_CHOICES = [
        (PERSONA_TRADING, "Trading / dealing desks"),
        (PERSONA_CFO, "CFO / finance"),
        (PERSONA_INVESTOR, "Investor / board"),
        (PERSONA_OTHER, "Other / not specified"),
    ]

    STATUS_NEW = "new"
    STATUS_CONTACTED = "contacted"
    STATUS_QUALIFIED = "qualified"
    STATUS_CLOSED = "closed"

    STATUS_CHOICES = [
        (STATUS_NEW, "New"),
        (STATUS_CONTACTED, "Contacted"),
        (STATUS_QUALIFIED, "Qualified"),
        (STATUS_CLOSED, "Closed / not a fit"),
    ]

    name = models.CharField(max_length=200, blank=True)
    company = models.CharField(max_length=200, blank=True)
    role = models.CharField(max_length=200, blank=True)
    email = models.EmailField(blank=True)
    message = models.TextField(blank=True)

    source = models.CharField(
        max_length=100,
        blank=True,
        help_text="Where the lead came from (e.g. website, referral, conference).",
    )

    persona = models.CharField(
        max_length=20,
        choices=PERSONA_CHOICES,
        blank=True,
        help_text="Primary persona this request belongs to.",
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_NEW,
        help_text="Internal status in your follow-up pipeline.",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        base = self.name or "(no name)"
        if self.company:
            return f"{base} – {self.company}"
        return base
