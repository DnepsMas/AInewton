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
from openai import AsyncOpenAI  # 🔥 使用 OpenAI SDK

# --- 保留 Memos 用于记忆 ---
from memos.api.client import MemOSClient

# ================= 配置区 =================
OPENAI_API_KEY = "yourapi"
OPENAI_BASE_URL = "your_url"
OPENAI_MODEL = "your_model"
MEMOS_API_KEY = "yourapi"
DB_FILE = "users.db"

# 初始化 OpenAI Client
openai_client = AsyncOpenAI(
    api_key=OPENAI_API_KEY,
    base_url=OPENAI_BASE_URL,
    default_headers={"x-foo": "true"}
)

# 初始化 Memos
try:
    mem_client = MemOSClient(api_key=MEMOS_API_KEY)
    print("✅ MemOS Client Connected")
except:
    mem_client = None


# ================= 数据库 =================
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        '''CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password_hash TEXT, memos_user_id TEXT, current_conv_id TEXT)''')
    # 新增对话历史表
    c.execute(
        '''CREATE TABLE IF NOT EXISTS chat_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT,
            role TEXT,
            content TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )''')
    conn.commit()
    conn.close()


def get_user(username):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE username=?", (username,))
    user = c.fetchone()
    conn.close()
    return user


def create_user(username, password):
    if get_user(username): return False
    memos_uid = f"user_{username}_{str(uuid.uuid4())[:8]}"
    pwd_hash = hashlib.sha256(password.encode()).hexdigest()
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT INTO users VALUES (?, ?, ?, ?)", (username, pwd_hash, memos_uid, "conv_default"))
    conn.commit()
    conn.close()
    return True


def verify_user(username, password):
    user = get_user(username)
    if not user: return False
    return user[1] == hashlib.sha256(password.encode()).hexdigest()


# 对话历史管理函数
def get_chat_history(username, limit=10):
    """获取用户最近的对话历史"""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        "SELECT role, content FROM chat_history WHERE username=? ORDER BY id DESC LIMIT ?",
        (username, limit)
    )
    rows = c.fetchall()
    conn.close()
    # 反转顺序（从旧到新）
    return [{"role": role, "content": content} for role, content in reversed(rows)]


# MemOS 数据解析函数
def parse_memos_result(memos_result: dict) -> dict:
    """解析 MemOS 返回的结果，提取关键信息"""
    parsed = {
        "memories": [],
        "preferences": [],
        "summary": ""
    }
    
    # 提取记忆列表
    if "memory_detail_list" in memos_result:
        for mem in memos_result["memory_detail_list"]:
            parsed["memories"].append({
                "key": mem.get("memory_key", ""),
                "value": mem.get("memory_value", ""),
                "tags": mem.get("tags", []),
                "relativity": mem.get("relativity", 0)
            })
    
    # 提取偏好列表
    if "preference_detail_list" in memos_result:
        for pref in memos_result["preference_detail_list"]:
            parsed["preferences"].append({
                "preference": pref.get("preference", ""),
                "reasoning": pref.get("reasoning", "")
            })
    
    # 生成简洁摘要（给AI看的）
    memory_texts = []
    if parsed["memories"]:
        # 取前5条最相关的记忆
        top_memories = sorted(parsed["memories"], key=lambda x: x["relativity"], reverse=True)[:5]
        for m in top_memories:
            # 提取memory_value的主要内容
            value = m['value'][:200] if len(m['value']) > 200 else m['value']
            memory_texts.append(f"• {m['key']}: {value}")
    
    pref_texts = []
    if parsed["preferences"]:
        # 取前3条偏好
        for p in parsed["preferences"][:3]:
            pref_texts.append(f"• {p['preference'][:100]}")
    
    summary_parts = []
    if memory_texts:
        summary_parts.append("【历史记忆】\n" + "\n".join(memory_texts))
    if pref_texts:
        summary_parts.append("【用户偏好】\n" + "\n".join(pref_texts))
    
    parsed["summary"] = "\n\n".join(summary_parts) if summary_parts else ""
    
    return parsed


def save_chat_message(username, role, content):
    """保存单条对话消息"""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        "INSERT INTO chat_history (username, role, content) VALUES (?, ?, ?)",
        (username, role, content)
    )
    conn.commit()
    conn.close()


def clear_chat_history(username):
    """清除用户的对话历史"""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("DELETE FROM chat_history WHERE username=?", (username,))
    conn.commit()
    conn.close()


# ================= FastAPI =================
app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"],
                   allow_headers=["*"])


class AuthRequest(BaseModel):
    username: str
    password: str


class ChatRequest(BaseModel):
    message: str
    userId: str


class GreetRequest(BaseModel):
    userId: str


class ClearHistoryRequest(BaseModel):
    userId: str


@app.post("/api/register")
async def register(req: AuthRequest):
    return {"success": True, "message": "Account created"} if create_user(req.username, req.password) else {
        "success": False, "message": "Username exists"}


@app.post("/api/login")
async def login(req: AuthRequest):
    return {"success": True, "message": "Login successful"} if verify_user(req.username, req.password) else {
        "success": False, "message": "Invalid credentials"}


# === 问候接口 (OpenAI SDK + MemOS 记忆检索) ===
@app.post("/api/greet")
async def greet_endpoint(req: GreetRequest):
    user = get_user(req.userId)
    if not user: raise HTTPException(401, "User not found")
    
    memos_uid, conv_id = user[2], user[3]
    
    # 🔥 从 MemOS 检索用户记忆
    memory_context = ""
    if mem_client:
        try:
            print(f"🧠 检索 {req.userId} 的记忆...")
            # 检索与用户特征相关的记忆
            res = mem_client.search_memory(
                query="用户的学习历史、数学水平、性格特点、过往对话",
                user_id=memos_uid,
                conversation_id=conv_id
            )
            
            # 解析记忆
            parsed = parse_memos_result(res)
            if parsed["summary"]:
                memory_context = f"\n\n{parsed['summary']}"
                print(f"✅ 检索到 {len(parsed['memories'])} 条记忆, {len(parsed['preferences'])} 条偏好")
        except Exception as e:
            print(f"⚠️ Greet记忆检索失败: {e}")
    
    # 简化提示词
    if memory_context:
        prompt_text = f"用户{req.userId}登录了。你对他的记忆：{memory_context}。请用严谨、古典的牛顿语气写一句简短问候（50字内）。"
    else:
        prompt_text = f"用户{req.userId}登录了。请用严谨、古典的牛顿语气写一句简短问候（50字内）。"
    
    greeting = "欢迎回到自然哲学的殿堂。"
    try:
        # 🔥 使用 OpenAI SDK 生成个性化问候
        completion = await openai_client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{"role": "user", "content": prompt_text}]
        )
        greeting = completion.choices[0].message.content
        print(f"💬 生成问候: {greeting[:50]}...")
    except Exception as e:
        print(f"❌ Greeting生成失败: {e}")

    return {"greeting": greeting}


# === 对话接口 (OpenAI SDK 流式实现 + 多轮对话 + MemOS深度集成) ===
@app.post("/chat")
async def chat_endpoint(req: ChatRequest):
    user = get_user(req.userId)
    if not user: raise HTTPException(401, "User not found")
    memos_uid, conv_id = user[2], user[3]

    # 获取短期对话历史（最近10轮）
    history = get_chat_history(req.userId, limit=20)  # 20条=10轮对话
    
    # 🔥 检索长期记忆（MemOS）
    memory_context = ""
    if mem_client:
        try:
            print(f"🔍 MemOS检索中: {req.message[:50]}...")
            res = mem_client.search_memory(
                query=req.message, 
                user_id=memos_uid, 
                conversation_id=conv_id
            )
            
            # 使用专门的解析函数
            parsed = parse_memos_result(res)
            if parsed["summary"]:
                memory_context = parsed["summary"]
                print(f"✅ 检索到 {len(parsed['memories'])} 条记忆, {len(parsed['preferences'])} 条偏好")
            else:
                print(f"ℹ️ 未检索到相关记忆")
        except Exception as e:
            print(f"⚠️ MemOS检索失败: {e}")

    # B. 构造 Prompt
    system_instruction = """
    【角色设定】你是艾萨克·牛顿爵士。
    【行为准则】
    1. 利用【记忆片段】回答，不要暴露你是读数据库。
    2. 数学公式必须使用 LaTeX 格式 (如 $$ x^2 $$)，行内公式用 $...$。
    3. 性格严谨、古典、傲慢。
    4. 如果没有要求,请说中文
    """
    
    # 构造系统消息
    if memory_context:
        system_message = f"【系统指令】{system_instruction}\n【记忆】{memory_context}\n【问题】{req.message}"
    else:
        system_message = f"【系统指令】{system_instruction}\n【问题】{req.message}"
    
    # 构建完整的消息列表
    messages = [{"role": "system", "content": system_message}]
    messages.extend(history)  # 短期历史
    messages.append({"role": "user", "content": req.message})  # 当前问题
    
    print(f"💬 短期历史: {len(history)//2}轮 | 长期记忆: {'有' if memory_context else '无'} | 总消息: {len(messages)}")

    async def response_generator():
        full_text = ""
        try:
            print(f"⚡ DEBUG: 使用 OpenAI SDK 流式调用 (多轮对话)...")
            
            # 🔥 使用 OpenAI SDK 流式调用，传递完整的消息历史
            stream = await openai_client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=messages,
                stream=True
            )

            # 流式输出
            async for chunk in stream:
                if chunk.choices and len(chunk.choices) > 0:
                    if chunk.choices[0].delta.content:
                        content = chunk.choices[0].delta.content
                        full_text += content
                        yield content  # 🔥 直接吐出字符

            # 保存本轮对话到数据库
            if full_text:
                await asyncio.to_thread(save_chat_message, req.userId, "user", req.message)
                await asyncio.to_thread(save_chat_message, req.userId, "assistant", full_text)
                print(f"💾 对话已保存到数据库")
            
            # 存储到 Memos（如果可用）
            if mem_client and full_text:
                msgs = [{"role": "user", "content": req.message}, {"role": "assistant", "content": full_text}]
                await asyncio.to_thread(mem_client.add_message, messages=msgs, user_id=memos_uid,
                                        conversation_id=conv_id)
                print(f"💾 Memory saved to Memos.")

        except Exception as e:
            print(f"❌ Error: {e}")
            import traceback
            traceback.print_exc()
            yield f"\n[Network Error: {str(e)}]"

    return StreamingResponse(response_generator(), media_type="text/plain")


# === 清除对话历史接口 ===
@app.post("/api/clear-history")
async def clear_history_endpoint(req: ClearHistoryRequest):
    user = get_user(req.userId)
    if not user: raise HTTPException(401, "User not found")
    
    try:
        clear_chat_history(req.userId)
        print(f"🗑️ 已清除用户 {req.userId} 的对话历史")
        return {"success": True, "message": "对话历史已清除"}
    except Exception as e:
        print(f"❌ 清除历史失败: {e}")
        return {"success": False, "message": f"清除失败: {str(e)}"}


if __name__ == "__main__":
    init_db()
    print("🚀 Newton Server (OpenAI SDK Mode) starting...")
    uvicorn.run(app, host="0.0.0.0", port=5050)
