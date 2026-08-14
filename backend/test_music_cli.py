import json
import requests
from typing import Type, Optional
from pydantic import BaseModel, Field
from langchain_core.tools import BaseTool, tool
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

# ==========================================
# 1. 基础配置区 (基础设施与网关配置)
# ==========================================
# one-api 网关配置：LangChain 会将符合 OpenAI 规范的请求发送至此
ONE_API_BASE_URL = "http://192.168.1.133:7086/v1"
ONE_API_KEY = "sk-YfAcgkoZLPwtNPluF54cAaCaFe2b48F4Bf8cA6943d988e9f"  # 你的 one-api 令牌

# n8n Webhook 根地址：Python 代码通过 HTTP POST 触发 n8n 工作流
N8N_BASE_URL = "http://192.168.1.133:5678"                       # 你的 n8n 服务地址


# ==========================================
# 2. 工具输入参数 Schema (基于 Pydantic)
# ==========================================
# 作用：向大模型 (LLM) 准确描述工具需要什么格式的入参。
# LLM 会读取这里的 description，决定从用户输入中提取什么信息填入。

class FetchMP3Input(BaseModel):
    """音频下载工具的参数定义"""
    # 核心修改：将原先的 url 改为 song_info，明确告诉模型这里接收的是搜索关键字
    song_info: str = Field(
        description="需要搜索并下载的歌曲信息，例如：'周杰伦 晴天' 或 'Taylor Swift Swift'"
    )


class RenameFileInput(BaseModel):
    """文件重命名工具的参数定义"""
    # 设置为 Optional，使该工具既支持‘自动批处理预设文件夹’，也支持‘指定新旧文件名’
    old_name: Optional[str] = Field(
        default=None, 
        description="可选：原文件名，包含扩展名（如 'test.mp3'）。如果不传则自动处理默认文件夹。"
    )
    new_name: Optional[str] = Field(
        default=None, 
        description="可选：重命名后的新文件名，包含扩展名（如 '晴天.mp3'）。"
    )


# ==========================================
# 3. 工具定义 (定义真正的 Python 执行函数)
# ==========================================

# ------------------------------------------
# 工具 1：下载 MP3 (使用 @tool 装饰器快速构建)
# ------------------------------------------
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


# ------------------------------------------
# 工具 2：重命名文件 (使用 继承 BaseTool 类 的方式)
# ------------------------------------------
class RenameFileTool(BaseTool):
    name: str = "rename"
    # Docstring 非常关键！LLM 根据这里的描述决定什么时候用这个工具
    description: str = (
        "用于对已下载的音频文件进行重命名整理。"
        "不用传参数触发‘全自动整理文件夹’。"
    )
    args_schema: Type[BaseModel] = RenameFileInput

    def _run(self, old_name: Optional[str] = None, new_name: Optional[str] = None) -> str:
        webhook_url = f"{N8N_BASE_URL}/webhook/rename"
        
        # 组装发送给 n8n 的参数
        payload = {
            "old_name": old_name,
            "new_name": new_name
        }
        
        try:
            response = requests.post(webhook_url, json=payload, timeout=15)
            response.raise_for_status()
            
            if old_name and new_name:
                return f"已成功将 '{old_name}' 重命名为 '{new_name}'。"
            else:
                return f"已触发自动批量重命名任务，n8n 返回结果: {response.text}"
                
        except requests.exceptions.RequestException as e:
            return f"调用 n8n 重命名接口失败: {str(e)}"


# ==========================================
# 4. 模型初始化与工具绑定 (Tool Binding)
# ==========================================
# 初始化 ChatOpenAI 客户端（通过 one-api 代理）
llm = ChatOpenAI(
    model="deepseek-chat",
    openai_api_base=ONE_API_BASE_URL,
    openai_api_key=ONE_API_KEY,
    temperature=0.1,  # 降低随机性，使模型在 Tool Calling 参数提取时更稳定准确
)

# 实例化所有工具并存入列表
tools = [fetch_mp3_tool, RenameFileTool()]

# 【关键步骤】使用 bind_tools 将工具列表传给 LLM
# 此时 LangChain 会将工具转换成 OpenAI 格式的 JSON Schema，并在请求时发送给 DeepSeek
llm_with_tools = llm.bind_tools(tools)


# ==========================================
# 5. Agent 单步推理与工具执行主循环
# ==========================================
def run_agent_step(user_prompt: str):
    """
    模拟标准 ReAct Agent 的单轮交互逻辑：
    1. 用户提问 -> 发送给 LLM
    2. LLM 分析意图 -> 返回是否需要调用 Tool (tool_calls)
    3. Python 执行对应的 Tool (请求 n8n Webhook)
    4. 将 Tool 的执行结果包装为 ToolMessage -> 再送回给 LLM
    5. LLM 根据工具执行结果进行总结 -> 输出最终用户可读的回答
    """
    print(f"\n==========================================")
    print(f"👉 用户输入: '{user_prompt}'")
    print(f"==========================================")
    
    # 构造基础 Prompt 上下文
    messages = [
        SystemMessage(content=(
            "你是一个智能音乐与文件管理助手。"
            "当用户想要下载音乐时，提取出歌手和歌名，调用 fetch_mp3 工具；"
            "当用户想要重命名或者整理音乐文件时，调用 rename 工具。"
        )),
        HumanMessage(content=user_prompt)
    ]
    
    # 【第 1 次 LLM 调用】：发送消息，让 DeepSeek 决定是否调用工具
    ai_msg = llm_with_tools.invoke(messages)
    messages.append(ai_msg)  # 将 AI 的初步回复（可能包含 tool_calls）存入历史
    
    # 如果 AI 没有生成 tool_calls，说明只是普通聊天，直接输出文本即可
    if not ai_msg.tool_calls:
        print("🤖 AI 直连回复:", ai_msg.content)
        return

    # 【工具执行逻辑】：解析 LLM 想要调用的工具列表
    tools_by_name = {t.name: t for t in tools}
    
    for tool_call in ai_msg.tool_calls:
        tool_name = tool_call["name"]
        tool_args = tool_call["args"]
        tool_id = tool_call["id"]
        
        print(f"\n🛠️  [Agent 决策]: 触发工具调用 -> {tool_name}")
        print(f"📥 [模型解析参数]: {json.dumps(tool_args, ensure_ascii=False)}")
        
        selected_tool = tools_by_name.get(tool_name)
        if selected_tool:
            # 本地真正调用工具函数，内部触发对应的 n8n Webhook
            tool_output = selected_tool.invoke(tool_args)
            print(f"📤 [n8n 返回结果]: {tool_output}")
            
            # 构造标准的 ToolMessage 节点挂回对话上下文
            # tool_call_id 用于告诉大模型“这是对应刚才哪一次工具请求的执行结果”
            messages.append(ToolMessage(content=str(tool_output), tool_call_id=tool_id))
        else:
            print(f"❌ 错误: 未能在注册列表中找到工具 '{tool_name}'")

    # 【第 2 次 LLM 调用】：把工具执行成功/失败的消息送回给 DeepSeek，生成最终总结
    print("\n⏳ 正在整理工具结果并生成最终回复...")
    final_response = llm_with_tools.invoke(messages)
    print(f"\n🤖 AI 最终回复:\n{final_response.content}")


# ==========================================
# 6. 本地测试入口
# ==========================================
if __name__ == "__main__":
    # 测试场景 1：传入歌手歌名（非 URL），测试搜索下载逻辑
    # run_agent_step("帮我下载一首河图的陌上花早")
    
    print("\n" + "="*50 + "\n")
    
    # 测试场景 2：测试触发自动重命名工作流
    # run_agent_step("把刚刚下载好的音乐文件重命名整理一下")