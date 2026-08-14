import json
import shutil
from pathlib import Path
from typing import List
from pydantic import BaseModel, Field
from langchain_core.tools import BaseTool
from langchain_openai import ChatOpenAI
from config import ONE_API_BASE_URL, ONE_API_KEY
import json as json_lib
from tools.security import validate_path


class MoveInstruction(BaseModel):
    filename: str = Field(description="源文件文件名")
    genre: str = Field(description="第一级风格文件夹名称")
    artist: str = Field(description="第二级歌手文件夹名称，未知填'未知歌手'")

class OrganizationPlan(BaseModel):
    plan: List[MoveInstruction] = Field(description="所有文件的移动归档计划")

class OrganizeFolderInput(BaseModel):
    """整理工具的参数——针对'把源文件夹的文件分类归档到目标文件夹的风格/歌手结构'这个场景"""
    source_dir: str = Field(default="/home/storage/music_repo", description="待整理的源文件夹")
    target_dir: str = Field(default="/home/storage/music", description="归档目标文件夹")

AUDIO_EXTENSIONS = {'.mp3', '.flac', '.m4a', '.wav', '.aac', '.ogg'}

class OrganizeFolderTool(BaseTool):
    name: str = "organize_music_folder"
    description: str = (
        "当用户想要把某个文件夹里的音频文件，按风格和歌手分类归档到两级目录结构时使用。"
        "例如'把storage里的音乐整理到music库里'。"
    )
    args_schema: type = OrganizeFolderInput

    def _run(self, source_dir: str = "/home/storage/music_repo", target_dir: str = "/home/storage/music") -> str:
        try:
            source_path = validate_path(source_dir)
            target_path = validate_path(target_dir)
        except PermissionError as e:
            return f"❌ 路径校验失败，无法访问该路径: {e}"
        
        source_path, target_path = Path(source_dir), Path(target_dir)
        if not source_path.exists():
            return f"❌ 源文件夹不存在: {source_dir}"
        target_path.mkdir(parents=True, exist_ok=True)

        source_files = [f.name for f in source_path.iterdir() if f.is_file() and f.suffix.lower() in AUDIO_EXTENSIONS]
        if not source_files:
            return "ℹ️ 源文件夹中没有找到待整理的音频文件。"

        existing_structure = {}
        for genre_dir in target_path.iterdir():
            if genre_dir.is_dir():
                existing_structure[genre_dir.name] = [a.name for a in genre_dir.iterdir() if a.is_dir()]

        llm = ChatOpenAI(
            model="deepseek-chat",
            temperature=0,
            api_key=ONE_API_KEY,
            base_url=ONE_API_BASE_URL,
        )
        structured_llm = llm.with_structured_output(OrganizationPlan)

        prompt = f"""
        你是一个专业的音乐库整理专家，请将待整理文件分类归档。

        分类规则：
        1. 第一级文件夹按音乐风格分类（国风、流行、摇滚、电子、爵士、ACG、古典等）。
        2. 第二级文件夹按歌手/艺术家分类。
        3. 优先复用目标文件夹现有结构，避免创建意思相近的重复文件夹。
        4. 无法推断歌手填"未知歌手"，无法确定风格填"其他"。

        目标文件夹现有结构 (风格 -> [歌手列表]):
        {json.dumps(existing_structure, ensure_ascii=False, indent=2)}

        待整理文件列表:
        {json.dumps(source_files, ensure_ascii=False, indent=2)}

        请仅输出如下格式的 JSON，不要有任何其他文字、不要用markdown代码块包裹：
        {{
        "plan": [
            {{"filename": "示例文件名.mp3", "genre": "流行", "artist": "示例歌手"}}
        ]
        }}
        plan 数组里必须包含【待整理文件列表】中每一个文件的分类结果，一一对应，不能遗漏。
        """

        try:
            response = llm.invoke(prompt)
            content = response.content.strip()
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
            content = content.strip()

            response_plan = OrganizationPlan.model_validate_json(content)

            # response: OrganizationPlan = structured_llm.invoke(prompt)
        except Exception as e:
            return f"❌ 大模型推理失败: {e}"

        results = []
        for item in response_plan.plan:
            src_file = source_path / item.filename
            if not src_file.exists():
                results.append(f"⚠️ 文件不存在，跳过: {item.filename}")
                continue
            dest_dir = target_path / item.genre.strip() / item.artist.strip()
            dest_file = dest_dir / item.filename
            dest_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src_file), str(dest_file))
            results.append(f"✅ {item.filename} ➔ 📁{item.genre}/🎤{item.artist}")

        return f"整理完成，共处理 {len(response_plan.plan)} 个文件：\n" + "\n".join(results)