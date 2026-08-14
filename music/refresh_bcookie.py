import asyncio
import json
from bilibili_api import Credential

async def main():
    with open("credential.json") as f:
        data = json.load(f)

    credential = Credential(
        sessdata=data["sessdata"],
        bili_jct=data["bili_jct"],
        buvid3=data["buvid3"],
        dedeuserid=data["dedeuserid"],
        ac_time_value=data["ac_time_value"],
    )

    # 检查是否需要刷新
    if await credential.check_refresh():
        print("Cookie 需要刷新，正在刷新...")
        await credential.refresh()
        print("刷新完成")

        # 更新保存的凭据（新的 refresh_token 必须存起来，下次要用）
        with open("credential.json", "w") as f:
            json.dump({
                "sessdata": credential.sessdata,
                "bili_jct": credential.bili_jct,
                "buvid3": credential.buvid3,
                "dedeuserid": credential.dedeuserid,
                "ac_time_value": credential.ac_time_value,
            }, f)
    else:
        print("Cookie 仍然有效，无需刷新")

    # 导出成 yt-dlp 需要的 Netscape 格式
    with open("/home/marina-ubuntu/Agent/music/cookies.txt", "w") as f:
        f.write("# Netscape HTTP Cookie File\n")
        f.write(f".bilibili.com\tTRUE\t/\tTRUE\t2147483647\tSESSDATA\t{credential.sessdata}\n")
        f.write(f".bilibili.com\tTRUE\t/\tTRUE\t2147483647\tbili_jct\t{credential.bili_jct}\n")
        f.write(f".bilibili.com\tTRUE\t/\tFALSE\t2147483647\tbuvid3\t{credential.buvid3}\n")
        f.write(f".bilibili.com\tTRUE\t/\tTRUE\t2147483647\tDedeUserID\t{credential.dedeuserid}\n")

    print("已导出到 cookies.txt")

asyncio.run(main())