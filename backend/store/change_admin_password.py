"""CLI 改管理员密码 —— 直接操作数据库的离线工具。

用法:
  set NEW_ADMIN_PW=YourNewPass123 && python -m backend.store.change_admin_password

环境变量:
  ADMIN_USER     要改密的用户名 (默认 "admin")
  NEW_ADMIN_PW   新密码（必填，至少8位，含大写字母+数字）
"""
import os, sys

_ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
_NEW_PW = os.environ.get("NEW_ADMIN_PW", "")


def main():
    if not _NEW_PW:
        sys.exit(
            "用法: set NEW_ADMIN_PW=<新密码> && python -m backend.store.change_admin_password\n"
        )

    from backend.core import auth
    from backend.store import auth_store

    err = auth.validate_password(_NEW_PW)
    if err:
        sys.exit(f"密码不符合要求: {err}")

    user = auth_store.get_user_with_hash(_ADMIN_USER) if _ADMIN_USER else None
    if user is None:
        sys.exit(f"用户不存在: {_ADMIN_USER}")

    # 检查新旧密码相同
    if auth.verify_pw(_NEW_PW, user["password_hash"]):
        sys.exit("新密码不能与旧密码相同")

    new_hash = auth.hash_pw(_NEW_PW)
    ok = auth_store.update_password(user["id"], new_hash)
    if not ok:
        sys.exit(f"更新密码失败: {_ADMIN_USER}")

    new_tv = auth_store.bump_token_version(user["id"])
    auth_store.write_audit(
        action="cli_change_password",
        user_id=user["id"], username=_ADMIN_USER,
        target="password_reset_via_cli",
    )
    print(f"[OK] {_ADMIN_USER} (id={user['id']}) 密码已更新, token_version={new_tv}")
    print("    所有已有会话已失效，需用新密码重新登录。")


if __name__ == "__main__":
    main()
