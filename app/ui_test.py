"""验证聊天式界面：两轮问答后历史是否保留。"""
import os

from streamlit.testing.v1 import AppTest

UI = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui.py")
at = AppTest.from_file(UI, default_timeout=120)
at.run()

print("EXCEPTIONS:", [e.value for e in at.exception])
print("CHAT_INPUTS:", len(at.chat_input))

# 第一轮
at.chat_input[0].set_value("密码多久要换一次？").run()
print("R1 EXCEPTIONS:", [e.value for e in at.exception])
print("R1 MESSAGES:", len(at.session_state.messages))

# 第二轮：历史里应该有 4 条（问、答、问、答）
at.chat_input[0].set_value("年假有几天？").run()
print("R2 EXCEPTIONS:", [e.value for e in at.exception])
print("R2 MESSAGES:", len(at.session_state.messages))

for i, m in enumerate(at.session_state.messages):
    print(f"  [{i}] {m['role']}: {m['content'][:40]}")

