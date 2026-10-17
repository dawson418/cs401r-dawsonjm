"""Track B evaluation: provided RAGAS harness, BEFORE/AFTER adding the customer profile as a judged context."""
import argparse, copy, sys, time
import pandas as pd

sys.path[:0] = [".", "evaluation"]  # harness may live at repo root or evaluation/
import evaluation_harness as eh
from rag.pipeline import generate_offer
from ragas.run_config import RunConfig

METRICS = ["faithfulness", "answer_relevancy", "context_recall"]
EV = "docs/lab3-evidence"

def build_judge(model_id, region="us-east-1"):
    # Same as the harness judge, but max_tokens raised so long judge outputs don't hit LLMDidNotFinishException.
    from langchain_aws import ChatBedrock, BedrockEmbeddings
    from ragas.llms import LangchainLLMWrapper
    from ragas.embeddings import LangchainEmbeddingsWrapper
    llm = LangchainLLMWrapper(ChatBedrock(model_id=model_id, region_name=region,
                                          model_kwargs={"temperature": 0, "max_tokens": 4096}))
    emb = LangchainEmbeddingsWrapper(BedrockEmbeddings(model_id="amazon.titan-embed-text-v2:0", region_name=region))
    return llm, emb
eh.build_bedrock_judge = build_judge

_orig_evaluate = eh.evaluate
def _evaluate(*a, **k):  # fewer parallel judge calls -> fewer throttling NaNs
    k.setdefault("run_config", RunConfig(max_workers=2, timeout=240, max_retries=8))
    return _orig_evaluate(*a, **k)
eh.evaluate = _evaluate

CHUNKS = {}
def make_fn(include_profile):
    def fn(ctx, question):
        o = generate_offer(ctx)
        CHUNKS[question] = o["chunk_ids"]
        return {"answer": o["offer"], "contexts": o["contexts"] if include_profile else o["policy_contexts"]}
    return fn

def mcol(df, m):
    return next((c for c in df.columns if c == m), None) or next((c for c in df.columns if m in c), None)

def one_run(include_profile, model_id, region):
    cases = copy.deepcopy(eh.OFFER_TEST_CASES)
    ev = eh.RAGEvaluator(make_fn(include_profile), bedrock_model_id=model_id, region=region)
    df = ev.run(cases).reset_index(drop=True)
    cols = {m: mcol(df, m) for m in METRICS}
    for i, tc in enumerate(cases):
        for attempt in (1, 2):
            if not any(pd.isna(df.at[i, cols[m]]) for m in METRICS):
                break
            print(f"  NaN for {tc.customer_id}: re-running that case (attempt {attempt})")
            time.sleep(10)
            sub = ev.run([tc]).reset_index(drop=True)
            for m in METRICS:
                df.at[i, cols[m]] = sub.at[0, mcol(sub, m)]
    return [{"customer_id": tc.customer_id, **{m: df.at[i, cols[m]] for m in METRICS},
             "offer": tc.generated_answer, "chunk_ids": CHUNKS.get(tc.question)} for i, tc in enumerate(cases)]

def tbl(df):
    df = df.reset_index()
    return "\n".join(["| " + " | ".join(map(str, df.columns)) + " |", "|" + "---|" * len(df.columns)] +
                     ["| " + " | ".join(str(round(v, 3)) if isinstance(v, float) else str(v) for v in r) + " |" for r in df.values])

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--model-id", default=eh.DEFAULT_BEDROCK_MODEL_ID)
    ap.add_argument("--region", default="us-east-1")
    a = ap.parse_args()
    rows = []
    for r in range(1, a.runs + 1):
        for cfg, inc in (("before", False), ("after", True)):
            print(f"\n===== run {r}/{a.runs}: {cfg} (profile in judged contexts: {inc}) =====")
            for row in one_run(inc, a.model_id, a.region):
                rows.append({"config": cfg, "run": r, "judge_model": a.model_id, **row})
            pd.DataFrame(rows).to_csv(f"{EV}/rag_eval.csv", index=False)  # saved after every run
            time.sleep(5)
    res = pd.DataFrame(rows)
    nan_left = int(res[METRICS].isna().sum().sum())
    per_case = res.groupby(["config", "customer_id"])[METRICS].mean()
    run_means = res.groupby(["config", "run"])[METRICS].mean()
    summ = run_means.groupby("config").agg(["mean", "min", "max"])
    summ.columns = [f"{m} {s}" for m, s in summ.columns]
    mean = run_means.groupby("config").mean()
    d = mean.loc["after"] - mean.loc["before"]
    def verdict(x):
        return "helped" if x > 0.05 else "hurt" if x < -0.05 else "made no measurable difference (within run-to-run noise)"
    after = res[res.config == "after"]
    def weakest(m):
        cid = after.groupby("customer_id")[m].mean().idxmin()
        sub = after[after.customer_id == cid]
        return cid, sub[m].mean(), sub.iloc[-1].offer, sub.iloc[-1].chunk_ids
    wf, wr, wc = weakest("faithfulness"), weakest("answer_relevancy"), weakest("context_recall")
    md = f"""# Track B RAGAS evaluation

Judge model: `{a.model_id}` (Bedrock, temperature 0, judge max_tokens raised to 4096, 2 parallel judge workers). Generator: `us.anthropic.claude-haiku-4-5-20251001-v1:0` (temperature 0.2). {a.runs} runs per condition on all 4 harness cases. Cells still NaN after 2 re-runs: {nan_left} (excluded from means, never counted as zero). The course staff no longer grade the original targets (0.80 / 0.75 / 0.70); scores are reported as measured.

## Per-case scores (mean over {a.runs} runs)
{tbl(per_case)}

## Mean and range across runs (mean of the 4 cases per run)
{tbl(summ)}

## The one change: profile added as an extra judged context (BEFORE -> AFTER)
Faithfulness {mean.loc['before','faithfulness']:.3f} -> {mean.loc['after','faithfulness']:.3f} (delta {d['faithfulness']:+.3f}): the change **{verdict(d['faithfulness'])}**.
Answer relevancy {mean.loc['before','answer_relevancy']:.3f} -> {mean.loc['after','answer_relevancy']:.3f} (delta {d['answer_relevancy']:+.3f}): {verdict(d['answer_relevancy'])}.
Context recall {mean.loc['before','context_recall']:.3f} -> {mean.loc['after','context_recall']:.3f} (delta {d['context_recall']:+.3f}): {verdict(d['context_recall'])}.
Rationale: the judge can only credit a claim that appears in its contexts. Without the profile entry, every profile fact in the offer (the customer's tier, their top categories) is unsupported even though it is true. The course staff report about +-0.1 run-to-run noise on faithfulness with 4 cases, so deltas under about 0.05 should not be treated as real.

## What limits each metric
**Faithfulness** (weakest case: {wf[0]}, mean {wf[1]:.3f}; its offer: "{wf[2]}"; retrieved chunks {wf[3]}). Every claim the contexts do not support counts against it: filler and invented terms, benefits paraphrased beyond the retrieved text, and tier framing such as "close to Gold" for CUST-10000588, which is only supported if the chunk stating the Gold threshold was retrieved. Check this offer sentence by sentence against its chunks to name the unsupported claims.
**Answer relevancy** (weakest case: {wr[0]}, mean {wr[1]:.3f}). RAGAS reverse-generates questions from the answer and compares them to the original question. The harness questions are instructions ("Generate a retention offer for this ... member ...") and the answers are marketing copy, so reverse-generated questions rarely resemble them even when the offer is correct. The course staff measured about 0.73 as the ceiling for a well-matched pair.
**Context recall** (weakest case: {wc[0]}, mean {wc[1]:.3f}). The ground truths contain sentences found in no policy document: for CUST-10000122 "a heavy percentage discount destroys margin on a $447 average order", and for CUST-10000588 the commentary that near-threshold framing is "legitimate and effective" and the note about the feature-store tier versus POL-LOY-011. Those can never be recalled from any context, so recall is capped below 1 regardless of retrieval quality (staff measured 0.61-0.67 with the entire corpus as context).
"""
    open(f"{EV}/rag-evaluation.md", "w").write(md)
    print(f"\nwrote {EV}/rag_eval.csv and {EV}/rag-evaluation.md")

if __name__ == "__main__":
    main()
