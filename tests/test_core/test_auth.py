"""JWT 签发/解码 + 密码校验测试。"""
import pytest
from backend.core.auth import (
    hash_pw, verify_pw, validate_password,
    create_access_token, decode_token,
)


class TestPasswordHashing:

    def test_hash_and_verify(self):
        pw = "Test1234"
        h = hash_pw(pw)
        assert h != pw
        assert verify_pw(pw, h) is True

    def test_wrong_password(self):
        h = hash_pw("Right123")
        assert verify_pw("Wrong456", h) is False

    def test_empty_password_does_not_crash(self):
        h = hash_pw("Some123")
        assert verify_pw("", h) is False


class TestPasswordValidation:

    def test_too_short(self):
        assert validate_password("Ab1") is not None

    def test_no_uppercase(self):
        assert validate_password("abcdefg1") is not None

    def test_no_digit(self):
        assert validate_password("Abcdefgh") is not None

    def test_valid(self):
        assert validate_password("ValidPwd123") is None


class TestJWT:

    def test_create_and_decode(self):
        token = create_access_token("testuser")
        payload = decode_token(token)
        assert payload is not None
        assert payload["sub"] == "testuser"

    def test_invalid_token_returns_none(self):
        assert decode_token("not.a.valid.token") is None
        assert decode_token("") is None

    def test_expired_token(self, mocker):
        """过期 token 返回 None。"""
        from datetime import datetime, timedelta, timezone
        import jwt as pyjwt
        from backend.config import JWT_SECRET, JWT_ALGORITHM

        past = datetime.now(timezone.utc) - timedelta(hours=48)
        payload = {"sub": "olduser", "iat": past, "exp": past + timedelta(hours=1)}
        token = pyjwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
        assert decode_token(token) is None


class TestTokenVersion:

    def test_token_carries_tv(self):
        """create_access_token 传入 token_version 后，JWT payload 应包含 tv 字段。"""
        token = create_access_token("alice", token_version=3)
        payload = decode_token(token)
        assert payload is not None
        assert payload["sub"] == "alice"
        assert payload["tv"] == 3

    def test_token_tv_defaults_to_zero(self):
        """不传 token_version 时 tv 默认为 0（向后兼容）。"""
        token = create_access_token("bob")
        payload = decode_token(token)
        assert payload is not None
        assert payload["tv"] == 0

    def test_tv_zero_backward_compat(self):
        """tv=0 的旧 token 仍然可以正常解码（不做 DB 比对时）。"""
        import jwt as pyjwt
        from datetime import datetime, timedelta, timezone
        from backend.config import JWT_SECRET, JWT_ALGORITHM

        now = datetime.now(timezone.utc)
        payload = {"sub": "legacy", "iat": now, "exp": now + timedelta(hours=1)}
        # 没有 tv 字段的旧格式 token
        token = pyjwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
        decoded = decode_token(token)
        assert decoded is not None
        assert decoded["sub"] == "legacy"
        # 旧 token 的 tv 缺失时，decode 后 tv 应为 None/via .get default
        assert decoded.get("tv", 0) == 0
