"""RBAC 权限判定测试。"""
import pytest
from backend.core.rbac import require_global, require_kb_role, require_kb_roles, ForbiddenError


class TestGlobalRole:

    def test_super_admin_passes_all(self):
        user = {"id": 1, "username": "admin", "role": "super_admin"}
        require_global(user, "user")
        require_global(user, "admin")
        require_global(user, "super_admin")

    def test_admin_blocked_by_super_admin(self):
        user = {"id": 2, "username": "a", "role": "admin"}
        with pytest.raises(ForbiddenError):
            require_global(user, "super_admin")

    def test_user_blocked_by_admin(self):
        user = {"id": 3, "username": "b", "role": "user"}
        with pytest.raises(ForbiddenError):
            require_global(user, "admin")

    def test_guest_blocked_by_user(self):
        user = {"id": 4, "username": "c", "role": "guest"}
        with pytest.raises(ForbiddenError):
            require_global(user, "user")


class TestKbRole:

    def test_super_admin_bypass(self, mocker):
        from backend.store import auth_store
        mocker.patch.object(auth_store, "get_kb_role", return_value=None)
        user = {"id": 1, "username": "admin", "role": "super_admin"}
        require_kb_role(user, 99, "owner")  # 不抛

    def test_owner_can_do_owner_things(self, mocker):
        from backend.store import auth_store
        mocker.patch.object(auth_store, "get_kb_role", return_value="owner")
        user = {"id": 2, "username": "bob", "role": "user"}
        require_kb_role(user, 1, "owner")
        require_kb_role(user, 1, "editor")
        require_kb_role(user, 1, "reader")

    def test_reader_cannot_edit(self, mocker):
        from backend.store import auth_store
        mocker.patch.object(auth_store, "get_kb_role", return_value="reader")
        user = {"id": 3, "username": "carol", "role": "user"}
        require_kb_role(user, 1, "reader")  # 不抛
        with pytest.raises(ForbiddenError):
            require_kb_role(user, 1, "editor")

    def test_non_member_rejected(self, mocker):
        from backend.store import auth_store
        mocker.patch.object(auth_store, "get_kb_role", return_value=None)
        user = {"id": 4, "username": "dave", "role": "user"}
        with pytest.raises(ForbiddenError):
            require_kb_role(user, 1, "reader")


class TestMultiKbRoles:

    def test_all_pass_super_admin(self):
        user = {"id": 1, "username": "admin", "role": "super_admin"}
        require_kb_roles(user, [1, 2, 3], "reader")  # 旁路

    def test_first_fail_throws(self, mocker):
        from backend.store import auth_store

        def _fake_role(kb_id, user_id):
            return "reader" if kb_id == 1 else None

        mocker.patch.object(auth_store, "get_kb_role", side_effect=_fake_role)
        user = {"id": 2, "username": "bob", "role": "user"}
        with pytest.raises(ForbiddenError):
            require_kb_roles(user, [1, 2], "reader")
