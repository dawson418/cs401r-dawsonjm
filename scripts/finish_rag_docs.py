import glob, os, pandas as pd
EV = "docs/lab3-evidence"
ex, of = f"{EV}/track-b-examples.md", f"{EV}/observed-failures.md"
corpus = " ".join(open(f, encoding="utf-8").read().lower()
                  for f in glob.glob("northstar-policy-docs/**/*", recursive=True) if f.endswith((".md", ".txt")))
assert "14 days" in corpus and "18 months" in corpus, "corpus no longer has the points-expiry clause; revise the text below"
df = pd.read_csv(f"{EV}/rag_eval.csv")
offer = str(df[(df.config == "after") & (df.customer_id == "CUST-10000904")].iloc[-1].offer)
checks = {"the $75 free-shipping threshold": "75", "the $5 birthday reward": "birthday",
          "the $7.95 return fee": "7.95", "a cross-category angle": "categor"}
absent = [k for k, v in checks.items() if v not in offer.lower()]

# 1) keep the 60-day failure block safe
if not os.path.exists(of):
    m = open(ex).read(); k = "## Observed failure during development (fixed)"
    assert k in m, "60-day failure block not found in track-b-examples.md"
    open(of, "w").write(k + m.split(k, 1)[1])

# 2) rewrite the Bronze section of rag-evaluation.md
p = f"{EV}/rag-evaluation.md"
s = open(p).read().split("\n## Weakest recall / relevancy case")[0]
s += ("\n## Weakest recall / relevancy case: CUST-10000904 (Bronze)\n"
      f"Its offer (last AFTER run): \"{offer}\" Of the Bronze specifics in the ground truth, the offer omits: {', '.join(absent) or 'none'}. "
      "It talks about points expiry and Silver benefits instead, so almost no ground-truth statement can be matched, which is why recall is lowest here. "
      "Its \"expire in 14 days\" claim also hurts faithfulness: loyalty-program-terms.md section 3.1 says points expire 18 months after the most recent "
      "qualifying purchase and that warnings are sent 60 and 14 days before expiry, so the offer misapplied the 14-day warning window as the expiry. "
      "The claim that the next order \"could move you closer to Silver\" has no supporting context either. Relevancy is lowest because the questions RAGAS "
      "reverse-generates from this answer (about point expiry) look nothing like the instruction to write a retention offer for a Bronze member.\n")
open(p, "w").write(s)

# 3) add failure 2 once
o = open(of).read()
if "## Observed failure 2" not in o:
    o += ("\n## Observed failure 2 (found in the RAGAS run, Bronze customer CUST-10000904)\n"
          f"- Observed offer: \"{offer}\"\n"
          "- Why it failed: the number is real but misapplied. loyalty-program-terms.md section 3.1 says points expire 18 months after the member's most recent "
          "qualifying purchase and that warnings go out at 60 and 14 days before expiry; the offer turned the 14-day warning into \"points expire in 14 days\", "
          "a false urgency claim. It also implies the customer is close to Silver, which no retrieved context supports. A substring check for \"14 days\" passes "
          "because the phrase is in the corpus, the same blind spot that let the 60-day claim through. The failure is intermittent at temperature 0.2: other "
          "generations for the same customer were accurate.\n"
          "- Proposed fix: (1) claim-level verification: split each offer into claims and have a temperature-0 verifier call check each numeric or time claim "
          "against the chunk it came from, regenerating (at most 3 times) when a claim is unsupported or applies to a different thing than the chunk says; "
          "(2) treat customer-specific state such as a points-expiry date as data read from the system of record and passed in, never inferred by the model, and "
          "forbid urgency or expiry language when that date is not supplied.\n")
    open(of, "w").write(o)
head = open(ex).read().split("\n## Observed failure")[0]
open(ex, "w").write(head + "\n" + open(of).read())
print("done. Bronze offer used:", offer)
