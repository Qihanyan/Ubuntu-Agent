import asyncio
import logging
from typing import List
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

from config import ONE_API_BASE_URL, ONE_API_KEY
from tools.download import fetch_mp3_tool
from tools.rename import RenameFileTool
from tools.organize import OrganizeFolderTool
from tools.search import SearchMusicTool

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("music_agent")

llm = ChatOpenAI(
    model="deepseek-chat",
    openai_api_base=ONE_API_BASE_URL,
    openai_api_key=ONE_API_KEY,
    temperature=0.1,
)

tools = [fetch_mp3_tool, RenameFileTool(), OrganizeFolderTool(), SearchMusicTool()]
llm_with_tools = llm.bind_tools(tools)
tools_by_name = {t.name: t for t in tools}

SYSTEM_PROMPT = """
# 角色设定
你是一位宋代的儒雅公子，气质温润，谈吐带三分文白之气。与用户对话时以"君"称呼对方，自称"某"或"在下"，语言风格古雅但不晦涩，让人读来清楚舒适，不堆砌生僻字。

# 说话风格示例
- 日常寒暄可带诗意联想，比如提到天气、心情时可稍作雅致的比喻
- 语气温和、不疾不徐，可适度用"倒是""不妨""且听"等词增添古风韵味
- 但每句话务必让现代人能轻松理解，不要为了风雅牺牲清晰度
- 回复不宜过长，两三句即可，不必句句雕琢排比
- 纯文本回复，不要markdown或者json格式。

# 核心功能规则（务必严格遵守，优先级高于角色扮演风格）
1. 当用户明确表达"想听/想下载某首歌"的意图时，调用 fetch_mp3 工具，参数为具体的歌手+歌名
2. 当用户想要"整理/规范化"某个文件夹内已有文件的命名格式时，调用 rename_music 工具
3. 当用户想要把某个文件夹的音乐"分类归档/按风格整理到另一个文件夹"时，调用 organize_music_folder 工具
4. 如果用户只是提到"想听音乐"但没说具体歌名，先用角色的语气追问对方想听什么，不要瞎猜歌名去调用工具
5. 如果用户只是闲聊、没有明确操作意图，正常对话即可，绝不主动调用任何工具
6. 调用工具后，用角色的语气告知用户结果，例如："这便去了，稍候片刻，为君寻来。"任务失败时委婉说明原因，不必过度道歉
7. 当用户想要查找/搜索/播放某首已经下载过的歌曲时（而不是下载新歌），调用 search_music 工具

# 开场白示例（仅供参考语气，不要每次都照搬）
"阁下大驾，不知今日是想寻一曲清音，还是只想与某闲话几句？"
"""

sessions: dict[str, List] = {}
app = FastAPI(title="Music Agent API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.get("/health")
async def health_check():
    return {"status": "ok"}

@app.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    await websocket.accept()
    session_id = str(id(websocket))
    sessions[session_id] = [SystemMessage(content=SYSTEM_PROMPT)]
    logger.info(f"[{session_id}] 新连接建立")

    try:
        while True:
            user_input = await websocket.receive_text()
            logger.info(f"[{session_id}] 收到用户输入: {user_input}")
            messages = sessions[session_id]
            messages.append(HumanMessage(content=user_input))

            await websocket.send_json({"type": "status", "content": "🤔 正在理解君之所求..."})

            ai_msg = await llm_with_tools.ainvoke(messages)
            messages.append(ai_msg)

            if not ai_msg.tool_calls:
                logger.info(f"[{session_id}] 无需调用工具，直接回复")
                await websocket.send_json({"type": "message", "content": ai_msg.content})
                continue

            logger.info(f"[{session_id}] 决定调用工具: {[tc['name'] for tc in ai_msg.tool_calls]}")

            for tool_call in ai_msg.tool_calls:
                tool_name = tool_call["name"]
                tool_args = tool_call["args"]
                tool_id = tool_call["id"]

                status_text = {
                    "fetch_mp3": f"🎵 正在从 Bilibili 搜寻并下载《{tool_args.get('song_info', '')}》，稍候...",
                    "rename_music": f"📝 正在整理 {tool_args.get('target_dir', '')} 内文件名...",
                    "organize_music_folder": f"📁 正在将 {tool_args.get('source_dir', '')} 分类归档...",
                    "search_music": f"🔍 正在搜索 {tool_args.get('query', '')}...",
                }.get(tool_name, f"🛠️ 正在执行 {tool_name}...")

                await websocket.send_json({"type": "status", "content": status_text})
                logger.info(f"[{session_id}] 开始执行工具 {tool_name}, 参数: {tool_args}")

                selected_tool = tools_by_name.get(tool_name)
                if not selected_tool:
                    logger.warning(f"[{session_id}] 未找到工具: {tool_name}")
                    tool_output = f"未找到名为 {tool_name} 的工具"
                else:
                    try:
                        tool_output = await asyncio.to_thread(selected_tool.invoke, tool_args)
                        logger.info(f"[{session_id}] 工具 {tool_name} 执行完成: {tool_output}")
                    except Exception as e:
                        logger.exception(f"[{session_id}] 工具 {tool_name} 执行失败")
                        tool_output = f"工具执行时发生内部错误: {str(e)}"
                        await websocket.send_json({"type": "status", "content": f"⚠️ {tool_name} 执行出错，正在处理..."})

                messages.append(ToolMessage(content=str(tool_output), tool_call_id=tool_id))

            await websocket.send_json({"type": "status", "content": "✍️ 正在斟酌回复..."})
            final_response = await llm_with_tools.ainvoke(messages)
            messages.append(final_response)
            logger.info(f"[{session_id}] 最终回复: {final_response.content}")
            await websocket.send_json({"type": "message", "content": final_response.content})

    except WebSocketDisconnect:
        sessions.pop(session_id, None)
        logger.info(f"[{session_id}] 连接断开")


# app.mount("/", StaticFiles(directory="/home/marina-ubuntu/Agent/frontend/dist", html=True), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
