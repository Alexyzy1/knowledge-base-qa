import os
import sys
import bcrypt
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from auth_models import Base, User, Whitelist, KbMember

DB_URL = os.environ.get("MYSQL_URL", "mysql+pymysql://user:CHANGE_ME@127.0.0.1:3306/knowledge_base?charset=utf8mb4")
ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PW = os.environ.get("ADMIN_PW")
SEED_KB_IDS = [1, 2]


def hash_pw(pw: str) -> str:
    return bcrypt.hashpw(pw.encode()[:72], bcrypt.gensalt()).decode()


def main():
    if not ADMIN_PW:
        sys.exit("set ADMIN_PW env var, e.g.  ADMIN_PW=yourpass python init_auth.py")
    engine = create_engine(DB_URL)
    Base.metadata.create_all(engine)  # creates user/whitelist/kb_member only
    with Session(engine) as s:
        u = s.scalar(select(User).where(User.username == ADMIN_USER))
        if u is None:
            u = User(username=ADMIN_USER, password_hash=hash_pw(ADMIN_PW), role="super_admin")
            s.add(u); s.flush()
            print(f"created super_admin: {ADMIN_USER} (id={u.id})")
        else:
            print(f"super_admin already exists: {ADMIN_USER} (id={u.id})")
        if s.scalar(select(Whitelist).where(Whitelist.username == ADMIN_USER)) is None:
            s.add(Whitelist(username=ADMIN_USER, note="seed super_admin"))
            print(f"whitelisted: {ADMIN_USER}")
        for kid in SEED_KB_IDS:
            ex = s.scalar(select(KbMember).where(KbMember.kb_id == kid, KbMember.user_id == u.id))
            if ex is None:
                s.add(KbMember(kb_id=kid, user_id=u.id, role="owner"))
                print(f"kb {kid} -> owner {ADMIN_USER}")
        s.commit()
    with Session(engine) as s:
        print("users:", [(x.id, x.username, x.role) for x in s.scalars(select(User))])
        print("whitelist:", [x.username for x in s.scalars(select(Whitelist))])
        print("kb_member:", [(x.kb_id, x.user_id, x.role) for x in s.scalars(select(KbMember))])


if __name__ == "__main__":
    main()
