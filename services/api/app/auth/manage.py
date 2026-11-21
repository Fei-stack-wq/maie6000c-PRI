"""Provision accounts locally: python -m services.api.app.auth.manage --help."""

import argparse
import getpass

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from services.api.app.auth.passwords import hash_password, normalize_username
from services.common.config import get_settings
from services.common.db import get_session_factory
from services.common.models import IssueAction, ReviewSession, ReviewUser


def manage_user(
    db: Session, action: str, username: str, *, role: str | None = None, password: str | None = None
) -> ReviewUser:
    username = normalize_username(username)
    if role is not None and role not in {"viewer", "reviewer"}:
        raise ValueError("角色只能是 viewer 或 reviewer。")
    user = db.scalar(select(ReviewUser).where(ReviewUser.username == username).with_for_update())
    if action == "create":
        if user is not None:
            raise ValueError("账号已存在。")
        if username == get_settings().review_demo_operator.strip() or db.scalar(
            select(IssueAction.id).where(IssueAction.operator == username).limit(1)
        ):
            raise ValueError("此名称已用于历史身份，请选择新账号，避免混淆审计记录。")
        if role is None or password is None:
            raise ValueError("创建账号需要角色与密码。")
        user = ReviewUser(username=username, role=role, password_hash=hash_password(password))
        db.add(user)
    else:
        if user is None:
            raise ValueError("账号不存在。")
        if action == "password" and password is not None:
            user.password_hash = hash_password(password)
        elif action == "role" and role is not None:
            user.role = role
        elif action in {"disable", "enable"}:
            user.enabled = action == "enable"
        else:
            raise ValueError("操作或参数无效。")
        # Account changes invalidate every existing session, not only this browser.
        db.execute(delete(ReviewSession).where(ReviewSession.user_id == user.id))
    db.commit()
    return user


def main():
    parser = argparse.ArgumentParser(description="管理复核账号（没有公开注册接口）")
    parser.add_argument("action", choices=["create", "password", "role", "disable", "enable"])
    parser.add_argument("username")
    parser.add_argument("--role", choices=["viewer", "reviewer"])
    args = parser.parse_args()
    if args.action in {"create", "role"} and not args.role:
        parser.error("此操作需要 --role viewer 或 --role reviewer")
    password = None
    if args.action in {"create", "password"}:
        password = getpass.getpass("密码（12–256 个字符）: ")
        if password != getpass.getpass("再次输入密码: "):
            parser.error("两次密码不同。")
    try:
        with get_session_factory()() as db:
            user = manage_user(db, args.action, args.username, role=args.role, password=password)
            print(f"已完成 {args.action}: {user.username} / {user.role} / enabled={user.enabled}")
    except (ValueError, IntegrityError) as exc:
        parser.error(str(exc) if isinstance(exc, ValueError) else "账号已存在。")


if __name__ == "__main__":
    main()
