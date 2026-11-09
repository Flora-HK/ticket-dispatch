"""保护 AuditLog 不可变

Revision ID: e7a3c9d15b42
Revises: c4e8a1f62d90
Create Date: 2026-11-09 11:00:00.000000

DM4 使用行级 Trigger 拒绝 AuditLog 的 UPDATE 和 DELETE。
测试清理依赖 TRUNCATE，Trigger 不拦截 TRUNCATE，因此不会破坏 app_test 夹具。
"""

from alembic import op

# 以下 revision 标识由 Alembic 使用，不能被后续迁移修改。
revision = "e7a3c9d15b42"
down_revision = "c4e8a1f62d90"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 函数统一拒绝审计行的修改与删除；55000 表示对象状态不允许该操作。
    op.execute(
        """
        CREATE FUNCTION public.prevent_audit_log_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION
                'audit_log is append-only; UPDATE and DELETE are forbidden'
                USING ERRCODE = '55000';
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_log_append_only
        BEFORE UPDATE OR DELETE ON public.audit_log
        FOR EACH ROW
        EXECUTE FUNCTION public.prevent_audit_log_mutation();
        """
    )


def downgrade() -> None:
    # 先移除 Trigger，再删除仅由该 Trigger 使用的函数。
    op.execute(
        "DROP TRIGGER IF EXISTS audit_log_append_only ON public.audit_log;"
    )
    op.execute("DROP FUNCTION IF EXISTS public.prevent_audit_log_mutation();")
