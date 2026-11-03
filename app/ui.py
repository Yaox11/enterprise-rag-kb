"""Streamlit 界面：聊天式问答，保留完整对话历史。"""
import os

import requests
import streamlit as st

# 允许用环境变量覆盖，方便部署到别的机器
DEFAULT_API = os.getenv("API_URL", "http://127.0.0.1:8000")

st.set_page_config(page_title="企业知识库问答", page_icon="📚", layout="centered")
st.title("📚 企业知识库智能问答")
st.caption("混合检索 + Cross-Encoder 重排 + 带引用生成")

# 对话历史：每条消息 {role, content, meta?, citations?}
# session_state 跨 rerun 存活，所以往上翻能看到之前每一轮
if "messages" not in st.session_state:
    st.session_state.messages = []


def render_message(msg):
    """统一样式渲染一条消息，历史消息和新消息都走这里。"""
    with st.chat_message(msg["role"]):
        if msg.get("refused"):
            st.warning(f'未找到足够相关的资料（最高相关度 {msg.get("top_score") or 0:.3f}）')
        st.markdown(msg["content"])
        if msg.get("meta"):
            st.caption(msg["meta"])
        if msg.get("citations"):
            with st.expander("引用来源"):
                for c in msg["citations"]:
                    st.markdown(f'**[{c["id"]}] {c["source"]}** · 相关度 {c["score"]:.3f}')
                    st.text(c["snippet"])


with st.sidebar:
    st.header("设置")
    api_url = st.text_input("API 地址", DEFAULT_API)
    api_token = st.text_input("API Token（可选）", type="password")
    top_k = st.slider("引用片段数", min_value=1, max_value=5, value=3)
    dept = st.selectbox("部门", ["全员", "研发", "产品", "财务"])
    clearance = st.selectbox(
        "密级",
        [0, 1, 2],
        index=1,
        format_func=lambda x: {0: "公开", 1: "内部", 2: "机密"}[x],
    )
    st.divider()

    # 探测后端是否就绪；模型首次加载要十几秒，所以给 3 秒超时即可
    try:
        h = requests.get(f"{api_url}/health", timeout=3).json()
        st.success(f'服务正常 · {h["documents"]} 个文档 / {h["chunks"]} 个片段')
        st.caption(f'索引时间：{h["index_built_at"]}')
        st.caption(f'拒答阈值：{h.get("refusal_threshold", 0):.2f}')
        if not h.get("llm_ready", True):
            st.warning("未配置 LLM_API_KEY，只能检索不能生成")
    except Exception:
        st.error("API 未启动")

    # 改完 corpus 里的文档后点这里，服务不用重启
    if st.button("更新所有文档", use_container_width=True):
        try:
            with st.spinner("重建索引中..."):
                res = requests.post(f"{api_url}/reindex", timeout=180).json()
            st.success(f'已重建：{res["documents"]} 个文档 / {res["chunks"]} 个片段')
            st.caption(f'索引时间：{res["index_built_at"]}')
        except Exception as exc:
            st.error(f"重建失败：{exc}")

    # 只重算改过的文件，速度和成本都比全量重建低
    if st.button("增量更新", use_container_width=True):
        try:
            with st.spinner("检查变更中..."):
                res = requests.post(f"{api_url}/refresh", timeout=180).json()
            if res.get("unchanged"):
                st.info(f'没有变化，共 {res["chunks"]} 个片段')
            else:
                st.success(f'新增 {len(res["added"])} / 修改 {len(res["changed"])} / 删除 {len(res["deleted"])}')
                st.caption(f'现有 {res["documents"]} 个文档 / {res["chunks"]} 个片段')
        except Exception as exc:
            st.error(f"更新失败：{exc}")

    st.divider()
    # 清空历史只影响界面，不影响后端索引
    if st.button("清空对话", use_container_width=True):
        st.session_state.messages = []
        st.rerun()

# 先渲染历史，保证任何 rerun 之后聊天记录都还在
for m in st.session_state.messages:
    render_message(m)

# chat_input 固定在页面底部，回车即发送；发送后输入框清空是聊天界面的标准行为
prompt = st.chat_input("输入问题，回车发送")
if prompt:
    # 1) 先把用户问题记进历史并显示
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # 2) 请求后端，结果也以消息形式追加
    with st.chat_message("assistant"):
        with st.spinner("检索并生成中..."):
            try:
                resp = requests.post(
                    f"{api_url}/ask",
                    json={"question": prompt, "top_k": top_k,
                          "dept": dept, "clearance": clearance},
                    headers={"X-API-Token": api_token} if api_token else {},
                    timeout=120,
                )
                resp.raise_for_status()
                data = resp.json()
            except Exception as exc:
                st.error(f"请求失败：{exc}")
                st.stop()

        tag = "（缓存命中）" if data.get("cached") else ""
        meta = f'耗时 {data["latency_ms"]} ms · {data["model"]} {tag}'

        # 阈值拒答：检索分数不够，后端直接短路，没有调用模型
        if data.get("refused"):
            st.warning(f'未找到足够相关的资料（最高相关度 {data["top_score"]:.3f}）')
        st.markdown(data["answer"])
        st.caption(meta)
        with st.expander("引用来源"):
            for c in data["citations"]:
                st.markdown(f'**[{c["id"]}] {c["source"]}** · 相关度 {c["score"]:.3f}')
                st.text(c["snippet"])

    # 3) 落库到 session_state，下一轮渲染历史时复用
    st.session_state.messages.append({
        "role": "assistant",
        "content": data["answer"],
        "meta": meta,
        "citations": data["citations"],
        "refused": data.get("refused", False),
        "top_score": data.get("top_score"),
    })

