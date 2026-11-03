"""阶段 8：把多跳查询分解迁移到真实语料（264 篇 Dify 文档）。

对比两种策略：
  A. 单查询：直接拿原问题检索 top-5；
  B. 查询分解：LLM 拆成 2-3 个子问题，各自检索后做「配额合并」。

配额合并的必要性：纯 RRF 会偏向被多个子问题同时命中的相似片段，
把只在一个子问题里出现的关键片段挤出 top-k —— 多跳场景下这是致命的。

Run:  outputs/run.cmd outputs/rag-kb-agent/stage8_multihop_real.py
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from openai import OpenAI

from rag_core import KnowledgeBase, load_dotenv, rrf

EVAL_PATH = os.path.join(HERE, "eval_set_real.json")
REPORT_PATH = os.path.join(HERE, "eval_report_multihop_real.json")
TOP_K = 5

DECOMP_PROMPT = """把下面的多跳问题拆成 2-3 个可以独立检索的子问题。
要求：
1. 每个子问题只关注一个事实点；
2. 尽量使用产品文档里可能出现的术语，不要用口语化的同义词；
3. 只输出 JSON 数组，例如 ["子问题1", "子问题2"]，不要任何解释。

问题：{q}"""


def decompose(client, model, question):
    """让模型拆题；解析失败时退化为按标点切分。"""
    try:
        text = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": DECOMP_PROMPT.format(q=question)}],
            temperature=0,
        ).choices[0].message.content
        m = re.search(r"\[.*\]", text, re.S)
        subs = json.loads(m.group(0)) if m else []
        subs = [str(s).strip() for s in subs if str(s).strip()]
        if subs:
            return subs[:3]
    except Exception:
        pass
    parts = [p.strip("，。？ ") for p in re.split(r"[，。？]", question)]
    return [p for p in parts if len(p) > 4][:3]


def quota_merge(rankings, top_k=5, window=3):
    """每个子问题保底贡献一个未选中的片段，再用 RRF 补齐。"""
    picked = []
    for ranking in rankings:
        for idx in ranking[:window]:
            if idx not in picked:
                picked.append(idx)
                break
    for idx in rrf(rankings):
        if len(picked) >= top_k:
            break
        if idx not in picked:
            picked.append(idx)
    return picked[:top_k]


def coverage(docs, gold):
    hit = [g for g in gold if g in docs]
    return len(hit) / len(gold), len(hit) == len(gold)


def union_then_rerank(kb, question, subs, top_k=TOP_K):
    """子问题只用来扩大召回，最终用原问题做一次重排。

    这样既利用了拆题带来的召回多样性，又避免子问题的措辞把排序带偏。
    """
    cand = set()
    for q in subs + [question]:
        for h in kb.retrieve(q, k=6, candidates=20):
            cand.add(h[0])
    cand = list(cand)
    scores = kb.reranker.predict([(question, kb.chunks[i]) for i in cand],
                                 show_progress_bar=False)
    order = sorted(range(len(cand)), key=lambda j: -float(scores[j]))
    return [cand[j] for j in order[:top_k]]


def max_score_fusion(kb, subs, top_k=TOP_K):
    """每个候选取它在各个子问题下的最高重排分，再排序。

    比“用复合问题统一重排”更对症：只要某个子问题能把它排高，它就有机会进 top-k。
    """
    cand = set()
    for s in subs:
        for h in kb.retrieve(s, k=6, candidates=20):
            cand.add(h[0])
    cand = list(cand)
    best = {i: -1e9 for i in cand}
    for s in subs:
        scores = kb.reranker.predict([(s, kb.chunks[i]) for i in cand],
                                     show_progress_bar=False)
        for i, v in zip(cand, scores):
            best[i] = max(best[i], float(v))
    order = sorted(cand, key=lambda i: -best[i])
    return order[:top_k]


def main():
    load_dotenv()
    data = json.load(open(EVAL_PATH, encoding="utf-8"))
    items = data["multi_hop"]
    kb = KnowledgeBase()

    client = OpenAI(api_key=os.environ["LLM_API_KEY"],
                    base_url=os.environ.get("LLM_BASE_URL", "https://api.deepseek.com"),
                    timeout=60)
    model = os.environ.get("LLM_MODEL", "deepseek-chat")

    base_cov = dec_cov = 0.0
    base_all5 = dec_all5 = 0
    base_all3 = dec_all3 = 0
    uni_cov = 0.0
    uni_all5 = uni_all3 = 0
    mf_cov = 0.0
    mf_all5 = mf_all3 = 0
    rows = []

    print(f"多跳 {len(items)} 题\n")
    print(f"{'问题':<26}{'单查':>8}{'分解':>8}{'扩召回':>8}{'取最高':>8}")
    print("-" * 78)

    for it in items:
        q, gold = it["q"], it["gold_docs"]

        # A. 单查询
        base_hits = kb.retrieve(q, k=TOP_K)
        base_docs = [h[1].split("#")[0] for h in base_hits]
        b_cov, b_all = coverage(base_docs, gold)

        # B. 分解 + 配额合并
        subs = decompose(client, model, q)
        rankings = [[h[0] for h in kb.retrieve(s, k=6, candidates=20)] for s in subs]
        merged = quota_merge(rankings, top_k=TOP_K)
        merged_docs = [kb.metas[i].split("#")[0] for i in merged]
        d_cov, d_all = coverage(merged_docs, gold)

        # C. 分解扩召回 + 原问题重排
        uni = union_then_rerank(kb, q, subs)
        uni_docs = [kb.metas[i].split("#")[0] for i in uni]
        u_cov, u_all = coverage(uni_docs, gold)

        # D. 每个候选取它在各子问题下的最高重排分
        mf = max_score_fusion(kb, subs)
        mf_docs = [kb.metas[i].split("#")[0] for i in mf]
        m_cov, m_all = coverage(mf_docs, gold)

        base_cov += b_cov; dec_cov += d_cov
        base_all5 += b_all; dec_all5 += d_all
        base_all3 += coverage(base_docs[:3], gold)[1]
        dec_all3 += coverage(merged_docs[:3], gold)[1]
        uni_cov += u_cov
        uni_all5 += u_all
        uni_all3 += coverage(uni_docs[:3], gold)[1]
        mf_cov += m_cov
        mf_all5 += m_all
        mf_all3 += coverage(mf_docs[:3], gold)[1]

        rows.append({"q": q, "sub_questions": subs,
                     "base_docs": base_docs, "merged_docs": merged_docs,
                     "base_coverage": b_cov, "dec_coverage": d_cov,
                     "base_all5": b_all, "dec_all5": d_all})

        print(f"{q[:24]:<26}{b_cov:>6.2f}{'✓' if b_all else '✗':>2}"
              f"{d_cov:>6.2f}{'✓' if d_all else '✗':>2}"
              f"{u_cov:>6.2f}{'✓' if u_all else '✗':>2}"
              f"{m_cov:>6.2f}{'✓' if m_all else '✗':>2}  {len(subs)}")

    n = len(items)
    print("-" * 78)
    print(f"Coverage@5  单查询 {base_cov/n:.2f}  ->  分解 {dec_cov/n:.2f}")
    print(f"AllHit@5    单查询 {base_all5}/{n}  ->  分解 {dec_all5}/{n}")
    print(f"AllHit@3    单查询 {base_all3}/{n}  ->  分解 {dec_all3}/{n}")
    print(f"Coverage@5  分解+原问题重排 {uni_cov/n:.2f}")
    print(f"AllHit@5    分解+原问题重排 {uni_all5}/{n}")
    print(f"AllHit@3    分解+原问题重排 {uni_all3}/{n}")
    print(f"Coverage@5  子问题取最高分 {mf_cov/n:.2f}")
    print(f"AllHit@5    子问题取最高分 {mf_all5}/{n}")
    print(f"AllHit@3    子问题取最高分 {mf_all3}/{n}")

    print("\n【分解明细】")
    for r in rows:
        print(f"  {r['q'][:24]}")
        for s in r["sub_questions"]:
            print(f"    - {s}")

    json.dump({"rows": rows,
               "summary": {"n": n, "base_coverage5": base_cov/n, "dec_coverage5": dec_cov/n,
                           "base_all5": base_all5, "dec_all5": dec_all5,
                           "base_all3": base_all3, "dec_all3": dec_all3}},
              open(REPORT_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\n报告写入 {REPORT_PATH}")


if __name__ == "__main__":
    main()

