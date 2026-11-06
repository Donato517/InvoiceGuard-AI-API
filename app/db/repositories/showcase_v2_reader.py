"""模組名稱：app.db.repositories.showcase_v2_reader；功能說明：讀取 v2.0 OCR 範例與明細。"""

from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

HEADER_FIELDS = (
    "invoice_date",
    "buyer_name",
    "buyer_tax_id",
    "sales_amount",
    "tax_type",
    "tax_amount",
    "total_amount",
    "total_amount_zh",
    "seller_name",
    "seller_tax_id",
    "notes",
)
ITEM_FIELDS = {
    "item_name": "name",
    "quantity": "quantity",
    "unit_price": "unit_price",
    "line_amount": "amount",
}
STATES = {"candidate": "draft", "verified": "active", "revoked": "returned", "retired": "inactive"}

SELECT_EXAMPLE = """
    SELECT e.*, p.supplier_name,
      (p.is_active AND (e.expires_at IS NULL OR e.expires_at>now())) AS supplier_and_expiry_ok,
      COALESCE((SELECT jsonb_agg(jsonb_build_object(
        'line_no', i.line_no, 'item_name', i.item_name, 'quantity', CAST(i.quantity AS text),
        'unit_price', CAST(i.unit_price AS text), 'line_amount', CAST(i.line_amount AS text)
      ) ORDER BY i.line_no) FROM public.supplier_invoice_example_items i
        WHERE i.example_id=e.example_id), '[]'::jsonb) AS items
    FROM public.supplier_invoice_examples e
    JOIN public.suppliers p ON p.supplier_id=e.supplier_id
"""
VERIFIED = "e.status='verified' AND p.is_active AND (e.expires_at IS NULL OR e.expires_at>now())"


def revision(row: dict[str, Any], *, verified_only: bool = False) -> dict[str, Any]:
    """將資料庫欄位轉成頁面／Few-Shot 既有的欄位路徑。"""
    example_id, version = row["example_id"], row["example_version"]
    keys = set(row["verified_field_keys"])
    truths = []
    selected = []

    def field(path: str, value: Any, *columns: str) -> None:
        verified = all(column in keys for column in columns)
        if value is None or (verified_only and not verified):
            return
        truths.append({"path": path, "state": "readable", "text": str(value)})
        if verified:
            selected.append(path)

    for name in HEADER_FIELDS:
        if name == "seller_tax_id" and not verified_only and name not in keys:
            # 必填的主檔識別值不代表票面統編已被抄錄或驗證。
            continue
        field(name, row[name], name)
    if row["invoice_track"] and row["invoice_number"]:
        field(
            "invoice_number",
            row["invoice_track"] + row["invoice_number"],
            "invoice_track",
            "invoice_number",
        )
    for item in row.get("items", []):
        line = item["line_no"]
        for column, path in ITEM_FIELDS.items():
            field(f"items.{line}.{path}", item[column], f"items[{line - 1}].{column}")
    return {
        "id": str(uuid5(NAMESPACE_URL, f"showcase-v2:{example_id}:{version}")),
        "v2_example_version": version,
        "linked_source": any(
            row.get(key) for key in ("source_invoice_id", "source_file_id", "source_recognition_id")
        ),
        "expires_at": row["expires_at"].isoformat() if row.get("expires_at") else None,
        "document_group_id": str(row.get("source_invoice_id") or row.get("document_group_id") or "")
        or None,
        "source_file_id": str(row["source_file_id"]) if row.get("source_file_id") else None,
        "source_file_version": row.get("source_file_version"),
        "source_recognition_id": str(row["source_recognition_id"])
        if row.get("source_recognition_id")
        else None,
        "master_supplier_id": str(row["supplier_id"]),
        "title": row["example_name"],
        "supplier_name": row["supplier_name"],
        "tax_id": row["seller_tax_id"],
        "layout": row["template_key"] or "",
        "kind": "triplicate",
        "copy_type": "unknown",
        "status": STATES[row["status"]],
        "usable": row["status"] == "verified" and row.get("supplier_and_expiry_ok", True),
        "created_at": row["created_at"].isoformat(),
        "created_by": str(row["created_by"]),
        "confirmed_by": str(row["verified_by"]) if row["verified_by"] else None,
        "confirmed_at": row["verified_at"].isoformat() if row["verified_at"] else None,
        "truths": truths,
        "key_fields": selected,
        "reason": row["verification_note"],
        "source": {
            "bucket": row["bucket_name"],
            "key": row["storage_path"],
            "mime": row["mime_type"],
            "sha256": row["content_sha256"],
            "size": str(row["size_bytes"]),
            "filename": row["original_filename"],
        },
    }


def candidates(db: Session, tax_id: str, layout: str, supplier: str = "") -> list[dict[str, Any]]:
    """只選供應商有效、尚未到期的 v2.0 已驗證範例。"""
    rows = db.execute(
        text(f"""
        {SELECT_EXAMPLE} WHERE {VERIFIED} AND e.seller_tax_id=:tax
        AND (:supplier='' OR e.supplier_id=CAST(NULLIF(:supplier,'') AS uuid))
        AND (:layout='' OR strpos(lower(e.template_key),lower(:layout))>0)
        ORDER BY e.verified_at DESC,e.example_id LIMIT 30
        """),
        {"tax": tax_id, "layout": layout, "supplier": supplier},
    ).mappings()
    return [
        {"sample_id": row["example_id"], "revision": revision(dict(row), verified_only=True)}
        for row in rows
    ]


def get_example(
    db: Session, sample: UUID, *, verified_only: bool = False, lock: bool = False
) -> dict[str, Any] | None:
    """依固定範例識別碼讀取目前版本。"""
    sql = f"{SELECT_EXAMPLE} WHERE e.example_id=:id"
    if verified_only:
        sql += f" AND {VERIFIED}"
    if lock:
        sql += " FOR UPDATE OF e"
    row = db.execute(text(sql), {"id": sample}).mappings().one_or_none()
    return revision(dict(row), verified_only=verified_only) if row is not None else None


def supplier_examples(db: Session, supplier: UUID, page: int) -> list[dict[str, Any]]:
    """依正式供應商 UUID 取目前版本，不讀歷史資料表。"""
    rows = db.execute(
        text(f"""
        {SELECT_EXAMPLE} WHERE e.supplier_id=:supplier
        ORDER BY lower(e.example_name),e.example_name,e.example_id LIMIT 20 OFFSET :offset
        """),
        {"supplier": supplier, "offset": (page - 1) * 20},
    ).mappings()
    return [
        {
            "id": row["example_id"],
            "payload": {"title": row["example_name"], "revisions": [revision(dict(row))]},
        }
        for row in rows
    ]


def supplier_example_counts(db: Session, suppliers: list[UUID]) -> dict[UUID, int]:
    """以單次查詢取得本頁供應商的獨立範例張數，不把歷史版本重複計入。"""
    if not suppliers:
        return {}
    rows = db.execute(
        text(
            "SELECT supplier_id, count(*) AS total FROM public.supplier_invoice_examples "
            "WHERE supplier_id IN :ids GROUP BY supplier_id"
        ).bindparams(bindparam("ids", expanding=True)),
        {"ids": suppliers},
    ).mappings()
    return {row["supplier_id"]: row["total"] for row in rows}
