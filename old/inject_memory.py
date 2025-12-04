import time
from memos.api.client import MemOSClient

# ==========================================
# 1. 配置区
# ==========================================
# 你的 MemOS Key (mpg-xxx)
MEMOS_API_KEY = ""

# ⚠️ 必须和主程序的 USER_ID 一致！否则Agent读取不到
TARGET_USER_ID = ""
CONV_ID = "history_injection_01"  # 专门起个对话ID，方便管理

# 初始化客户端
client = MemOSClient(api_key=MEMOS_API_KEY)


def inject_bio():
    # 2. 读取文本文件
    try:
        with open("newton_bio.txt", "r", encoding="utf-8") as f:
            lines = f.readlines()
    except FileNotFoundError:
        print("❌ 找不到 newton_bio.txt，请先创建这个文件！")
        return

    print(f"🚀 开始灌注记忆，共 {len(lines)} 条知识点...")

    # 3. 循环写入
    for i, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue  # 跳过空行

        print(f"[{i + 1}/{len(lines)}] 正在写入: {line[:20]}...")

        try:
            # 我们模拟“上帝”告诉牛顿这些事实
            # MemOS 会把这些存储为长期记忆
            messages = [
                {"role": "user", "content": f"请记住关于你自己的这段历史：{line}"},
                {"role": "assistant", "content": "吾已铭记于心。"}  # 模拟牛顿确认接收
            ]

            # 调用 API 写入
            client.add_message(
                messages=messages,
                user_id=TARGET_USER_ID,
                conversation_id=CONV_ID
            )

            # 稍微停顿一下，防止 API 超频
            time.sleep(1)

        except Exception as e:
            print(f"❌ 写入失败: {e}")

    print("\n✅ 记忆灌注完成！现在你的 Agent 拥有牛顿的生平记忆了。")


if __name__ == "__main__":
    inject_bio()