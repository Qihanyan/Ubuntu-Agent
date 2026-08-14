import sys
from tools.rename import RenameFileTool
from tools.organize import OrganizeFolderTool

def main():
    if len(sys.argv) < 2:
        print("用法:")
        print("  python manual_run.py rename [目标文件夹，默认/home/storage/music_repo]")
        print("  python manual_run.py organize [源文件夹] [目标文件夹]")
        return

    action = sys.argv[1]

    if action == "rename":
        target_dir = sys.argv[2] if len(sys.argv) > 2 else "/home/storage/music_repo"
        result = RenameFileTool()._run(target_dir=target_dir)
        print(result)

    elif action == "organize":
        source_dir = sys.argv[2] if len(sys.argv) > 2 else "/home/storage/music"
        target_dir = sys.argv[3] if len(sys.argv) > 3 else "/home/storage/music_repo"
        result = OrganizeFolderTool()._run(source_dir=source_dir, target_dir=target_dir)
        print(result)

    else:
        print(f"未知操作: {action}")

if __name__ == "__main__":
    main()