from django.db import migrations


def col_exists(schema_editor, table, col):
    """
    Helper: връща True ако колоната съществува в дадена sqlite таблица.
    """
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(f"PRAGMA table_info({table});")
        return col in [row[1] for row in cursor.fetchall()]


def forwards(apps, schema_editor):
    """
    Поправяме несъответствията между models.py и реалната база,
    без да трием нито един ред.
    """

    # ---------- CONTRACT.contract_name ----------
    if not col_exists(schema_editor, "portal_contract", "contract_name"):
        # добавяме колоната
        schema_editor.execute(
            "ALTER TABLE portal_contract ADD COLUMN contract_name varchar(255);"
        )

        # ако имаме старо поле title -> копираме към contract_name
        if col_exists(schema_editor, "portal_contract", "title"):
            schema_editor.execute("""
                UPDATE portal_contract
                SET contract_name = COALESCE(NULLIF(contract_name, ''), title)
                WHERE contract_name IS NULL OR contract_name = '';
            """)

        # като fallback – ако нещо още е NULL/празно
        schema_editor.execute("""
            UPDATE portal_contract
            SET contract_name = COALESCE(NULLIF(contract_name, ''), 'Contract #' || id)
            WHERE contract_name IS NULL OR contract_name = '';
        """)

    # ---------- INVOICE.vendor_id ----------
    if not col_exists(schema_editor, "portal_invoice", "vendor_id"):
        schema_editor.execute(
            "ALTER TABLE portal_invoice ADD COLUMN vendor_id integer;"
        )

        # Ако имаме contract_id и contract.vendor_id – попълваме
        if col_exists(schema_editor, "portal_invoice", "contract_id") and col_exists(
            schema_editor, "portal_contract", "vendor_id"
        ):
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


class Migration(migrations.Migration):
    dependencies = [
        ("portal", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
