"""阶段 3：完整 ask() 链路 —— 检索 -> 重排 -> 拼 Prompt -> 生成 -> 带引用回答。

没有 API Key 时进入 dry-run：打印将要发送的完整 Prompt，不做生成。

配置（二选一）：
  1. 环境变量 LLM_API_KEY / LLM_BASE_URL / LLM_MODEL
  2. 同目录下的 .env 文件，内容形如
       LLM_API_KEY=sk-xxxx
       LLM_BASE_URL=https://api.deepseek.com
       LLM_MODEL=deepseek-chat

Run:  outputs/run.cmd outputs/rag-kb-agent/stage3_ask.py
"""
import glob
import os
import re

import chromadb
import jieba
import numpy as np
from rank_bm25 import BM25Okapi
from sentence_transformers import CrossEncoder, SentenceTransformer

HERE = os.path.dirname(__file__)
CORPUS_DIR = os.path.join(HERE, "corpus")
EMB_MODEL = "BAAI/bge-small-zh-v1.5"
RERANK_MODEL = "BAAI/bge-reranker-base"
CANDIDATES = 10
TOP_K = 3

PROMPT_TMPL = """你是企业知识库助手。请只依据下面的【资料】回答问题。

规则：
1. 资料里有答案就简洁回答，并在句末标注引用编号，例如 [1][2]。
2. 资料里没有答案，就回答“根据现有资料无法回答”，不要编造。
3. 不要使用资料以外的知识。

【资料】
{context}

【问题】{question}
"""


def load_dotenv():
    path = os.path.join(HERE, ".env")
    if not os.path.exists(path):
        return
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


def chunk_text(text, max_chars=320, overlap=40):
    blocks = [b.strip() for b in re.split(r"(?m)^(?=#{1,3}\s)", text.strip()) if b.strip()]
    chunks = []
    for b in blocks:
        if len(b) <= max_chars:
            chunks.append(b)
            continue
        start = 0
        while start < len(b):
            chunks.append(b[start:start + max_chars])
            if start + max_chars >= len(b):
                break
            start += max_chars - overlap
    return [c for c in chunks if len(c.strip()) > 20]


def load_corpus():
    texts, metas = [], []
    for path in sorted(glob.glob(os.path.join(CORPUS_DIR, "*.md"))):
        raw = open(path, encoding="utf-8").read()
        name = os.path.basename(path)
        for i, ch in enumerate(chunk_text(raw)):
            texts.append(ch)
            metas.append(f"{name}#{i}")
    return texts, metas


def rrf(rank_lists, k=60):
    scores = {}
    for ranking in rank_lists:
        for rank, idx in enumerate(ranking):
            scores[idx] = scores.get(idx, 0.0) + 1.0 / (k + rank + 1)
    return [i for i, _ in sorted(scores.items(), key=lambda x: -x[1])]


class KnowledgeBase:
    def __init__(self):
        self.chunks, self.metas = load_corpus()
        self.embedder = SentenceTransformer(EMB_MODEL)
        emb = self.embedder.encode(self.chunks, normalize_embeddings=True, show_progress_bar=False)
        client = chromadb.EphemeralClient()
        self.col = client.create_collection("knowledge_base", metadata={"hnsw:space": "cosine"})
        self.col.add(ids=[f"c{i}" for i in range(len(self.chunks))], documents=self.chunks,
                     embeddings=[e.tolist() for e in emb],
                     metadatas=[{"src": m} for m in self.metas])
        self.bm25 = BM25Okapi([list(jieba.cut(c)) for c in self.chunks])
        self.reranker = CrossEncoder(RERANK_MODEL, max_length=512)

    def retrieve(self, query, k=TOP_K):
        vec = self.col.query(
            query_embeddings=[self.embedder.encode(query, normalize_embeddings=True).tolist()],
            n_results=len(self.chunks))["ids"][0]
        vec = [int(x[1:]) for x in vec]
        bm = list(np.argsort(self.bm25.get_scores(list(jieba.cut(query))))[::-1])
        cand = rrf([vec, bm])[:CANDIDATES]
        scores = self.reranker.predict([(query, self.chunks[i]) for i in cand], show_progress_bar=False)
        order = sorted(range(len(cand)), key=lambda j: -float(scores[j]))
        return [(cand[j], self.metas[cand[j]], self.chunks[cand[j]]) for j in order[:k]]


def build_prompt(question, hits):
    ctx = "\n\n".join(f"[{i+1}] 来源：{src}\n{text}" for i, (_, src, text) in enumerate(hits))
    return PROMPT_TMPL.format(context=ctx, question=question)


def main():
    load_dotenv()
    kb = KnowledgeBase()

    question = "出差去上海，酒店一晚最多能报多少？"
    hits = kb.retrieve(question)
    prompt = build_prompt(question, hits)

    print("=" * 70)
    print("检索到的 3 个片段：")
    for i, (_, src, text) in enumerate(hits, 1):
        print(f"  [{i}] {src}  {text[:40].replace(chr(10), ' ')}...")

    api_key = os.getenv("LLM_API_KEY")
    if not api_key:
        print("=" * 70)
        print("未配置 LLM_API_KEY，进入 dry-run。将要发送给模型的完整 Prompt：\n")
        print(prompt)
        print("=" * 70)
        print("配置方法：在 outputs/rag-kb-agent/.env 写入 LLM_API_KEY=sk-xxx 后重跑。")
        return

    from openai import OpenAI
    client = OpenAI(api_key=api_key,
                    base_url=os.getenv("LLM_BASE_URL", "https://api.deepseek.com"))
    resp = client.chat.completions.create(
        model=os.getenv("LLM_MODEL", "deepseek-chat"),
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
    )
    print("=" * 70)
    print("回答：")
    print(resp.choices[0].message.content)
    print("\n引用来源：")
    for i, (_, src, _) in enumerate(hits, 1):
        print(f"  [{i}] {src}")


if __name__ == "__main__":
    main()
