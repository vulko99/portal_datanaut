from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()


class Vendor(models.Model):
    name = models.CharField(max_length=255)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Contract(models.Model):
    owner = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="contracts",
        null=True,          # позволяваме null за вече съществуващите записи
        blank=True,
    )

    vendor = models.ForeignKey(
        Vendor,
        on_delete=models.PROTECT,
        related_name="contracts",
    )
    title = models.CharField(max_length=255)
    entity = models.CharField(
        max_length=255,
        blank=True,
        help_text="Legal entity / desk / cost centre",
    )
    annual_value = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
    )
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    renewal_date = models.DateField(null=True, blank=True)

    # Каченият файл – тук ще са PDF/DOCX и т.н.
    file = models.FileField(
        upload_to="contracts/",
        help_text="Signed contract document",
    )

    uploaded_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="uploaded_contracts",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.title
