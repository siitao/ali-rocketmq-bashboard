from __future__ import annotations

import argparse
import getpass
import sys

from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import SessionLocal, init_db
from .models import User
from .rbac import ROLE_LEVELS
from .security import MAX_PASSWORD_LENGTH, hash_password


def _prompt_username(username: str | None) -> str:
    value = (username or input("用户名: ")).strip()
    if not value:
        raise SystemExit("用户名不能为空")
    if len(value) > 64:
        raise SystemExit("用户名不能超过 64 个字符")
    return value


def _prompt_password(password: str | None, *, confirm: bool = True) -> str:
    if password:
        print("警告：通过命令行参数传密码会留在 shell 历史中，建议改用交互式输入。", file=sys.stderr)
    else:
        password = getpass.getpass("密码（至少 8 位）: ")
        if confirm:
            again = getpass.getpass("确认密码: ")
            if password != again:
                raise SystemExit("两次输入的密码不一致")
    if len(password) < 8:
        raise SystemExit("密码至少 8 位")
    if len(password) > MAX_PASSWORD_LENGTH:
        raise SystemExit(f"密码不能超过 {MAX_PASSWORD_LENGTH} 位")
    return password


def _find_user(db: Session, username: str) -> User | None:
    return db.scalar(select(User).where(User.username == username))


def create_user(args: argparse.Namespace) -> int:
    init_db()
    username = _prompt_username(args.username)
    password = _prompt_password(args.password)

    with SessionLocal() as db:
        if _find_user(db, username):
            print(f"用户 {username} 已存在", file=sys.stderr)
            return 1
        user = User(
            username=username,
            password_hash=hash_password(password),
            role=args.role,
        )
        db.add(user)
        db.commit()
    print(f"已创建用户 {username}（角色：{args.role}）")
    return 0


def reset_password(args: argparse.Namespace) -> int:
    init_db()
    username = _prompt_username(args.username)
    password = _prompt_password(args.password)

    with SessionLocal() as db:
        user = _find_user(db, username)
        if user is None:
            print(f"用户 {username} 不存在", file=sys.stderr)
            return 1
        user.password_hash = hash_password(password)
        user.is_active = True
        db.commit()
    print(f"已重置 {username} 的密码并启用账号")
    return 0


def list_users(_args: argparse.Namespace) -> int:
    init_db()
    with SessionLocal() as db:
        users = db.scalars(select(User).order_by(User.username)).all()
    if not users:
        print("还没有任何用户，请先运行 create-admin")
        return 0
    print(f"{'用户名':<24} {'角色':<10} {'状态':<8} 最后登录")
    for user in users:
        status = "启用" if user.is_active else "停用"
        last = user.last_login_at.strftime("%Y-%m-%d %H:%M:%S") if user.last_login_at else "-"
        print(f"{user.username:<24} {user.role:<10} {status:<8} {last}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description="RocketMQ Console 管理命令")
    sub = parser.add_subparsers(dest="command", required=True)

    admin = sub.add_parser("create-admin", help="创建管理员账号")
    admin.add_argument("--username")
    admin.add_argument("--password")
    admin.set_defaults(func=lambda args: create_user(_with_role(args, "admin")))

    user = sub.add_parser("create-user", help="创建普通账号")
    user.add_argument("--username")
    user.add_argument("--password")
    user.add_argument("--role", choices=sorted(ROLE_LEVELS), default="viewer")
    user.set_defaults(func=create_user)

    reset = sub.add_parser("reset-password", help="重置密码（同时启用账号）")
    reset.add_argument("--username")
    reset.add_argument("--password")
    reset.set_defaults(func=reset_password)

    listing = sub.add_parser("list-users", help="列出账号")
    listing.set_defaults(func=list_users)
    return parser


def _with_role(args: argparse.Namespace, role: str) -> argparse.Namespace:
    args.role = role
    return args


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
