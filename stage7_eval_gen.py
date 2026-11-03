"""阶段 7：端到端生成评测（真实语料）。

单跳题：检索 top3 -> 生成 -> 用 LLM 当裁判和参考答案比对；
无答案题：直接看模型是否拒答。

为什么用 LLM 当裁判：同一个事实的说法可以差很多（「600 元」vs「每晚上限六百元」），
关键词匹配会大量误判。裁判也有噪声，所以同时统计拒答率和引用率做交叉验证。

Run:  outputs/run.cmd outputs/rag-kb-agent/stage7_eval_gen.py
"""
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from openai import OpenAI

from rag_core import KnowledgeBase, build_prompt, load_dotenv

EVAL_PATH = os.path.join(HERE, "eval_set_real.json")
REPORT_PATH = os.path.join(HERE, "eval_report_gen.json")
TOP_K = 3

JUDGE_PROMPT = """参考答案：{ref}

模型回答：{ans}

请判断模型回答是否与参考答案表达同一事实。允许措辞不同，但关键数字、名称、步骤必须一致。
如果模型回答在关键事实上出错，或者答非所问，判为 NO。
只输出 YES 或 NO。"""

# 这些词出现，基本可以认定是拒答
REFUSAL_WORDS = ["无法回答", "未提及", "没有相关", "资料中没有", "无法确定", "没有说明"]


def chat(client, model, prompt, temperature=0.2):
    return client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
    ).choices[0].message.content.strip()


def is_refusal(ans):
    return any(w in ans for w in REFUSAL_WORDS)


def main():
    load_dotenv()
    data = json.load(open(EVAL_PATH, encoding="utf-8"))
    kb = KnowledgeBase()

    client = OpenAI(api_key=os.environ["LLM_API_KEY"],
                    base_url=os.environ.get("LLM_BASE_URL", "https://api.deepseek.com"),
                    timeout=60)
    model = os.environ.get("LLM_MODEL", "deepseek-chat")

    ret_ms, gen_ms, judge_ms = [], [], []
    correct = cited = false_refuse = 0
    rows = []

    print(f"单跳 {len(data['single_hop'])} 题\n")
    for item in data["single_hop"]:
        q, ref = item["q"], item["answer"]

        t0 = time.perf_counter()
        hits = kb.retrieve(q, k=TOP_K)
        t1 = time.perf_counter()

        prompt = build_prompt(q, [(h[1], h[2]) for h in hits])
        ans = chat(client, model, prompt)
        t2 = time.perf_counter()

        refused = is_refusal(ans)
        has_cite = bool(re.search(r"\[\d+\]", ans))

        # 拒答就不必再让裁判判了，直接算错；否则交给 LLM 裁判
        if refused:
            ok = False
            judge_used = False
        else:
            verdict = chat(client, model, JUDGE_PROMPT.format(ref=ref, ans=ans), temperature=0)
            ok = verdict.strip().upper().startswith("YES")
            judge_used = True
        t3 = time.perf_counter()

        ret_ms.append((t1 - t0) * 1000)
        gen_ms.append((t2 - t1) * 1000)
        if judge_used:
            judge_ms.append((t3 - t2) * 1000)

        correct += ok
        cited += has_cite
        false_refuse += refused
        rows.append({"q": q, "ref": ref, "answer": ans, "correct": ok,
                     "refused": refused, "cited": has_cite})

        mark = "✓" if ok else ("拒" if refused else "✗")
        print(f"  {mark} {q[:26]:<28}{ans[:46]}")

    n = len(data["single_hop"])
    print("\n【单跳 · 端到端】")
    print(f"  答对率 {correct}/{n} = {correct/n:.0%}")
    print(f"  引用率 {cited}/{n} = {cited/n:.0%}")
    print(f"  误拒率 {false_refuse}/{n} = {false_refuse/n:.0%}")

    # ---------- 无答案题：只看是否拒答 ----------
    refused_ok = 0
    una_rows = []
    for q in data["unanswerable"]:
        hits = kb.retrieve(q, k=TOP_K)
        ans = chat(client, model, build_prompt(q, [(h[1], h[2]) for h in hits]))
        ok = is_refusal(ans)
        refused_ok += ok
        una_rows.append({"q": q, "answer": ans, "refused": ok})
        print(f"  {'✓' if ok else '✗'} {q[:26]:<28}{ans[:46]}")

    m = len(data["unanswerable"])
    print("\n【无答案 · 拒答】")
    print(f"  拒答率 {refused_ok}/{m} = {refused_ok/m:.0%}")

    def avg(xs):
        return sum(xs) / len(xs) if xs else 0

    print("\n【延迟】")
    print(f"  检索 {avg(ret_ms):.0f} ms | 生成 {avg(gen_ms):.0f} ms | 裁判 {avg(judge_ms):.0f} ms")

    json.dump({"single_hop": rows, "unanswerable": una_rows,
               "summary": {"correct": correct, "n": n, "cited": cited,
                           "false_refusal": false_refuse, "refused_unanswerable": refused_ok,
                           "m": m, "avg_ret_ms": avg(ret_ms),
                           "avg_gen_ms": avg(gen_ms), "avg_judge_ms": avg(judge_ms)}},
              open(REPORT_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\n报告写入 {REPORT_PATH}")


if __name__ == "__main__":
    main()

