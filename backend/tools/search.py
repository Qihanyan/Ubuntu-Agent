from pathlib import Path
from urllib.parse import quote
from pydantic import BaseModel, Field
from langchain_core.tools import BaseTool
from opencc import OpenCC

MSTREAM_BASE_URL = "http://192.168.1.133:1999/files"

SEARCH_LOCATIONS = {
    "/home/storage/music": "music",
    "/home/storage/music_repo": "music_repo",
}

AUDIO_EXTENSIONS = {".mp3", ".mp4", ".flac", ".m4a", ".wav"}

# 繁转简 / 简转繁 两个转换器
t2s = OpenCC('t2s')  # 繁体 -> 简体
s2t = OpenCC('s2t')  # 简体 -> 繁体

def normalize_variants(text: str) -> set[str]:
    """返回一个词的所有繁简变体，用于匹配时全部尝试"""
    simplified = t2s.convert(text)
    traditional = s2t.convert(text)
    return {text.lower(), simplified.lower(), traditional.lower()}


class SearchMusicInput(BaseModel):
    query: str = Field(description="用户想搜索的歌曲名、歌手名或关键词")

class SearchMusicTool(BaseTool):
    name: str = "search_music"
    description: str = (
        "当用户想要查找/搜索/播放某首已经下载过的歌曲时使用（而不是下载新歌）。"
        "支持繁简体自动匹配，会模糊匹配歌手名或歌曲名，返回可直接播放的链接。"
    )
    args_schema: type = SearchMusicInput

    def _run(self, query: str) -> str:
        query_variants = normalize_variants(query)
        matches = []

        for real_path, url_prefix in SEARCH_LOCATIONS.items():
            base = Path(real_path)
            if not base.exists():
                continue

            for file_path in base.rglob("*"):
                if file_path.is_file() and file_path.suffix.lower() in AUDIO_EXTENSIONS:
                    filename_variants = normalize_variants(file_path.stem)

                    # 只要 query 的任一变体，是文件名任一变体的子串，就算命中
                    hit = any(
                        qv in fv
                        for qv in query_variants
                        for fv in filename_variants
                    )

                    if hit:
                        relative_path = file_path.relative_to(base)
                        encoded_path = "/".join(quote(part) for part in relative_path.parts)
                        url = f"{MSTREAM_BASE_URL}/{url_prefix}/{encoded_path}"
                        matches.append((file_path.stem, url))

        if not matches:
            return f"未找到与 '{query}' 匹配的歌曲。"

        results = [f"🎵 {name}\n   {url}" for name, url in matches[:10]]
        return f"找到 {len(matches)} 首匹配歌曲：\n\n" + "\n\n".join(results)