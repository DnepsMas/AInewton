import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import sqlite3
import hashlib
import uuid
import os
import json
import asyncio

# --- AI & Memos 库 ---
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
from memos.api.client import MemOSClient

# ================= 配置区 =================
# ⚠️ 请确保 Key 和端口与你之前提供的一致
GEMINI_API_KEY = ""
MEMOS_API_KEY = ""
PROXY_PORT = ""
DB_FILE = "users.db"

# 配置网络代理 (解决国内连接 Gemini 问题)
os.environ["HTTP_PROXY"] = f"http://127.0.0.1:{PROXY_PORT}"
os.environ["HTTPS_PROXY"] = f"http://127.0.0.1:{PROXY_PORT}"

# 初始化 AI 客户端
genai.configure(api_key=GEMINI_API_KEY, transport='rest')

# 初始化 Memos 客户端
try:
    mem_client = MemOSClient(api_key=MEMOS_API_KEY)
    print("✅ MemOS Client Connected")
except Exception as e:
    mem_client = None
    print(f"❌ MemOS Connection Failed: {e}")


# ================= 数据库逻辑 (SQLite) =================
def init_db():
    """初始化数据库，建表"""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (username TEXT PRIMARY KEY, 
                  password_hash TEXT, 
                  memos_user_id TEXT,
                  current_conv_id TEXT)''')
    conn.commit()
    conn.close()


def get_user(username):
    """查询用户信息"""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE username=?", (username,))
    user = c.fetchone()
    conn.close()
    return user


def create_user(username, password):
    """创建新用户"""
    if get_user(username):
        return False

    # 自动生成该用户专属的 Memos ID (实现记忆隔离)
    memos_uid = f"user_{username}_{str(uuid.uuid4())[:8]}"
    default_conv_id = "conv_default"

    # 密码哈希处理
    pwd_hash = hashlib.sha256(password.encode()).hexdigest()

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT INTO users VALUES (?, ?, ?, ?)",
              (username, pwd_hash, memos_uid, default_conv_id))
    conn.commit()
    conn.close()
    return True


def verify_user(username, password):
    """验证登录"""
    user = get_user(username)
    if not user: return False
    pwd_hash = hashlib.sha256(password.encode()).hexdigest()
    return user[1] == pwd_hash


# ================= FastAPI 应用定义 =================
app = FastAPI()

# 跨域设置 (允许 index.html 访问)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- 数据模型 ---
class AuthRequest(BaseModel):
    username: str
    password: str


class ChatRequest(BaseModel):
    message: str
    userId: str


class GreetRequest(BaseModel):
    userId: str


# ================= 接口路由 =================

# 1. 注册
@app.post("/api/register")
async def register(req: AuthRequest):
    if create_user(req.username, req.password):
        return {"success": True, "message": "Account created"}
    return {"success": False, "message": "Username already exists"}


# 2. 登录
@app.post("/api/login")
async def login(req: AuthRequest):
    if verify_user(req.username, req.password):
        return {"success": True, "message": "Login successful"}
    return {"success": False, "message": "Invalid credentials"}


# 3. 个性化问候 (NEW!)
@app.post("/api/greet")
async def greet_endpoint(req: GreetRequest):
    user_data = get_user(req.userId)
    if not user_data:
        raise HTTPException(status_code=401, detail="User not found")

    memos_user_id = user_data[2]
    current_conv_id = user_data[3]

    # 尝试检索用户画像
    retrieved_memory = ""
    if mem_client:
        try:
            # 搜索宽泛的关键词，试图获取用户背景
            res = mem_client.search_memory(
                query="User profile interests name background",
                user_id=memos_user_id,
                conversation_id=current_conv_id
            )
            retrieved_memory = str(res)
        except Exception:
            pass

    # 生成欢迎语
    system_instruction = """
    【角色】艾萨克·牛顿爵士 (Sir Isaac Newton)
    【任务】根据记忆片段生成一句简短的欢迎语。
    【要求】
    1. 若有用户名字或兴趣，请在问候中提及。
    2. 若无记忆，则用严谨、略带傲慢的语气欢迎新学生。
    3. 限制在50字以内。
    4. 如果没有要求,请说中文
    """

    prompt = f"【记忆】{retrieved_memory}\n【用户ID】{req.userId}\n请生成欢迎语："

    greeting = "欢迎回到自然哲学的殿堂。"  # 兜底默认值
    try:
        model = genai.GenerativeModel("models/gemini-2.5-flash", system_instruction=system_instruction)
        response = model.generate_content(prompt)
        if response.text:
            greeting = response.text
    except Exception as e:
        print(f"Greeting Error: {e}")

    return {"greeting": greeting}


# 4. 核心对话 (RAG + Stream)
@app.post("/chat")
async def chat_endpoint(req: ChatRequest):
    user_data = get_user(req.userId)
    if not user_data:
        raise HTTPException(status_code=401, detail="User not found")

    memos_user_id = user_data[2]
    current_conv_id = user_data[3]
    user_msg = req.message

    # A. 检索记忆 (Recall)
    retrieved_memory = ""
    if mem_client:
        try:
            print(f"🔍 Searching memories for: {req.userId}")
            res = mem_client.search_memory(
                query=user_msg,
                user_id=memos_user_id,
                conversation_id=current_conv_id
            )
            retrieved_memory = str(res)
        except Exception as e:
            print(f"Memory Search Error: {e}")

    # B. 构造 Prompt
    system_instruction = """
    【角色设定】你是艾萨克·牛顿爵士。
    【行为准则】
    1. 利用【记忆片段】回答，不要暴露你是读数据库。
    2. 数学公式必须使用 LaTeX 格式 (如 $$ x^2 $$)，行内公式用 $...$。
    3. 性格严谨、古典、傲慢。
    4. 如果没有要求,请说中文
    """

    final_prompt = f"【记忆片段】\n{retrieved_memory}\n\n【用户问题】\n{user_msg}"

    # C. 生成器函数
    async def response_generator():
        model = genai.GenerativeModel("models/gemini-2.5-flash", system_instruction=system_instruction)

        # 安全设置 (防止拒答)
        safety_settings = {
            HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
        }

        full_response_text = ""
        try:
            response = model.generate_content(final_prompt, stream=True, safety_settings=safety_settings)

            for chunk in response:
                if chunk.text:
                    full_response_text += chunk.text
                    yield chunk.text

            # D. 存储记忆 (Store)
            if mem_client and full_response_text:
                try:
                    msgs = [
                        {"role": "user", "content": user_msg},
                        {"role": "assistant", "content": full_response_text}
                    ]
                    mem_client.add_message(
                        messages=msgs,
                        user_id=memos_user_id,
                        conversation_id=current_conv_id
                    )
                    print(f"💾 Memory saved for {req.userId}")
                except Exception as e:
                    print(f"Save Memory Error: {e}")

        except Exception as e:
            yield f"\n[System Error: {str(e)}]"

    return StreamingResponse(response_generator(), media_type="text/plain")


if __name__ == "__main__":
    init_db()
    print("🚀 Newton Server running on port 5050...")
    uvicorn.run(app, host="0.0.0.0", port=5050)