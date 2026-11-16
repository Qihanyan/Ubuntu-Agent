"""
所有 Pydantic schema 的公共基类和可复用的字段类型。

StrictModel：
  - extra="forbid"：多出来的字段直接报错，而不是悄悄忽略
  - strict=True：不做类型转换（"false" 不会变成 False，123 不会变成 "123"）
  - str_strip_whitespace=True：字符串先去首尾空白，再检查长度等约束
"""
from typing import Annotated, Callable

from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict, StringConstraints, ValidationError

from tools.security import validate_path


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)


# ------------------------------------------------------------------
# 路径：必须落在白名单目录内，校验通过后替换成 resolve 后的绝对路径
# ------------------------------------------------------------------
def _allowed_dir(v: str) -> str:
    try:
        return str(validate_path(v))
    except PermissionError as e:
        raise ValueError(str(e)) from e


AllowedDir = Annotated[str, StringConstraints(min_length=1, max_length=4096), AfterValidator(_allowed_dir)]


# ------------------------------------------------------------------
# 单级文件/文件夹名：LLM 输出的名字会被拼进路径，必须保证它只是"一级名字"
# 禁止 / \ 和控制字符、禁止 . 和 ..，防止路径穿越或绝对路径替换（Path("/a") / "/etc" == "/etc"）
# ------------------------------------------------------------------
def _single_path_segment(v: str) -> str:
    if v in {".", ".."}:
        raise ValueError(f"非法名称: {v!r}")
    if any(c in v for c in "/\\") or any(ord(c) < 32 for c in v):
        raise ValueError(f"名称中不能包含路径分隔符或控制字符: {v!r}")
    return v


def SafeName(max_length: int):
    return Annotated[str, StringConstraints(min_length=1, max_length=max_length), AfterValidator(_single_path_segment)]


# LLM 经常把"空"写成 null。先统一成 ""，再走严格的 str 校验
def _none_to_empty(v):
    return "" if v is None else v


def OptionalText(max_length: int):
    return Annotated[str, BeforeValidator(_none_to_empty), StringConstraints(max_length=max_length)]


# ------------------------------------------------------------------
# 工具参数校验失败时，把错误原因返回给 LLM（而不是抛异常），让它有机会修正参数
# ------------------------------------------------------------------
ToolValidationHandler = bool | str | Callable[[ValidationError], str] | None  # 与 BaseTool 字段类型一致


def format_tool_validation_error(e: ValidationError) -> str:
    details = "; ".join(f"{'.'.join(map(str, err['loc'])) or '参数'}: {err['msg']}" for err in e.errors())
    return f"工具参数校验失败，未执行任何操作。原因: {details}"
