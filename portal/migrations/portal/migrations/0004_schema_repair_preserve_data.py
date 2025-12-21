from django.db import migrations


def _column_exists(schema_editor, table_name: str, column_name: str) -> bool:
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(f"PRAGMA table_info({table_name});")
        cols = [row[1] for row in cursor.fetchall()]
    return column_name in cols


def forwards(apps, schema_editor):
    Vendor = apps.get_model("portal", "Vendor")
    Invoice = apps.get_model("portal", "Invoice")

    # -------------------------
    # CONTRACT: ensure contract_name exists and is populated
    # -------------------------
    if not _column_exists(schema_editor, "portal_contract", "contract_name"):
        schema_editor.execute("ALTER TABLE portal_contract ADD COLUMN contract_name varchar(255);")

    # ако имаш старо поле title в DB, копираме го към contract_name
    if _column_exists(schema_editor, "portal_contract", "title"):
        schema_editor.execute("""
            UPDATE portal_contract
            SET contract_name = COALESCE(NULLIF(contract_name,''), title)
            WHERE contract_name IS NULL OR contract_name = '';
        """)

    # ако пак има празни, даваме дефолт (за да не чупи UI)
    schema_editor.execute("""
        UPDATE portal_contract
        SET contract_name = COALESCE(NULLIF(contract_name,''), 'Contract #' || id)
        WHERE contract_name IS NULL OR contract_name = '';
    """)

    # -------------------------
    # INVOICE: ensure vendor_id exists and is populated
    # -------------------------
    if not _column_exists(schema_editor, "portal_invoice", "vendor_id"):
        schema_editor.execute("ALTER TABLE portal_invoice ADD COLUMN vendor_id integer;")

    # backfill vendor_id от contract.vendor_id (ако invoice има contract_id)
    if _column_exists(schema_editor, "portal_invoice", "contract_id") and _column_exists(schema_editor, "portal_contract", "vendor_id"):
        schema_editor.execute("""
            UPDATE portal_invoice
            SET vendor_id = (
                SELECT vendor_id
                FROM portal_contract
                WHERE portal_contract.id = portal_invoice.contract_id
            )
            WHERE (vendor_id IS NULL OR vendor_id = 0)
              AND contract_id IS NOT NULL;
        """)

    # останалите (без contract) ги връзваме към "Unknown / Unassigned"
    unknown, _ = Vendor.objects.get_or_create(
        name="Unknown / Unassigned",
        defaults={"vendor_type": "other"},
    )
    Invoice.objects.filter(vendor__isnull=True).update(vendor=unknown)


class Migration(migrations.Migration):
    dependencies = [
        ("portal", "0003_alter_contract_owner_invoice"),  # ако твоят последен е различен, смени го
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
