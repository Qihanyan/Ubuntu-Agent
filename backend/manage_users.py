"""
python manage_users.py hash     # 输入密码，输出 bcrypt 哈希，粘贴到 settings.USERS
python manage_users.py secret   # 生成 JWT 密钥，写入环境变量 MUSIC_AGENT_JWT_SECRET
"""
import getpass
import secrets
import sys

import bcrypt


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "hash":
        pw = getpass.getpass("密码: ")
        if pw != getpass.getpass("再输一次: "):
            sys.exit("两次输入不一致")
        if len(pw.encode()) > 72:
            sys.exit("密码过长（bcrypt 上限 72 字节）")
        print(bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode())
    elif cmd == "secret":
        print(secrets.token_urlsafe(48))
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
