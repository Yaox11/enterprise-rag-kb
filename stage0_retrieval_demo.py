"""阶段 0 + 混合检索预览：向量检索 vs BM25（无 LLM，纯检索对比）。

Run:  outputs/run.cmd outputs/rag-kb-agent/stage0_retrieval_demo.py
"""
import warnings

# jieba 0.42.1 内部仍在使用已弃用的 pkg_resources（setuptools 81+ 会告警）。
# 这是第三方库的历史问题，不影响运行，过滤掉以免污染调试输出。
warnings.filterwarnings("ignore", message="pkg_resources is deprecated as an API")

import glob
import os
import sys

import jieba
import numpy as np
import chromadb
from rank_bm25 import BM25Okapi
from sentence_transformers import SentenceTransformer

CORPUS_DIR = os.path.join(os.path.dirname(__file__), "corpus")
EMB_MODEL = "BAAI/bge-small-zh-v1.5"   # 中文小模型，约 95MB，首次运行会从 hf-mirror 下载


def chunk_text(text: str, size: int = 220, overlap: int = 40) -> list[str]:
    """最朴素的分块：按固定字数切，留 overlap 防止切断语义。
    真实项目里要换成结构感知分块（按标题层级）。"""
    text = text.strip()
    chunks, start = [], 0
    while start < len(text):
        end = start + size
        chunks.append(text[start:end])
        if end >= len(text):
            break
        start = end - overlap
    return [c for c in chunks if len(c.strip()) > 20]


def load_corpus():
    """返回 (chunk 文本列表, 每个 chunk 的来源标签)"""
    texts, metas = [], []
    for path in sorted(glob.glob(os.path.join(CORPUS_DIR, "*.md"))):
        raw = open(path, encoding="utf-8").read()
        name = os.path.basename(path)
        for i, ch in enumerate(chunk_text(raw)):
            texts.append(ch)
            metas.append(f"{name}#{i}")
    return texts, metas


def main():
    chunks, metas = load_corpus()
    print(f"语料：{len(set(m.split(chr(35))[0] for m in metas))} 个文档 -> {len(chunks)} 个 chunk\n")

    # ---------- 路线 1：稠密向量检索 ----------
    model = SentenceTransformer(EMB_MODEL)
    emb = model.encode(chunks, normalize_embeddings=True, show_progress_bar=False)

    client = chromadb.EphemeralClient()
    col = client.create_collection("knowledge_base", metadata={"hnsw:space": "cosine"})
    col.add(ids=[f"c{i}" for i in range(len(chunks))], documents=chunks,
            embeddings=[e.tolist() for e in emb], metadatas=[{"src": m} for m in metas])

    # ---------- 路线 2：稀疏 BM25 检索 ----------
    tokenized = [list(jieba.cut(c)) for c in chunks]
    bm25 = BM25Okapi(tokenized)

    queries = [
        "出差住宿能报销多少？",        # 语义型：向量应该更强
        "ERR-1042 是什么错误？",      # 精确编码：BM25 应该更强
        "Q3-2024 支持本地知识库吗？",  # 版本号 + 语义混合
    ]

    def vector_search(q, k=3):
        res = col.query(query_embeddings=[model.encode(q, normalize_embeddings=True).tolist()], n_results=k)
        return [(m.get("src"), round(d, 4)) for m, d in zip(res["metadatas"][0], res["distances"][0])]

    def bm25_search(q, k=3):
        scores = bm25.get_scores(list(jieba.cut(q)))
        idx = np.argsort(scores)[::-1][:k]
        return [(metas[i], round(float(scores[i]), 4)) for i in idx]

    for q in queries:
        print("=" * 78)
        print("问题:", q)
        print("  [向量检索] top3:", vector_search(q))
        print("  [BM25    ] top3:", bm25_search(q))


if __name__ == "__main__":
    main()
