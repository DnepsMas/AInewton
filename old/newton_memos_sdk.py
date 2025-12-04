from google.generativeai.types import HarmCategory, HarmBlockThreshold
import streamlit as st
import google.generativeai as genai
import os
from memos.api.client import MemOSClient  # 导入官方 SDK

# ==========================================
# 1. 配置区 (填入你的 Key)
# ==========================================

# A. Gemini 配置
GEMINI_API_KEY = ""
PROXY_PORT = ""  # 你的梯子端口

# B. MemOS 配置 (你的新玩具)
# 去 MemTensor 后台获取以 mpg- 开头的 Key
MEMOS_API_KEY = ""

# C. 用户身份标识 (为了让 MemOS 区分是谁在说话)
USER_ID = ""
CONV_ID = "chat_session_01"

# ==========================================
# 2. 初始化环境
# ==========================================

# 配置网络代理 (给 Gemini 用)
os.environ["HTTP_PROXY"] = f"http://127.0.0.1:{PROXY_PORT}"
os.environ["HTTPS_PROXY"] = f"http://127.0.0.1:{PROXY_PORT}"

# 初始化 Gemini
genai.configure(api_key=GEMINI_API_KEY, transport='rest')

# 初始化 MemOS 客户端
# 注意：MemOS 的 SDK 会自动处理 base_url，除非你需要改
try:
    mem_client = MemOSClient(api_key=MEMOS_API_KEY)
    print("✅ MemOS 客户端连接成功")
except Exception as e:
    print(f"❌ MemOS 连接失败: {e}")
    mem_client = None


# ==========================================
# 3. 定义牛顿模型
# ==========================================
@st.cache_resource
def get_newton_model():
    system_instruction = """
    【角色设定】
    你是艾萨克·牛顿爵士 (Sir Isaac Newton)。

    【行为准则】
    1. **记忆能力**: 你拥有极其强大的记忆力。我会把相关的回忆提供给你，请在回答中自然地利用这些信息，不要让用户觉得你是在读数据库。
    2. **数学专家**: 所有数学公式必须严格使用 LaTeX 格式。
    3. **性格**: 严谨
    4. **反应**: 如果用户问你以前的事，利用【回忆】来回答。
    """
    return genai.GenerativeModel("models/gemini-2.5-flash", system_instruction=system_instruction)


model = get_newton_model()

# ==========================================
# 4. Streamlit 界面逻辑
# ==========================================
st.set_page_config(page_title="Newton x MemOS", page_icon="🍎")
st.title("🍎 艾萨克·牛顿 (MemOS 加持版)")

# 初始化聊天历史
if "messages" not in st.session_state:
    st.session_state.messages = []

# 显示历史消息
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# ==========================================
# 5. 核心交互循环 (RAG Loop)
# ==========================================
if prompt := st.chat_input("向爵士提问..."):

    # 1. 显示用户问题
    with st.chat_message("user"):
        st.markdown(prompt)
    st.session_state.messages.append({"role": "user", "content": prompt})

    # 2. MemOS 检索 (Recall)
    retrieved_memory = ""
    if mem_client:
        with st.status("🧠 海马体正在检索记忆...", expanded=True) as status:
            try:
                # 调用 SDK 搜索记忆
                res = mem_client.search_memory(
                    query=prompt,
                    user_id=USER_ID,
                    conversation_id=CONV_ID
                )
                # 解析返回结果 (SDK 返回的结构可能根据版本不同，通常直接转 string 即可调试)
                # 假设返回的是相关文本列表
                retrieved_memory = str(res)

                st.write(f"检索结果: {retrieved_memory}")
                status.update(label="记忆检索完成", state="complete", expanded=False)
            except Exception as e:
                st.error(f"记忆检索失败: {e}")

    # 3. Gemini 生成 (Think)
    with st.chat_message("assistant"):
        placeholder = st.empty()
        full_response = ""

        # 构造最终 Prompt
        final_prompt = f"""
        【提取到的记忆片段 (Memories)】
        {retrieved_memory}

        【用户的当前问题】
        {prompt}
        """

        try:
            # === 🔥 关键修改：配置安全设置，防止报错 400 ===
            safety_settings = {
                HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
            }

            # 发送给牛顿 (带上免死金牌)
            response = model.generate_content(
                final_prompt,
                stream=False,
                safety_settings=safety_settings
            )

            # 流式渲染
            for chunk in response:
                if chunk.text:
                    full_response += chunk.text
                    placeholder.markdown(full_response + "▌")

            # 渲染结束
            placeholder.markdown(full_response)

            st.session_state.messages.append({"role": "assistant", "content": full_response})

            # ... (后面是 MemOS 存储代码，不用动) ...

        except Exception as e:
            # 如果还是报错，我们打印出更详细的信息
            st.error(f"牛顿思考出错 (Error 400 通常是安全过滤导致，请检查代码是否添加了 BLOCK_NONE): {e}")

            # 4. MemOS 存储 (Store) - 关键步骤！
            # 我们把"原汁原味"的对话发给 MemOS，它会自动抽象和压缩
            if mem_client:
                try:
                    # 构造 MemOS 需要的数据格式
                    msgs_to_store = [
                        {"role": "user", "content": prompt},
                        {"role": "assistant", "content": full_response}
                    ]

                    # 异步写入，不阻塞 UI
                    mem_client.add_message(
                        messages=msgs_to_store,
                        user_id=USER_ID,
                        conversation_id=CONV_ID
                    )
                    # 这里的 print 是为了你在后台终端看到写入成功
                    print(f"✅ 已将对话写入 MemOS: {prompt[:20]}...")

                except Exception as e:
                    print(f"❌ 写入 MemOS 失败: {e}")

        except Exception as e:
            st.error(f"牛顿思考出错: {e}")