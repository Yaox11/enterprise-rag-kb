"""服务层：把「检索 → 重排 → 生成 → 引用」封装成一个可复用的类。

几个工程上的取舍，面试里常被追问：
1. 模型加载要十几秒，所以整个进程只初始化一次，绝不在每次请求里新建；
2. LLM 调用可能超时或被限流，所以设了超时 + 重试；
3. 相同问题走缓存，既省 token 也降延迟；
4. 返回结构固定（answer + citations + latency），接口层不关心检索细节。
"""
import logging
import os
import sys
import time
from collections import OrderedDict

from openai import OpenAI

# app/ 的上一级才是 rag_core.py 所在目录，手动加进 sys.path
APP_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(APP_DIR)
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from rag_core import KnowledgeBase, build_prompt, load_dotenv

logger = logging.getLogger("rag.service")

# 缓存上限。真实系统里会换成 Redis，并带 TTL。
CACHE_SIZE = 100


class RagService:
    """一个进程内共享的 RAG 服务实例。"""

    def __init__(self):
        load_dotenv()  # 读取 .env 里的 LLM_API_KEY 等配置
        self.api_key = (os.getenv("LLM_API_KEY") or "").strip()
        self.base_url = os.getenv("LLM_BASE_URL", "https://api.deepseek.com")
        self.model = os.getenv("LLM_MODEL", "deepseek-chat")
        # 重排分低于这个值就直接拒答，不调模型。
        # 按当前语料实测标定：无答案题最高 0.096，有答案题最低 0.321。
        # 取两者中点附近 0.2，比贴着 0.3 有更大的安全余量。
        self.refusal_threshold = float(os.getenv("REFUSAL_THRESHOLD", "0.2"))
        # 可选鉴权：AUTH_TOKENS="token1:研发:2,token2:财务:2"
        # 配置后，身份以 token 为准，忽略请求体里的 dept/clearance。
        self.tokens = {}
        for part in (os.getenv("AUTH_TOKENS") or "").split(","):
            bits = part.split(":")
            if len(bits) == 3:
                self.tokens[bits[0].strip()] = (bits[1].strip(), int(bits[2]))

        logger.info("加载 embedding 与 rerank 模型...")
        self.kb = KnowledgeBase()
        logger.info("模型加载完成，共 %d 个片段", len(self.kb.chunks))

        # 没有 key 时也允许启动，/ask 会返回明确的 503，而不是启动就崩
        self.client = None
        if self.api_key:
            # timeout 必设：否则上游卡住会拖死整个接口
            self.client = OpenAI(api_key=self.api_key, base_url=self.base_url,
                                 timeout=30.0, max_retries=0)

        self._cache = OrderedDict()

    def resolve_token(self, token):
        """把 token 映射成 (部门, 密级)；未配置鉴权或 token 无效时返回 None。"""
        return self.tokens.get((token or "").strip())

    def _chat(self, prompt: str) -> str:
        """调用 LLM，失败重试一次。"""
        if self.client is None:
            raise RuntimeError("未配置 LLM_API_KEY，请检查 outputs/rag-kb-agent/.env")
        last_err = None
        for attempt in range(2):
            try:
                resp = self.client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.2,
                )
                return resp.choices[0].message.content.strip()
            except Exception as exc:  # 网络抖动、限流、超时都走这里
                last_err = exc
                logger.warning("LLM 调用失败（第 %d 次）：%s", attempt + 1, exc)
                time.sleep(1.0)
        raise RuntimeError(f"LLM 调用失败：{last_err}")

    def answer(self, question: str, top_k: int = 3, dept: str = None, clearance: int = None) -> dict:
        """完整链路：检索 → 重排 → 拼 Prompt → 生成 → 组装引用。"""
        question = question.strip()
        # 缓存键必须带上权限，否则不同部门会拿到同一份答案，等于越权
        key = (question, top_k, dept, clearance)
        t0 = time.perf_counter()

        if key in self._cache:
            self._cache.move_to_end(key)  # LRU：命中就挪到队尾
            hit = dict(self._cache[key])
            hit["cached"] = True
            # 缓存命中要报本次真实耗时（接近 0），而不是首次的耗时
            hit["latency_ms"] = int((time.perf_counter() - t0) * 1000)
            return hit

        # 1) 检索 + 重排（KnowledgeBase.retrieve 内部已完成混合召回与精排）
        hits = self.kb.retrieve(question, k=top_k, dept=dept, clearance=clearance)

        # 1.5) 置信度门控：最高重排分不够就短路拒答，省一次 LLM 调用
        top_score = float(hits[0][3]) if hits else 0.0
        if top_score < self.refusal_threshold:
            refused = {
                "answer": "根据现有资料无法回答。",
                "citations": [],  # 候选片段相关度太低，列出来反而误导
                "latency_ms": int((time.perf_counter() - t0) * 1000),
                "model": self.model,
                "cached": False,
                "refused": True,
                "top_score": round(top_score, 4),
            }
            self._cache[key] = refused
            if len(self._cache) > CACHE_SIZE:
                self._cache.popitem(last=False)
            return refused

        # 2) 拼 Prompt：每个片段带编号和来源，方便模型写出 [1][2] 引用
        prompt = build_prompt(question, [(h[1], h[2]) for h in hits])

        # 3) 生成
        answer_text = self._chat(prompt)

        result = {
            "answer": answer_text,
            "citations": [
                {
                    "id": i + 1,
                    "source": h[1],
                    # 只回传前 200 字，避免响应体过大
                    "snippet": h[2][:200],
                    "score": round(float(h[3]), 4),
                }
                for i, h in enumerate(hits)
            ],
            "latency_ms": int((time.perf_counter() - t0) * 1000),
            "model": self.model,
            "cached": False,
            "refused": False,
            "top_score": round(top_score, 4),
        }

        self._cache[key] = result
        if len(self._cache) > CACHE_SIZE:
            self._cache.popitem(last=False)  # 淘汰最久未使用的
        return result

    def reindex(self) -> dict:
        """热重建索引：重新读 corpus，模型不重载，通常 2-3 秒。

        注意必须同时清空答案缓存，否则同一个问题还会返回旧索引下的回答。
        """
        chunks = self.kb.reload()
        self._cache.clear()
        documents = len({m.split("#")[0] for m in self.kb.metas})
        logger.info("索引已重建：%d 个文档 / %d 个片段", documents, chunks)
        return {"chunks": chunks, "documents": documents,
                "index_built_at": self.kb.built_at}

    def refresh(self) -> dict:
        """增量更新：只重算新增/修改的文件，删除的摘掉。"""
        result = self.kb.incremental_update()
        self._cache.clear()
        result["documents"] = len({m.split("#")[0] for m in self.kb.metas})
        result["index_built_at"] = self.kb.built_at
        return result

