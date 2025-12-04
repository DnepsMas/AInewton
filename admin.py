import streamlit as st
import sqlite3
import pandas as pd
import os

# ================= 配置 =================
DB_FILE = "users.db"
st.set_page_config(page_title="Newton Admin Panel", page_icon="🛡️", layout="wide")

# ================= CSS 美化 =================
st.markdown("""
<style>
    .stApp { background-color: #0e1117; color: #fff; }
    .stDataFrame { border: 1px solid #333; }
</style>
""", unsafe_allow_html=True)


# ================= 数据库函数 =================
def load_data():
    """读取所有用户数据"""
    if not os.path.exists(DB_FILE):
        return pd.DataFrame()

    conn = sqlite3.connect(DB_FILE)
    try:
        # 读取数据到 Pandas DataFrame，方便展示
        df = pd.read_sql_query("SELECT * FROM users", conn)
    except Exception as e:
        st.error(f"数据库读取错误: {e}")
        df = pd.DataFrame()
    finally:
        conn.close()
    return df


def delete_user_by_name(username):
    """根据用户名删除记录"""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    try:
        c.execute("DELETE FROM users WHERE username=?", (username,))
        conn.commit()
        return True
    except Exception as e:
        st.error(f"删除失败: {e}")
        return False
    finally:
        conn.close()


# ================= 界面逻辑 =================
st.title("🛡️ Newton 用户数据库管理 (Localhost)")
st.caption("仅限管理员在服务器本地操作 • `users.db`")

st.divider()

# 1. 刷新数据
if st.button("🔄 刷新列表"):
    st.rerun()

df = load_data()

# 2. 展示数据表格
if not df.empty:
    st.subheader(f"当前用户总数: {len(df)}")

    # 隐藏过长的哈希显示，或者直接展示
    # 这里我们完整展示，并在 Streamlit 原生表格里支持搜索/排序
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "username": "用户名 (User ID)",
            "password_hash": "密码哈希 (SHA256)",
            "memos_user_id": "Memos 内部 ID",
            "current_conv_id": "当前会话 ID"
        }
    )

    st.divider()

    # 3. 删除用户区域 (危险操作)
    st.subheader("🧨 危险操作区")

    col1, col2 = st.columns([3, 1])

    with col1:
        # 下拉选择要删除的用户
        user_to_delete = st.selectbox(
            "选择要删除的用户:",
            options=df["username"].tolist(),
            index=None,
            placeholder="请选择..."
        )

    with col2:
        st.write("")  # 占位对齐
        st.write("")
        if st.button("🗑️ 确认删除用户", type="primary", use_container_width=True):
            if user_to_delete:
                if delete_user_by_name(user_to_delete):
                    st.success(f"用户 [{user_to_delete}] 已从数据库移除！")
                    import time

                    time.sleep(1)
                    st.rerun()
            else:
                st.warning("请先选择一个用户。")

else:
    st.info("数据库为空或文件不存在 (users.db)。")