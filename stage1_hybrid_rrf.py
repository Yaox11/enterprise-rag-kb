"""阶段 1：混合检索 + RRF 融合，并用评测集量化效果。

对比三种策略：仅向量 / 仅 BM25 / 向量+BM25 经 RRF 融合。
指标：Hit@1、Hit@3、MRR（标准答案 chunk 的排名倒数）。

Run:  outputs/run.cmd outputs/rag-kb-agent/stage1_hybrid_rrf.py
"""
import warnings

# jieba 0.42.1 内部仍在使用已弃用的 pkg_resources（setuptools 81+ 会告警）。
# 这是第三方库的历史问题，不影响运行，过滤掉以免污染调试输出。
warnings.filterwarnings("ignore", message="pkg_resources is deprecated as an API")

import glob
import os
import re

import chromadb
import jieba
import numpy as np
from rank_bm25 import BM25Okapi
from sentence_transformers import SentenceTransformer

CORPUS_DIR = os.path.join(os.path.dirname(__file__), "corpus")
EMB_MODEL = "BAAI/bge-small-zh-v1.5"


def chunk_text(text, max_chars=320, overlap=40):
    """结构感知分块：按 Markdown 标题切，标题跟正文待在一起；
    超长小节再按字数兜底切分。"""
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


# (问题, 标准答案所在 chunk 必须包含的字符串)
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
    """Reciprocal Rank Fusion：只用名次，不用原始分数。"""
    scores = {}
    for ranking in rank_lists:
        for rank, idx in enumerate(ranking):
            scores[idx] = scores.get(idx, 0.0) + 1.0 / (k + rank + 1)
    return [i for i, _ in sorted(scores.items(), key=lambda x: -x[1])]


def evaluate(name, ranker, chunks):
    h1 = h3 = 0
    mrr = 0.0
    rows = []
    for q, key in EVAL:
        gold = {i for i, c in enumerate(chunks) if key in c}
        if not gold:
            rows.append((q, "-", "-"))
            print(f"  [warn] 找不到标准答案片段: {q} / {key}")
            continue
        rl = ranker(q)
        rank = next((r + 1 for r, i in enumerate(rl) if i in gold), None)
        if rank:
            mrr += 1.0 / rank
            if rank == 1:
                h1 += 1
            if rank <= 3:
                h3 += 1
        rows.append((q, str(rank), ""))
    n = len(EVAL)
    return {"name": name, "hit1": h1 / n, "hit3": h3 / n, "mrr": mrr / n, "rows": rows}


def main():
    chunks, metas = load_corpus()
    model = SentenceTransformer(EMB_MODEL)
    emb = model.encode(chunks, normalize_embeddings=True, show_progress_bar=False)

    client = chromadb.EphemeralClient()
    col = client.create_collection("knowledge_base", metadata={"hnsw:space": "cosine"})
    col.add(ids=[f"c{i}" for i in range(len(chunks))], documents=chunks,
            embeddings=[e.tolist() for e in emb], metadatas=[{"src": m} for m in metas])

    bm25 = BM25Okapi([list(jieba.cut(c)) for c in chunks])

    def rank_vector(q):
        res = col.query(query_embeddings=[model.encode(q, normalize_embeddings=True).tolist()],
                        n_results=len(chunks))
        ids = [int(x[1:]) for x in res["ids"][0]]
        return ids

    def rank_bm25(q):
        scores = bm25.get_scores(list(jieba.cut(q)))
        return list(np.argsort(scores)[::-1])

    def rank_hybrid(q):
        return rrf([rank_vector(q), rank_bm25(q)])

    results = [evaluate("仅向量", rank_vector, chunks),
               evaluate("仅 BM25", rank_bm25, chunks),
               evaluate("混合 RRF", rank_hybrid, chunks)]

    print(f"语料 {len(chunks)} 个 chunk，评测 {len(EVAL)} 题\n")
    print(f"{'策略':<10}{'Hit@1':>8}{'Hit@3':>8}{'MRR':>8}")
    print("-" * 34)
    for r in results:
        print(f"{r['name']:<10}{r['hit1']:>8.2f}{r['hit3']:>8.2f}{r['mrr']:>8.2f}")

    print("\n每题标准答案的排名（1 为命中第一）：")
    print(f"{'问题':<26}{'向量':>6}{'BM25':>7}{'RRF':>6}")
    print("-" * 50)
    for q, _ in EVAL:
        row = [next((x[1] for x in r["rows"] if x[0] == q), "-") for r in results]
        print(f"{q[:24]:<26}{row[0]:>6}{row[1]:>7}{row[2]:>6}")


if __name__ == "__main__":
    main()
