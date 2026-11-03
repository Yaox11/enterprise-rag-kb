"""阶段 5：多跳问题评测 + 查询分解（Query Decomposition）。

为什么要单独测多跳？
    普通问题的事实集中在一个 chunk 里；多跳问题必须同时拿到 2 个以上
    不同片段才能回答，有时还要再做一次算术。单查询检索的 top-3 往往
    只能覆盖其中一个，模型就会「看起来答了」，其实缺一半依据。

两种策略对比：
    A. 单查询：直接用原问题检索 top-3 / top-5
    B. 查询分解：让 LLM 把问题拆成 2-3 个可独立检索的子问题，
       分别检索后再用 RRF 合并

指标：
    Coverage@k —— 必需要素被覆盖的平均比例（连续值，0~1）
    AllHit@k   —— 所有要素都覆盖到的题目比例（严格指标）

Run:  outputs/run.cmd outputs/rag-kb-agent/stage5_multihop.py
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from rag_core import KnowledgeBase, build_prompt, load_dotenv, rrf

EVAL_PATH = os.path.join(HERE, "eval_set.json")
REPORT_PATH = os.path.join(HERE, "eval_report_multihop.json")

# 只让模型输出 JSON 数组，便于解析；temperature=0 保证结果稳定。
DECOMP_PROMPT = """把下面的多跳问题拆成 2-3 个可以独立检索的子问题。
要求：
1. 每个子问题只关注一个事实点；
2. 子问题之间不要重复；
3. 只输出 JSON 数组，例如 ["子问题1", "子问题2"]，不要输出任何解释。

问题：{q}"""


def norm(s):
    """去掉所有空白，避免「3 月 31 日」和「3月31日」被判成不同。"""
    return re.sub(r"\s+", "", s)


def decompose(client, model, question):
    """调用 LLM 做查询分解；解析失败时退化为按标点切分，保证流程不中断。"""
    try:
        text = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": DECOMP_PROMPT.format(q=question)}],
            temperature=0,
        ).choices[0].message.content
        # 模型有时会用 ```json 包裹，用正则把数组部分抠出来
        m = re.search(r"\[.*\]", text, re.S)
        subs = json.loads(m.group(0)) if m else []
        subs = [str(s).strip() for s in subs if str(s).strip()]
        if subs:
            return subs[:3]
    except Exception:
        pass
    # 兜底方案：按中文标点粗切，宁可效果差也不让脚本崩
    parts = [p.strip("，。？ ") for p in re.split(r"[，。？]", question)]
    return [p for p in parts if len(p) > 4][:3]


def coverage(found, gold_sets):
    """found 是检索到的 chunk 下标；gold_sets 是每个要素对应的下标集合。
    返回 (覆盖率, 是否全命中)。"""
    flags = [any(i in g for i in found) for g in gold_sets]
    return sum(flags) / len(flags), all(flags)


def quota_merge(rankings, top_k=3, window=3):
    """多跳专用合并：每个子问题保底贡献一个「新」片段，再按 RRF 补齐。

    纯 RRF 会偏向被多个子问题同时命中的相似片段，把只在一个子问题里
    出现的关键片段挤出 top-k —— 多跳场景下这恰恰是致命的。
    """
    picked = []
    for ranking in rankings:
        for idx in ranking[:window]:   # 在该子问题前 window 名里
            if idx not in picked:      # 找一个还没被选中的
                picked.append(idx)
                break
    for idx in rrf(rankings):          # 剩余坑位按 RRF 顺序补齐
        if len(picked) >= top_k:
            break
        if idx not in picked:
            picked.append(idx)
    return picked[:top_k]


def main():
    load_dotenv()
    data = json.load(open(EVAL_PATH, encoding="utf-8"))
    items = data["multi_hop"]

    kb = KnowledgeBase()
    print(f"语料 {len(kb.chunks)} 个 chunk；多跳题 {len(items)} 道\n")

    api_key = os.getenv("LLM_API_KEY")
    if not api_key:
        print("需要 LLM_API_KEY 来做查询分解，请先配置 .env")
        return

    from openai import OpenAI
    client = OpenAI(api_key=api_key,
                    base_url=os.getenv("LLM_BASE_URL", "https://api.deepseek.com"))
    model = os.getenv("LLM_MODEL", "deepseek-chat")

    # 汇总用的累加器
    cov3 = cov5 = cov_d = 0.0
    all3 = all5 = all_d = 0
    gen_ok = 0
    rows = []

    print(f"{'问题':<26}{'Cov@3':>7}{'All@3':>7}{'Cov@5':>7}{'All@5':>7}{'Cov@拆':>8}{'All@拆':>8}{'生成':>6}")
    print("-" * 82)

    for it in items:
        q = it["q"]
        # 每个必需事实可能出现在多个 chunk 里（分块有重叠），所以用集合
        gold_sets = [kb.gold_indices(g) for g in it["golds"]]

        # ---------- A. 单查询：一次拿 5 个候选，再截前三 ----------
        hits5 = kb.retrieve(q, k=5)
        idx5 = [h[0] for h in hits5]
        c3, a3 = coverage(idx5[:3], gold_sets)
        c5, a5 = coverage(idx5, gold_sets)

        # ---------- B. 查询分解：每个子问题各检索 4 个，RRF 合并取前三 ----------
        subs = decompose(client, model, q)
        # 每个子问题取 6 个、候选池放大到 20，再用配额合并
        rankings = [[h[0] for h in kb.retrieve(s, k=6, candidates=20)] for s in subs]
        merged = quota_merge(rankings)
        cd, ad = coverage(merged, gold_sets)

        # ---------- 端到端：用合并后的片段生成，检查关键数字是否都出现 ----------
        ctx = [(kb.metas[i], kb.chunks[i]) for i in merged]
        try:
            ans = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": build_prompt(q, ctx)}],
                temperature=0.2,
            ).choices[0].message.content.strip()
            ok = all(norm(k) in norm(ans) for k in it["answer_keys"]) and "无法回答" not in ans
        except Exception as exc:
            ans, ok = f"[API 错误] {exc}", False

        cov3 += c3; cov5 += c5; cov_d += cd
        all3 += a3; all5 += a5; all_d += ad
        gen_ok += ok
        rows.append({"q": q, "sub_questions": subs, "answer": ans,
                     "cov3": c3, "all3": a3, "cov5": c5, "all5": a5,
                     "cov_decomp": cd, "all_decomp": ad, "gen_ok": ok})

        print(f"{q[:24]:<26}{c3:>7.2f}{('✓' if a3 else '✗'):>7}{c5:>7.2f}"
              f"{('✓' if a5 else '✗'):>7}{cd:>8.2f}{('✓' if ad else '✗'):>8}"
              f"{('✓' if ok else '✗'):>6}")

    n = len(items)
    print("-" * 82)
    print(f"Coverage@3 {cov3/n:.2f} | AllHit@3 {all3}/{n} | "
          f"Coverage@5 {cov5/n:.2f} | AllHit@5 {all5}/{n} | "
          f"分解 Coverage@3 {cov_d/n:.2f} | AllHit@3 {all_d}/{n} | 生成正确 {gen_ok}/{n}")

    # 把每题的拆解结果打出来，方便观察模型是怎么拆的
    print("\n【查询分解明细】")
    for r in rows:
        print(f"  {r['q'][:22]}")
        for s in r["sub_questions"]:
            print(f"    - {s}")

    json.dump({"items": rows,
               "summary": {"coverage_at_3": cov3/n, "all_hit_at_3": all3/n,
                           "coverage_at_5": cov5/n, "all_hit_at_5": all5/n,
                           "coverage_decomp_3": cov_d/n, "all_hit_decomp_3": all_d/n,
                           "gen_correct": gen_ok/n}},
              open(REPORT_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\n报告已写入 {REPORT_PATH}")


if __name__ == "__main__":
    main()
