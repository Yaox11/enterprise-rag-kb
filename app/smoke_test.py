"""接口冒烟测试：健康检查 → 提问 → 再问一次验证缓存。"""
import json
import requests

BASE = "http://127.0.0.1:8000"

h = requests.get(f"{BASE}/health", timeout=10).json()
print("HEALTH:", json.dumps(h, ensure_ascii=False))

payload = {"question": "出差去上海，酒店一晚最多能报多少？", "top_k": 3}
r = requests.post(f"{BASE}/ask", json=payload, timeout=120)
print("STATUS:", r.status_code)
d = r.json()
print("ANSWER:", d["answer"])
print("LATENCY:", d["latency_ms"], "ms")
for c in d["citations"]:
    print("  CITE", c["id"], c["source"], c["score"])

r2 = requests.post(f"{BASE}/ask", json=payload, timeout=120)
print("SECOND cached:", r2.json()["cached"], "latency:", r2.json()["latency_ms"], "ms")

# 参数校验：空问题应返回 422
bad = requests.post(f"{BASE}/ask", json={"question": "", "top_k": 3}, timeout=10)
print("EMPTY QUESTION STATUS:", bad.status_code)
