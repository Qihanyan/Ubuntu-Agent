from pathlib import Path

# 只允许在这些目录（及其子目录）内操作，其他一律拒绝
ALLOWED_ROOTS = [
    Path("/home/storage/music_repo").resolve(),
    Path("/home/storage/music").resolve(),
]

def validate_path(path_str: str) -> Path:
    """
    校验路径必须落在白名单目录内，拒绝任何越界、软链接逃逸、路径穿越尝试。
    校验失败直接抛异常，调用方必须处理。
    """
    resolved = Path(path_str).resolve()  # resolve() 会展开 .. 和软链接，拿到真实绝对路径

    for allowed_root in ALLOWED_ROOTS:
        try:
            resolved.relative_to(allowed_root)
            return resolved  # 校验通过，落在某个允许的根目录下
        except ValueError:
            continue

    raise PermissionError(f"路径 '{path_str}' 不在允许操作的范围内，已拒绝执行")