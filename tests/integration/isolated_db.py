"""
隔離 PostgreSQL 整合測試的輔助類別：一個合成部門與使用者，結束時清除其提交的發票與辨識紀錄。
僅供 tests/integration 使用；連線限制在 conftest 的 engine fixture。
"""

from uuid import UUID, uuid4

from sqlalchemy import Engine, text

PASSWORD_HASH = "$argon2id$v=19$m=65536,t=3,p=4$" + "A" * 22 + "$" + "B" * 22


class World:
    """一個合成部門與使用者；結束時清除該使用者提交的發票與辨識紀錄。"""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        tag = uuid4().hex[:8]
        with engine.begin() as conn:
            self.department_id: UUID = conn.execute(
                text(
                    "INSERT INTO public.departments(department_code, department_name)"
                    " VALUES (:c, 'W15 測試部') RETURNING department_id"
                ),
                {"c": f"w15_{tag}"},
            ).scalar_one()
            self.department_code = f"w15_{tag}"
            self.user_id: UUID = conn.execute(
                text(
                    "INSERT INTO invoiceguard_identity.user_accounts"
                    "(email, password_hash, account_status, primary_department_id)"
                    " VALUES (:e, :h, 'active', :d) RETURNING user_id"
                ),
                {"e": f"w15_{tag}@example.test", "h": PASSWORD_HASH, "d": self.department_id},
            ).scalar_one()
            conn.execute(
                text("INSERT INTO public.user_profiles(user_id, display_name) VALUES (:u, 'W15')"),
                {"u": self.user_id},
            )
            conn.execute(
                text("INSERT INTO public.user_departments(user_id, department_id) VALUES (:u, :d)"),
                {"u": self.user_id, "d": self.department_id},
            )
        self.email = f"w15_{tag}@example.test"

    def cleanup(self) -> None:
        with self.engine.begin() as conn:
            ids = [
                row[0]
                for row in conn.execute(
                    text("SELECT invoice_id FROM public.invoices WHERE submitted_by = :u"),
                    {"u": self.user_id},
                )
            ]
            conn.execute(
                text("DELETE FROM public.invoice_field_reviews WHERE invoice_id = ANY(:i)"),
                {"i": ids},
            )
            conn.execute(
                text("DELETE FROM public.invoice_changes WHERE invoice_id = ANY(:i)"), {"i": ids}
            )
            conn.execute(
                text("DELETE FROM public.ai_recognition_logs WHERE requested_by = :u"),
                {"u": self.user_id},
            )
            conn.execute(text("DELETE FROM public.invoices WHERE invoice_id = ANY(:i)"), {"i": ids})
            conn.execute(
                text("DELETE FROM invoiceguard_identity.user_accounts WHERE user_id = :u"),
                {"u": self.user_id},
            )
            conn.execute(
                text("DELETE FROM public.departments WHERE department_id = :d"),
                {"d": self.department_id},
            )
