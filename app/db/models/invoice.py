"""
模組名稱：app.db.models.invoice
功能說明：發票主檔與明細，以及 AI 風險分析結果。

==============================================================================
資料表：invoices（發票主檔）                                       狀態：草案
==============================================================================
欄位             型別            NULL  預設        說明
---------------  --------------  ----  ----------  ------------------------------
id               BIGINT          NO    IDENTITY    主鍵
user_id          BIGINT          NO                所屬使用者 → users.id
invoice_number   VARCHAR(10)     NO                發票號碼（2 碼英文＋8 碼數字，例：AB12345678）
invoice_date     DATE            NO                開立日期
invoice_term     VARCHAR(5)      NO                期別（民國年＋雙月的後月，例：11310）
seller_tax_id    VARCHAR(8)      YES               賣方統一編號
seller_name      VARCHAR(200)    YES               賣方名稱
buyer_tax_id     VARCHAR(8)      YES               買方統一編號（B2C 為 NULL）
total_amount     NUMERIC(12,2)   NO                總金額（含稅）
tax_amount       NUMERIC(12,2)   YES               稅額
source           VARCHAR(20)     NO                來源：upload / einvoice_sync / manual
status           VARCHAR(20)     NO    'pending'   狀態：pending / analyzing / passed / flagged / rejected
risk_score       SMALLINT        YES               AI 風險分數 0–100（越高越可疑）
ai_result        JSONB           YES               AI 分析結果（含判斷理由、模型版本）
file_key         VARCHAR(500)    YES               原始檔在物件儲存的路徑（不存檔案本體）
created_at       TIMESTAMPTZ     NO    now()       建立時間
updated_at       TIMESTAMPTZ     NO    now()       最後更新時間
deleted_at       TIMESTAMPTZ     YES               軟刪除時間（NULL＝未刪除）
------------------------------------------------------------------------------
主鍵：pk_invoices (id)
唯一：uq_invoices_user_id_invoice_number_invoice_date (user_id, invoice_number, invoice_date)
檢查：ck_invoices_source_valid       source IN (...)
      ck_invoices_status_valid       status IN (...)
      ck_invoices_risk_score_range   risk_score BETWEEN 0 AND 100
索引：ix_invoices_status (status)
      ix_invoices_invoice_date (invoice_date)
外鍵：fk_invoices_user_id_users  user_id → users.id  ON DELETE RESTRICT
關聯：users 1 ─ N invoices；invoices 1 ─ N invoice_items
------------------------------------------------------------------------------
異動紀錄（新到舊；上線後須附 migration revision）
2026-10-21  JerryChien  初版草案（尚未產生 migration）
==============================================================================

==============================================================================
資料表：invoice_items（發票明細）                                  狀態：草案
==============================================================================
欄位             型別            NULL  預設        說明
---------------  --------------  ----  ----------  ------------------------------
id               BIGINT          NO    IDENTITY    主鍵
invoice_id       BIGINT          NO                所屬發票 → invoices.id
line_no          SMALLINT        NO                明細序號（從 1 開始）
description      VARCHAR(500)    NO                品名
quantity         NUMERIC(12,3)   NO                數量
unit_price       NUMERIC(12,2)   NO                單價
amount           NUMERIC(12,2)   NO                小計
created_at       TIMESTAMPTZ     NO    now()       建立時間
updated_at       TIMESTAMPTZ     NO    now()       最後更新時間
------------------------------------------------------------------------------
主鍵：pk_invoice_items (id)
唯一：uq_invoice_items_invoice_id_line_no (invoice_id, line_no)
外鍵：fk_invoice_items_invoice_id_invoices  invoice_id → invoices.id  ON DELETE CASCADE
關聯：invoices 1 ─ N invoice_items
------------------------------------------------------------------------------
異動紀錄（新到舊；上線後須附 migration revision）
2026-10-21  JerryChien  初版草案（尚未產生 migration）
==============================================================================
"""

from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    ForeignKey,
    Numeric,
    SmallInteger,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, IdMixin, SoftDeleteMixin, TimestampMixin, in_values_check

if TYPE_CHECKING:
    from app.db.models.user import User


class InvoiceSource(StrEnum):
    """發票來源。"""

    UPLOAD = "upload"  # 使用者上傳圖檔 / PDF
    EINVOICE_SYNC = "einvoice_sync"  # 財政部電子發票平台同步
    MANUAL = "manual"  # 手動輸入


class InvoiceStatus(StrEnum):
    """發票狀態。前端 constants/invoice.js 的值必須與此一致。"""

    PENDING = "pending"  # 待分析
    ANALYZING = "analyzing"  # AI 分析中
    PASSED = "passed"  # 分析通過
    FLAGGED = "flagged"  # 有風險，待人工複核
    REJECTED = "rejected"  # 人工判定異常


class Invoice(IdMixin, TimestampMixin, SoftDeleteMixin, Base):
    """發票主檔。欄位定義見本檔開頭 Schema 備註。"""

    __tablename__ = "invoices"
    __table_args__ = (
        UniqueConstraint("user_id", "invoice_number", "invoice_date"),
        CheckConstraint(in_values_check("source", InvoiceSource), name="source_valid"),
        CheckConstraint(in_values_check("status", InvoiceStatus), name="status_valid"),
        CheckConstraint("risk_score BETWEEN 0 AND 100", name="risk_score_range"),
    )

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="RESTRICT"))
    invoice_number: Mapped[str] = mapped_column(String(10))
    invoice_date: Mapped[date] = mapped_column(Date, index=True)
    invoice_term: Mapped[str] = mapped_column(String(5))
    seller_tax_id: Mapped[str | None] = mapped_column(String(8))
    seller_name: Mapped[str | None] = mapped_column(String(200))
    buyer_tax_id: Mapped[str | None] = mapped_column(String(8))
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    tax_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    source: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(
        String(20), server_default=InvoiceStatus.PENDING.value, index=True
    )
    risk_score: Mapped[int | None] = mapped_column(SmallInteger)
    ai_result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    file_key: Mapped[str | None] = mapped_column(String(500))

    user: Mapped["User"] = relationship(back_populates="invoices")
    items: Mapped[list["InvoiceItem"]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan", order_by="InvoiceItem.line_no"
    )


class InvoiceItem(IdMixin, TimestampMixin, Base):
    """發票明細。欄位定義見本檔開頭 Schema 備註。"""

    __tablename__ = "invoice_items"
    __table_args__ = (UniqueConstraint("invoice_id", "line_no"),)

    invoice_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("invoices.id", ondelete="CASCADE")
    )
    line_no: Mapped[int] = mapped_column(SmallInteger)
    description: Mapped[str] = mapped_column(String(500))
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))

    invoice: Mapped["Invoice"] = relationship(back_populates="items")
