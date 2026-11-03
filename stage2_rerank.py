"""阶段 2：混合召回 + Cross-Encoder 重排。

对比：仅向量 / 混合 RRF / 混合 RRF + bge-reranker-base 精排。
召回 top-10 候选，重排后取 top-3 计算指标，并统计重排延迟。

Run:  outputs/run.cmd outputs/rag-kb-agent/stage2_rerank.py
"""
import glob
import os
import re
import time

import chromadb
import jieba
import numpy as np
from rank_bm25 import BM25Okapi
from sentence_transformers import CrossEncoder, SentenceTransformer

CORPUS_DIR = os.path.join(os.path.dirname(__file__), "corpus")
EMB_MODEL = "BAAI/bge-small-zh-v1.5"
RERANK_MODEL = "BAAI/bge-reranker-base"
CANDIDATES = 10


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


EVAL = [
    ("出差住宿能报销多少？", "每晚上限 600 元"),
    ("一线城市住宿标准是多少？", "每晚上限 600 元"),
    ("出差餐饮补助每天多少钱？", "每人每天 120 元"),
    ("报销单要在多久内提交？", "15 个自然日"),
    ("发票抬头错了能报销吗？", "个人抬头发票一律不予报销"),
    ("实习生账号有效期多久？", "有效期 6 个月"),
    ("密码多久要换一次？", "每 90 天强制更换"),
    ("ERR-1042 是什么错误？", "VPN 证书过期"),
    ("账号被锁定了怎么办？", "等待 30 分钟自动解锁"),
    ("Q3-2024 支持哪些文档格式？", "PDF、Word、Markdown、网页"),
    ("私有化部署最低配置是多少？", "8 核 CPU"),
    ("企业版支持哪些渠道对接？", "企业微信、钉钉、飞书"),
    ("会话量超限怎么计费？", "0.03 元/次"),
    ("年假有几天？", "满 1 年享受 5 天"),
    ("迟到半小时怎么处理？", "按事假半天处理"),
    ("周末加班工资怎么算？", "周末加班按 2 倍"),
    ("P0 故障多久响应？", "服务完全不可用"),
    ("P1 故障多久恢复？", "核心功能严重受损"),
    ("服务可用性承诺是多少？", "99.9%"),
    ("发现数据泄露要在多久内上报？", "30 分钟内上报"),
    ("安全事件日志要保留多久？", "保留 180 天"),
    ("安全演练多久一次？", "每季度组织一次"),
]


def rrf(rank_lists, k=60):
    scores = {}
    for ranking in rank_lists:
        for rank, idx in enumerate(ranking):
            scores[idx] = scores.get(idx, 0.0) + 1.0 / (k + rank + 1)
    return [i for i, _ in sorted(scores.items(), key=lambda x: -x[1])]


def evaluate(name, ranker, chunks, timings=None):
    h1 = h3 = 0
    mrr = 0.0
    rows = []
    for q, key in EVAL:
        gold = {i for i, c in enumerate(chunks) if key in c}
        gold = gold or {-1}
        t0 = time.perf_counter()
        rl = ranker(q)
        if timings is not None:
            timings.append((time.perf_counter() - t0) * 1000)
        rank = next((r + 1 for r, i in enumerate(rl) if i in gold), None)
        if rank:
            mrr += 1.0 / rank
            h1 += rank == 1
            h3 += rank <= 3
        rows.append((q, str(rank or "-")))
    n = len(EVAL)
    return {"name": name, "hit1": h1 / n, "hit3": h3 / n, "mrr": mrr / n, "rows": rows}


def main():
    chunks, metas = load_corpus()
    print(f"语料 {len(chunks)} 个 chunk，评测 {len(EVAL)} 题，重排候选数 {CANDIDATES}\n")

    embedder = SentenceTransformer(EMB_MODEL)
    emb = embedder.encode(chunks, normalize_embeddings=True, show_progress_bar=False)
    client = chromadb.EphemeralClient()
    col = client.create_collection("knowledge_base", metadata={"hnsw:space": "cosine"})
    col.add(ids=[f"c{i}" for i in range(len(chunks))], documents=chunks,
            embeddings=[e.tolist() for e in emb], metadatas=[{"src": m} for m in metas])
    bm25 = BM25Okapi([list(jieba.cut(c)) for c in chunks])

    def rank_vector(q):
        res = col.query(query_embeddings=[embedder.encode(q, normalize_embeddings=True).tolist()],
                        n_results=len(chunks))
        return [int(x[1:]) for x in res["ids"][0]]

    def rank_bm25(q):
        return list(np.argsort(bm25.get_scores(list(jieba.cut(q))))[::-1])

    hybrid_cache = {}

    def rank_hybrid(q):
        if q not in hybrid_cache:
            hybrid_cache[q] = rrf([rank_vector(q), rank_bm25(q)])
        return hybrid_cache[q]

    print("加载重排模型（首次会下载约 1.1GB）...")
    reranker = CrossEncoder(RERANK_MODEL, max_length=512)

    rerank_ms = []

    def rank_rerank(q):
        cand = rank_hybrid(q)[:CANDIDATES]
        t0 = time.perf_counter()
        scores = reranker.predict([(q, chunks[i]) for i in cand], show_progress_bar=False)
        rerank_ms.append((time.perf_counter() - t0) * 1000)
        order = sorted(range(len(cand)), key=lambda j: -float(scores[j]))
        return [cand[j] for j in order] + rank_hybrid(q)[CANDIDATES:]

    results = [evaluate("仅向量", rank_vector, chunks),
               evaluate("混合 RRF", rank_hybrid, chunks),
               evaluate("RRF+重排", rank_rerank, chunks)]

    print(f"\n{'策略':<10}{'Hit@1':>8}{'Hit@3':>8}{'MRR':>8}")
    print("-" * 34)
    for r in results:
        print(f"{r['name']:<10}{r['hit1']:>8.2f}{r['hit3']:>8.2f}{r['mrr']:>8.2f}")

    print(f"\n重排延迟：平均 {np.mean(rerank_ms):.0f} ms/题，"
          f"P95 {np.percentile(rerank_ms, 95):.0f} ms（{CANDIDATES} 个候选，CPU）")

    print("\n每题标准答案排名：")
    print(f"{'问题':<26}{'向量':>6}{'RRF':>7}{'重排':>6}")
    print("-" * 48)
    for q, _ in EVAL:
        row = [next(x[1] for x in r["rows"] if x[0] == q) for r in results]
        print(f"{q[:24]:<26}{row[0]:>6}{row[1]:>7}{row[2]:>6}")


if __name__ == "__main__":
    main()
