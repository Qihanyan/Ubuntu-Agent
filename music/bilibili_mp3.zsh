#!/bin/zsh
export PATH="$HOME/.local/bin:$PATH"
# Usage:
#   ./allinall_bilibili.zsh urllist path_to_newsongs        # 原有用法：文件列表
#   ./allinall_bilibili.zsh -s "歌曲名" path_to_newsongs      # 新增：单曲直接下载

if [[ "$1" == "-s" ]]; then
  if [ "$#" -ne 3 ]; then
    echo "Usage: $0 -s \"song name\" dirname"
    exit 1
  fi
  song="$2"
  dirname="$3"
  filename=$(mktemp)
  echo "$song" > "$filename"
  cleanup_temp=1
else
  if [ "$#" -ne 2 ]; then
    echo "Usage: $0 filename dirname"
    exit 1
  fi
  filename="$1"
  dirname="$2"
  cleanup_temp=0
fi

if [ ! -d "$dirname" ]; then
  echo "The provided argument is not a valid directory."
  exit 1
fi

if [ ! -f "$filename" ]; then
  echo "File $filename does not exist"
  exit 1
fi

# Check for ffmpeg command (needed both to merge dash streams and to extract mp3)
if ! command -v ffmpeg &> /dev/null; then
  echo "ffmpeg is not installed or not found in PATH."
  exit 1
fi

# Create an empty array
songs=()

# Read the file and populate the array
while IFS= read -r line; do
  [ -n "$line" ] && songs+=("$line")
done < "$filename"

cd "$dirname"

# Update yt-dlp once up front rather than on every iteration. bilibili's
# anti-bot checks change often, so an old yt-dlp is a common cause of
# HTTP 412 errors on search. Skip quietly if we don't own the install path
# (e.g. installed to /usr/local/bin by root) instead of spamming a warning.
ytdlp_path=$(command -v yt-dlp)
if [ -w "$ytdlp_path" ] || [ -w "$(dirname "$ytdlp_path")" ]; then
  yt-dlp --no-check-certificate -U
else
  echo "Skipping yt-dlp self-update (no write permission to $ytdlp_path)."
  echo "Run 'sudo yt-dlp -U' occasionally, especially if downloads start failing with HTTP 412."
fi

# Auth for bilibili's search/risk-control checks (needed for bilisearch --
# bilibili's search API 412s on anonymous requests regardless of yt-dlp
# version). Export cookies while logged into bilibili.com in your browser
# (e.g. via the "Get cookies.txt LOCALLY" extension) and point to the file:
#   BILI_COOKIES_FILE=/path/to/bilibili_cookies.txt
# On WSL, a file saved by your Windows browser is under /mnt/c/Users/<you>/...
#
# Alternative if you'd rather point at a browser profile directly (only
# works when that browser's profile lives on this same filesystem, e.g.
# native Linux/macOS -- not a Windows browser accessed from inside WSL):
#   BILI_COOKIES_BROWSER=firefox
cookie_args=()
if [ -n "$BILI_COOKIES_FILE" ]; then
  if [ -f "$BILI_COOKIES_FILE" ]; then
    cookie_args=(--cookies "$BILI_COOKIES_FILE")
  else
    echo "BILI_COOKIES_FILE is set to '$BILI_COOKIES_FILE' but that file doesn't exist -- proceeding without cookies."
  fi
elif [ -n "$BILI_COOKIES_BROWSER" ]; then
  cookie_args=(--cookies-from-browser "$BILI_COOKIES_BROWSER")
fi

# Loop through each URL / search term
for term in "${songs[@]}"; do
  if [[ "$term" == http* ]]; then
    query="$term"
  else
    query="bilisearch1:$term"
  fi

  yt-dlp --no-check-certificate \
    --no-playlist \
    "${cookie_args[@]}" \
    -f "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best" \
    --merge-output-format mp4 \
    -o "%(title)s.%(ext)s" \
    -v "$query"

  if [ $? -ne 0 ]; then
    echo "Failed to download $term"
    echo "  If this was HTTP 412: update yt-dlp (sudo yt-dlp -U), set BILI_COOKIES_FILE," \
         "or paste a direct bilibili video URL instead of a search term."
  else
    echo "Successfully downloaded $term"
  fi
done

# Convert every downloaded video file to mp3
count=0
converted=0
video_files=($dirname/*.(mp4|mkv|webm|flv)(N))
if [ ${#video_files} -gt 0 ]; then
  for file in "${video_files[@]}"; do
    count=$((count + 1))
    base_name="${file%.*}"
    mp3_file="${base_name}.mp3"
    if [ ! -f "$mp3_file" ]; then
      ffmpeg -i "$file" -vn -ab 192k -y "$mp3_file" -loglevel warning
      converted=$((converted + 1))
      echo "Converted $file to $mp3_file"
    else
      echo "Skipped $file (mp3 already exists)"
    fi
  done
fi

echo "----------------------"
echo "${converted} in ${count} files converted."

# Delete the leftover video files, only mp3s should remain
target_files=($dirname/*.(mp4|mkv|webm|flv)(N))
if [ ${#target_files} -gt 0 ]; then
  for file in "${target_files[@]}"; do
    rm "$file"
    echo "Deleted $file"
  done
fi

# Clean up the temp file created for -s "single song" mode
if [ "$cleanup_temp" -eq 1 ]; then
  rm -f "$filename"
fi
