from pydantic import BaseModel, Field
from langchain_core.tools import tool
import requests
from config import N8N_BASE_URL

# ------------------------------------------
# 工具 1：下载 MP3 (使用 @tool 装饰器快速构建)
# ------------------------------------------

class FetchMP3Input(BaseModel):
    song_info: str = Field(description="需要搜索并下载的歌曲信息，例如：'周杰伦 晴天'")


@tool("fetch_mp3", args_schema=FetchMP3Input)
def fetch_mp3_tool(song_info: str) -> str:
    """
    【工具功能描述】：
    当用户表达想听某首歌、下载某首音乐、或者搜索特定歌手/歌名的音频时调用此工具。
    注意：此工具不需要网址链接，只需要传入歌名或歌手信息（如 '周杰伦 晴天'）。
    """
    # 拼接 n8n 的 Production/Test Webhook 路径
    webhook_url = f"{N8N_BASE_URL}/webhook/fetch-mp3"
    
    # 构造发送给 n8n 的 JSON Body，key等于"song"
    # $json.body.song
    payload = {"song": song_info}
    
    try:
        # 发起 HTTP POST 请求触发 n8n 工作流
        # timeout 设置为 60s，因为 bilibili 搜索+下载转音频需要一定时间
        response = requests.post(webhook_url, json=payload, timeout=60)
        response.raise_for_status()  # 检查 HTTP 状态码是否为 200 OK
        
        # 返回结果会作为 ToolMessage 给大模型，让大模型知道执行情况
        return f"n8n 下载任务触发成功！目标歌曲: '{song_info}'，后台处理中。响应内容: {response.text}"
    
    except requests.exceptions.RequestException as e:
        # 捕获网络异常/超时，并将错误友好返回给 LLM
        return f"调用 n8n 下载接口失败: {str(e)}"
