"""验证热重建：同一问题在加入新文档前后，答案如何变化。"""
import json
import os
req = __import__("requests")

BASE = "http://127.0.0.1:8000"
DOC = os.path.join("corpus", "07_公司年会安排.md")
Q = "公司年会今年在哪里举办？"


def ask():
    r = req.post(f"{BASE}/ask", json={"question": Q, "top_k": 3}, timeout=120)
    d = r.json()
    return d["answer"], d.get("cached", False)


def reindex():
    r = req.post(f"{BASE}/reindex", timeout=180)
    return r.json()


# 上一次失败的测试可能留下了临时文档，先清掉，保证基线干净
if os.path.exists(DOC):
    os.remove(DOC)


print("HEALTH (before):", json.dumps(req.get(f"{BASE}/health", timeout=5).json(), ensure_ascii=False))
ans, _ = ask()
print("\n[1] 加文档前:", ans)

# 写入一篇新文档
open(DOC, "w", encoding="utf-8").write(
    "# 公司年会安排\n\n"
    "## 一、时间与地点\n"
    "2026 年公司年会定于 12 月 20 日在上海国际会议中心举办，全体员工参加。\n\n"
    "## 二、交通安排\n"
    "统一安排大巴从公司出发，下午 4 点集合。\n"
)
print("\n[2] 已写入", DOC, "，调用 /reindex")
print("   ", reindex())

ans, cached = ask()
print("\n[3] 重建后再问:", ans, "| cached =", cached)

# 清理：删掉临时文档并重建，恢复原状
os.remove(DOC)
print("\n[4] 删除临时文档并重建:", reindex())
ans, _ = ask()
print("[5] 恢复后再问:", ans)

