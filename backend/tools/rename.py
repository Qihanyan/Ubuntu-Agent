import os
import re
import shutil
from pathlib import Path
from typing import Optional, Type, List
from pydantic import BaseModel, Field
from langchain_core.tools import BaseTool
from langchain_openai import ChatOpenAI
from config import ONE_API_BASE_URL, ONE_API_KEY
import json as json_lib
from tools.security import validate_path


# ==========================================
# 1. 结构化输出 Pydantic 模型定义
# ==========================================
class SongMetadata(BaseModel):
    is_instrumental: bool = Field(
        description="是否为纯音乐/纯伴奏（无歌曲人声演唱，如纯钢琴曲、BGM、伴奏等）"
    )
    instrument: Optional[str] = Field(
        default="",
        description="如果是纯音乐，演奏的主要乐器名称（如 '钢琴'、'古筝'、'小提琴'）。如果无法识别或多种乐器合奏，填 '纯音乐'"
    )
    artist: str = Field(
        default="未知歌手",
        description="歌手、UP主或作曲人名称"
    )
    title: str = Field(
        description="歌曲或曲目名称（去除标题党描述、清晰度标注如 1080P/4K 等）"
    )
    highlight_lyric: Optional[str] = Field(
        default="",
        description="最有代表性的一句歌词（如果是纯音乐，可以是经典评语、曲风描述或留空）"
    )

class RenameFolderInput(BaseModel):
    """文件重命名工具的参数定义"""
    target_dir: Optional[str] = Field(
        default="/home/storage/music_repo",
        description="需要批量整理整理和重命名的音频文件夹路径，默认为 '/home/storage/music_repo'"
    )

# ==========================================
# 2. 重构后的 RenameFileTool 基础工具
# ==========================================
class RenameFileTool(BaseTool):
    name: str = "rename_music"
    description: str = (
        "扫描指定文件夹中的音频文件（.mp3, .mp4, .flac, .m4a），"
        "利用 AI 分析歌曲信息，并重命名为标准化格式："
        "纯音乐: <乐器> - <歌手> - <歌曲> - <代表描述>.mp3\n"
        "普通歌曲: <歌手> - <歌曲> - <代表歌词>.mp3"
    )
    args_schema: Type[BaseModel] = RenameFolderInput

    def _sanitize_filename(self, name: str) -> str:
        """清洗文件名中的非法字符，防止路径穿越或系统报错"""
        # 替换 Windows/Linux 禁用的文件名字符: \ / : * ? " < > |
        cleaned = re.sub(r'[\\/:*?"<>|]', '', name)
        return cleaned.strip()

    def _get_unique_path(self, target_file: Path) -> Path:
        """处理文件名冲突，如果文件已存在，自动生成 _2, _3 后缀"""
        if not target_file.exists():
            return target_file
        
        stem = target_file.stem
        suffix = target_file.suffix
        parent = target_file.parent
        counter = 2
        
        while True:
            new_path = parent / f"{stem}_{counter}{suffix}"
            if not new_path.exists():
                return new_path
            counter += 1

    def _run(self, target_dir: Optional[str] = "/home/storage/music_repo") -> str:
        try:
            music_path  = validate_path(target_dir)
        except PermissionError as e:
            return f"❌ 路径校验失败，无法访问该路径: {e}"

        music_path = Path(target_dir)
        if not music_path.exists():
            return f"❌ 找不到目标文件夹: {target_dir}"

        # 支持的音频后缀
        audio_extensions = {".mp3", ".mp4", ".m4a", ".flac", ".wav", ".aac"}
        
        # 扫描待整理文件
        files = [f for f in music_path.iterdir() if f.is_file() and f.suffix.lower() in audio_extensions]
        if not files:
            return f"📁 文件夹 '{target_dir}' 中没有需要整理的音频文件。"

        # 初始化专门用于分析元数据的 LLM
        metadata_llm = ChatOpenAI(
            model="deepseek-chat",
            openai_api_base=ONE_API_BASE_URL,
            openai_api_key=ONE_API_KEY,
            temperature=0.1
        )

        results = []

        for file_path in files:
            old_name = file_path.name
            
            prompt = f"""
你是一个音频元信息分析专家。请分析以下音频文件名/描述，精准提取元信息：
文件名: "{old_name}"

要求：
1. 提取歌手/作曲/UP主、真实歌名/曲名。去除所有无关的后缀（如 1080P, 4K, 官方版, MVP, 翻唱, [MP3] 等）。
2. 判断是否为纯音乐/纯伴奏（无人声演唱）。如果是纯音乐，提取主要演奏乐器（如钢琴/古筝）；若无法确定具体乐器，乐器填 "纯音乐"。
3. 提取或匹配该歌曲【最有代表性/最出名的一句歌词】（例如《晴天》对应"刮风这天试着握紧手"；如果是纯音乐，填写一句简短的意境描述或留空）。
请仅输出如下格式的 JSON，不要有任何其他文字、不要用markdown代码块包裹：
{{"is_instrumental": false, "instrument": "", "artist": "歌手名", "title": "歌曲名", "highlight_lyric": "一句歌词"}}
"""
            try:
                response = metadata_llm.invoke(prompt)
                content = response.content.strip()
                # 去除可能的markdown代码块标记
                if content.startswith("```"):
                    content = content.split("```")[1]
                    if content.startswith("json"):
                        content = content[4:]
                content = content.strip()

                meta: SongMetadata = SongMetadata.model_validate_json(content)

                # # 调用 AI 结构化输出
                # meta: SongMetadata = metadata_llm.invoke(prompt)

                # 根据规则拼装新文件名
                artist = self._sanitize_filename(meta.artist or "未知歌手")
                title = self._sanitize_filename(meta.title or "未知曲目")
                lyric = self._sanitize_filename(meta.highlight_lyric or "")

                # 提取歌词/描述组合
                lyric_part = f" - {lyric}" if lyric else ""

                if meta.is_instrumental:
                    instrument = self._sanitize_filename(meta.instrument or "纯音乐")
                    new_filename = f"{instrument} - {artist} - {title}{lyric_part}{file_path.suffix}"
                else:
                    new_filename = f"{artist} - {title}{lyric_part}{file_path.suffix}"

                # 获取不冲突的最终目标路径
                dest_path = self._get_unique_path(music_path / new_filename)

                # 执行本地文件重命名 (shutil.move)
                if file_path != dest_path:
                    shutil.move(str(file_path), str(dest_path))
                    results.append(f"✅ '{old_name}' ➔ '{dest_path.name}'")
                else:
                    results.append(f"ℹ️ '{old_name}' 已经是最新格式，无需更改")

            except Exception as e:
                results.append(f"❌ '{old_name}' 重命名失败: {str(e)}")

        summary = "\n".join(results)
        return f"批量重命名任务完成！处理结果如下:\n{summary}"