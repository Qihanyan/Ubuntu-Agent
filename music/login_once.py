import asyncio
from bilibili_api import login_v2

async def main():
    qr = login_v2.QrCodeLogin(platform=login_v2.QrCodeLoginChannel.WEB)
    await qr.generate_qrcode()
    print(qr.get_qrcode_terminal())  # 在终端显示二维码，用手机B站App扫

    while not qr.has_done():
        await qr.check_state()
        await asyncio.sleep(2)

    credential = qr.get_credential()
    print("登录成功！")
    print("SESSDATA:", credential.sessdata)
    print("bili_jct:", credential.bili_jct)
    print("buvid3:", credential.buvid3)
    print("DedeUserID:", credential.dedeuserid)
    print("ac_time_value (refresh_token):", credential.ac_time_value)

    # 保存到文件，后续脚本读取用
    import json
    with open("credential.json", "w") as f:
        json.dump({
            "sessdata": credential.sessdata,
            "bili_jct": credential.bili_jct,
            "buvid3": credential.buvid3,
            "dedeuserid": credential.dedeuserid,
            "ac_time_value": credential.ac_time_value,
        }, f)

asyncio.run(main())