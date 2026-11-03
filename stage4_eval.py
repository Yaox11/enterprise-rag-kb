"""阶段 4：口语化问题 + 无答案问题的评测。

测三件事：
  1. 口语化提问下检索还能不能命中（Hit@1 / Hit@3 / MRR）
  2. 文档里没有答案时，重排最高分是不是明显更低（可用于定拒答阈值）
  3. 端到端生成：答对率、引用率、拒答率、误拒率

Run:  outputs/run.cmd outputs/rag-kb-agent/stage4_eval.py
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from rag_core import KnowledgeBase, build_prompt, load_dotenv

EVAL_PATH = os.path.join(HERE, "eval_set.json")
REPORT_PATH = os.path.join(HERE, "eval_report.json")


def norm(s):
    """去掉所有空白，避免「6 个月」和「6个月」被判成两个答案。"""
    return re.sub(r"\s+", "", s)


def ask_llm(client, model, prompt):
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
    )
    return resp.choices[0].message.content.strip()


def main():
    load_dotenv()
    data = json.load(open(EVAL_PATH, encoding="utf-8"))
    coll, unans = data["colloquial"], data["unanswerable"]

    kb = KnowledgeBase()
    print(f"语料 {len(kb.chunks)} 个 chunk；口语化 {len(coll)} 题；无答案 {len(unans)} 题\n")

    # ---------- 1. 口语化检索 ----------
    h1 = h3 = 0
    mrr = 0.0
    ans_scores = []
    print("【口语化 · 检索】")
    print(f"{'问题':<30}{'排名':>6}{'top1 来源':>24}")
    print("-" * 62)
    for item in coll:
        q = item["q"]
        hits = kb.retrieve(q, k=10)
        gold = kb.gold_indices(item["gold"])
        rank = next((r + 1 for r, h in enumerate(hits) if h[0] in gold), None)
        if rank:
            mrr += 1.0 / rank
            h1 += rank == 1
            h3 += rank <= 3
        ans_scores.append(hits[0][3])
        print(f"{q[:28]:<30}{str(rank or '-'):>6}{hits[0][1]:>24}")
    n = len(coll)
    print(f"→ Hit@1 {h1/n:.2f} | Hit@3 {h3/n:.2f} | MRR {mrr/n:.2f}\n")

    # ---------- 2. 无答案问题的重排分 ----------
    print("【无答案 · 重排最高分】")
    una_scores = []
    for q in unans:
        hits = kb.retrieve(q, k=1)
        una_scores.append(hits[0][3])
        print(f"  {q:<32}top1 分数 {hits[0][3]:>7.3f}   {hits[0][1]}")

    lo, hi = max(una_scores), min(ans_scores)
    print(f"\n有答案题 top1 分数：最低 {min(ans_scores):.3f} / 平均 {sum(ans_scores)/len(ans_scores):.3f}")
    print(f"无答案题 top1 分数：最高 {max(una_scores):.3f} / 平均 {sum(una_scores)/len(una_scores):.3f}")
    if lo < hi:
        print(f"两类之间没有重叠，建议拒答阈值取中点：{(lo + hi) / 2:.3f}")
    else:
        print(f"两类分数有重叠（无答案最高 {lo:.3f} ≥ 有答案最低 {hi:.3f}），单靠阈值会误拒，需要配合 LLM 判断")

    # ---------- 3. 端到端生成 ----------
    key = os.getenv("LLM_API_KEY")
    report = {"retrieval": {"hit1": h1/n, "hit3": h3/n, "mrr": mrr/n},
              "scores": {"answerable_min": min(ans_scores), "unanswerable_max": max(una_scores)}}
    if not key:
        print("\n未配置 LLM_API_KEY，跳过生成评测。")
        json.dump(report, open(REPORT_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        return

    from openai import OpenAI
    client = OpenAI(api_key=key, base_url=os.getenv("LLM_BASE_URL", "https://api.deepseek.com"))
    model = os.getenv("LLM_MODEL", "deepseek-chat")

    print("\n【端到端 · 生成】")
    correct = cited = false_refuse = 0
    rows = []
    for item in coll:
        q = item["q"]
        hits = kb.retrieve(q, k=3)
        prompt = build_prompt(q, [(h[1], h[2]) for h in hits])
        try:
            ans = ask_llm(client, model, prompt)
        except Exception as exc:
            print(f"  [API 错误] {exc}")
            break
        refused = "无法回答" in ans
        ok = norm(item["answer_key"]) in norm(ans)
        has_cite = ("[" in ans) and ("]" in ans)
        correct += ok
        cited += has_cite
        false_refuse += refused
        rows.append({"q": q, "answer": ans, "correct": ok, "refused": refused})
        print(f"  {'✓' if ok else '✗'} {q[:26]:<28} {ans[:52]}")

    refused_ok = 0
    for q in unans:
        hits = kb.retrieve(q, k=3)
        prompt = build_prompt(q, [(h[1], h[2]) for h in hits])
        try:
            ans = ask_llm(client, model, prompt)
        except Exception as exc:
            print(f"  [API 错误] {exc}")
            break
        ok = "无法回答" in ans
        refused_ok += ok
        rows.append({"q": q, "answer": ans, "refused": ok})
        print(f"  {'✓' if ok else '✗'} {q[:26]:<28} {ans[:52]}")

    m = len(coll)
    print(f"\n答对率 {correct}/{m} = {correct/m:.0%}")
    print(f"引用率 {cited}/{m} = {cited/m:.0%}")
    print(f"误拒率 {false_refuse}/{m} = {false_refuse/m:.0%}")
    print(f"无答案拒答率 {refused_ok}/{len(unans)} = {refused_ok/len(unans):.0%}")

    report["generation"] = {"correct": correct, "total_answerable": m,
                            "cited": cited, "false_refusal": false_refuse,
                            "refused_unanswerable": refused_ok,
                            "total_unanswerable": len(unans), "rows": rows}
    json.dump(report, open(REPORT_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\n报告已写入 {REPORT_PATH}")


if __name__ == "__main__":
    main()
