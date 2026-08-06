"""认证 API 集成测试。"""
import pytest
from fastapi.testclient import TestClient


class TestAuthAPI:

    @pytest.fixture
    def client(self, db_session):
        """创建 TestClient。先在 DB 中创建 whitelist 条目。"""
        from backend.store.auth_models import Whitelist
        s = db_session
        s.add(Whitelist(username="newuser", note="test"))
        s.add(Whitelist(username="loginuser", note="test"))
        s.add(Whitelist(username="badpwuser", note="test"))
        s.commit()

        from backend.main import app
        return TestClient(app)

    def test_register_valid(self, client):
        resp = client.post("/api/auth/register", json={
            "username": "newuser", "password": "NewUser123",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0

    def test_register_weak_password(self, client):
        resp = client.post("/api/auth/register", json={
            "username": "weakuser", "password": "short",
        })
        data = resp.json()
        assert data["code"] != 0

    def test_login_success(self, client):
        client.post("/api/auth/register", json={
            "username": "loginuser", "password": "LoginUser123",
        })
        resp = client.post("/api/auth/login", json={
            "username": "loginuser", "password": "LoginUser123",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert "access_token" in data["data"]

    def test_login_wrong_password(self, client):
        client.post("/api/auth/register", json={
            "username": "badpwuser", "password": "BadPwUser123",
        })
        resp = client.post("/api/auth/login", json={
            "username": "badpwuser", "password": "WrongPassword1",
        })
        data = resp.json()
        assert data["code"] == 401

    def test_protected_route_no_token(self, client):
        resp = client.get("/api/kb")
        assert resp.status_code == 401


class TestLogout:

    @pytest.fixture
    def client(self, db_session):
        from backend.store.auth_models import Whitelist
        s = db_session
        s.add(Whitelist(username="logoutuser", note="test"))
        s.commit()

        from backend.main import app
        return TestClient(app)

    def test_logout_endpoint(self, client):
        """POST /api/auth/logout 应返回成功。"""
        client.post("/api/auth/register", json={
            "username": "logoutuser", "password": "LogoutUser123",
        })
        login_resp = client.post("/api/auth/login", json={
            "username": "logoutuser", "password": "LogoutUser123",
        })
        token = login_resp.json()["data"]["access_token"]

        resp = client.post("/api/auth/logout", headers={
            "Authorization": f"Bearer {token}",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert data["data"]["msg"] == "已登出"

    def test_token_rejected_after_logout(self, client):
        """登出后旧 token 应被拒绝（tv 不匹配 → 401）。"""
        client.post("/api/auth/register", json={
            "username": "logoutuser", "password": "LogoutUser123",
        })
        login_resp = client.post("/api/auth/login", json={
            "username": "logoutuser", "password": "LogoutUser123",
        })
        token = login_resp.json()["data"]["access_token"]

        # 登出
        client.post("/api/auth/logout", headers={
            "Authorization": f"Bearer {token}",
        })

        # 用旧 token 访问受保护接口 → 应被拒绝
        resp = client.get("/api/auth/me", headers={
            "Authorization": f"Bearer {token}",
        })
        assert resp.status_code == 401

    def test_new_token_works_after_logout(self, client):
        """登出后重新登录获得的 token 应正常工作。"""
        client.post("/api/auth/register", json={
            "username": "logoutuser", "password": "LogoutUser123",
        })
        login1 = client.post("/api/auth/login", json={
            "username": "logoutuser", "password": "LogoutUser123",
        })
        token1 = login1.json()["data"]["access_token"]

        client.post("/api/auth/logout", headers={
            "Authorization": f"Bearer {token1}",
        })

        # 重新登录
        login2 = client.post("/api/auth/login", json={
            "username": "logoutuser", "password": "LogoutUser123",
        })
        token2 = login2.json()["data"]["access_token"]

        # 新 token 应能正常使用
        resp = client.get("/api/auth/me", headers={
            "Authorization": f"Bearer {token2}",
        })
        assert resp.status_code == 200
        assert resp.json()["data"]["username"] == "logoutuser"


class TestPasswordChangeInvalidatesToken:

    @pytest.fixture
    def client(self, db_session):
        from backend.store.auth_models import Whitelist
        s = db_session
        s.add(Whitelist(username="pwduser", note="test"))
        s.commit()

        from backend.main import app
        return TestClient(app)

    def test_token_rejected_after_password_change(self, client):
        """改密后旧 token 应被拒绝。"""
        client.post("/api/auth/register", json={
            "username": "pwduser", "password": "OldPwd123",
        })
        login_resp = client.post("/api/auth/login", json={
            "username": "pwduser", "password": "OldPwd123",
        })
        token = login_resp.json()["data"]["access_token"]

        # 改密
        resp = client.put("/api/account/password", json={
            "old_password": "OldPwd123",
            "new_password": "NewPwd456",
        }, headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        assert resp.json()["code"] == 0

        # 旧 token 被拒绝
        resp = client.get("/api/auth/me", headers={
            "Authorization": f"Bearer {token}",
        })
        assert resp.status_code == 401

    def test_relogin_works_after_password_change(self, client):
        """改密后用新密码登录应成功。"""
        client.post("/api/auth/register", json={
            "username": "pwduser", "password": "OldPwd123",
        })
        login1 = client.post("/api/auth/login", json={
            "username": "pwduser", "password": "OldPwd123",
        })
        token1 = login1.json()["data"]["access_token"]

        client.put("/api/account/password", json={
            "old_password": "OldPwd123",
            "new_password": "NewPwd456",
        }, headers={"Authorization": f"Bearer {token1}"})

        # 旧密码无法登录
        resp = client.post("/api/auth/login", json={
            "username": "pwduser", "password": "OldPwd123",
        })
        assert resp.json()["code"] == 401

        # 新密码可以登录
        login2 = client.post("/api/auth/login", json={
            "username": "pwduser", "password": "NewPwd456",
        })
        assert login2.json()["code"] == 0
        token2 = login2.json()["data"]["access_token"]
        assert token2 != token1
