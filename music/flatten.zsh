#!/bin/zsh

# Usage: ./flatten.zsh /path/to/parent_folder

if [ "$#" -ne 1 ]; then
  echo "Usage: $0 <parent_folder>"
  exit 1
fi

parent="$1"

if [ ! -d "$parent" ]; then
  echo "文件夹不存在: $parent"
  exit 1
fi

count=0

# 递归找出所有子文件夹里的文件（不含母文件夹自身根目录下已有的文件）
find "$parent" -mindepth 2 -type f | while IFS= read -r file; do
  base_name=$(basename "$file")
  target="$parent/$base_name"

  # 处理重名：如果目标已存在，加 _2, _3 后缀
  if [ -e "$target" ]; then
    stem="${base_name%.*}"
    ext="${base_name##*.}"
    counter=2
    while [ -e "$parent/${stem}_${counter}.${ext}" ]; do
      counter=$((counter + 1))
    done
    target="$parent/${stem}_${counter}.${ext}"
  fi

  mv "$file" "$target"
  echo "移动: $file -> $target"
  count=$((count + 1))
done

# 删除所有空的子文件夹
find "$parent" -mindepth 1 -type d -empty -delete

echo "----------------------"
echo "完成。"