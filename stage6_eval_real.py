"""阶段 6：真实语料评测（264 篇 Dify 官方文档，6036 个片段）。

三类题目分开统计：
  单跳：答案在一篇文档里，测检索命中率和排名；
  多跳：需要同时命中两篇文档，测覆盖率；
  拒答：语料里没有答案，测最高重排分是否能和“有答案”区分开。

指标都按“文档级”计算：只要召回到正确文档的任一相关片段就算命中。

Run:  outputs/run.cmd outputs/rag-kb-agent/stage6_eval_real.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from rag_core import KnowledgeBase, load_dotenv

EVAL_PATH = os.path.join(HERE, "eval_set_real.json")
REPORT_PATH = os.path.join(HERE, "eval_report_real.json")


def doc_indices(kb, doc):
    """某篇文档对应的所有 chunk 下标，用于文档级命中判定。"""
    return {i for i, m in enumerate(kb.metas) if m.startswith(doc + "#")}


def main():
    load_dotenv()
    data = json.load(open(EVAL_PATH, encoding="utf-8"))
    kb = KnowledgeBase()
    print(f"语料 {len(kb.chunks)} 个片段\n")

    # ---------- 1. 单跳 ----------
    single = data["single_hop"]
    h1 = h3 = h5 = 0
    mrr = 0.0
    gold_scores = []
    failures = []
    for item in single:
        gold = set()
        for doc in item["gold_chunks"]:
            gold |= doc_indices(kb, doc.split("#")[0])
        hits = kb.retrieve(item["q"], k=5)
        ranks = [r + 1 for r, h in enumerate(hits) if h[0] in gold]
        rank = min(ranks) if ranks else None
        if rank:
            mrr += 1.0 / rank
            h1 += rank == 1
            h3 += rank <= 3
            h5 += rank <= 5
            gold_scores.append(max(h[3] for h in hits if h[0] in gold))
        else:
            failures.append((item["q"], item["gold_chunks"][0]))

    n = len(single)
    print("【单跳检索】")
    print(f"  Hit@1 {h1/n:.2f} | Hit@3 {h3/n:.2f} | Hit@5 {h5/n:.2f} | MRR {mrr/n:.2f}")
    if failures:
        print(f"  未召回 {len(failures)} 题：")
        for q, doc in failures[:5]:
            print(f"    - {q[:40]}  →  应为 {doc}")

    # ---------- 2. 多跳 ----------
    multi = data["multi_hop"]
    cov_sum, all5, all3 = 0.0, 0, 0
    for item in multi:
        docs = item["gold_docs"]
        hits = kb.retrieve(item["q"], k=5)
        got = set()
        for h in hits:
            f = h[1].split("#")[0]
            if f in docs:
                got.add(f)
        cov_sum += len(got) / len(docs)
        all5 += len(got) == len(docs)
        # 前 3 名是否已覆盖全部文档
        top3 = {h[1].split("#")[0] for h in hits[:3]}
        all3 += all(d in top3 for d in docs)

    m = len(multi)
    print("\n【多跳】")
    print(f"  Coverage@5 {cov_sum/m:.2f} | AllHit@5 {all5}/{m} | AllHit@3 {all3}/{m}")

    # ---------- 3. 拒答 ----------
    una = data["unanswerable"]
    una_scores = [kb.retrieve(q, k=1)[0][3] for q in una]
    print("\n【拒答信号】")
    print(f"  无答案题 top1 分数：最低 {min(una_scores):.3f} / 平均 {sum(una_scores)/len(una_scores):.3f} / 最高 {max(una_scores):.3f}")
    if gold_scores:
        print(f"  有答案题命中分数：最低 {min(gold_scores):.3f} / 平均 {sum(gold_scores)/len(gold_scores):.3f}")
        print(f"  两者重叠区间：{min(una_scores):.3f} ~ {min(max(una_scores), min(gold_scores)):.3f}")

    json.dump({
        "single_hop": {"n": n, "hit1": h1/n, "hit3": h3/n, "hit5": h5/n, "mrr": mrr/n,
                       "failures": failures},
        "multi_hop": {"n": m, "coverage5": cov_sum/m, "all_hit5": all5, "all_hit3": all3},
        "unanswerable": {"n": len(una), "scores": una_scores},
    }, open(REPORT_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\n报告写入 {REPORT_PATH}")


if __name__ == "__main__":
    main()

