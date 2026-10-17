import re
from rag.pipeline import generate_offer, SAMPLE_PROFILES, STRESS_PROFILES
PAT = re.compile(r"\d+\s*%|\$\s*\d+|\b\d+[- ]days?\b|exclusive|bonus|coupon|birthday", re.I)
def lint(o):
    ctx = " ".join(o["contexts"]).lower()
    return sorted({m.group(0) for m in PAT.finditer(o["offer"]) if m.group(0).lower() not in ctx})
def block(i, p, kind):
    o = generate_offer(p)
    bad = lint(o)
    return (f"### {kind} {i}\n- Profile: `{p}`\n- Offer: {o['offer']}\n- Retrieved chunk IDs: {o['chunk_ids']}\n"
            f"- Terms in the offer not found in any retrieved context (auto-lint): {bad or 'none'}\n\n")
md = "# Track B examples\n\n## Correct behavior (5 input/output pairs)\n\n"
for i, p in enumerate(SAMPLE_PROFILES, 1):
    md += block(i, p, "Example")
md += "## Failure cases (stress profiles)\n\n"
md += block(1, STRESS_PROFILES[0], "Failure case")
md += ("**Risk:** the feature-store tier comes from lifetime value, while policy defines tier by trailing-12-month spend, so a Platinum "
       "label on low lifetime value may not match the customer's real tier, and the offer may state a Platinum-only benefit. "
       "**Proposed fix:** read tier from the system of record at generation time; until then, phrase tier benefits conditionally "
       "(\"if you are Platinum...\") and add a post-generation check that every named benefit appears in a retrieved chunk for that tier.\n\n")
md += block(2, STRESS_PROFILES[1], "Failure case")
md += ("**Risk:** with no top categories the model may invent a category the customer never bought. "
       "**Proposed fix:** when top_categories is empty, fall back to the store's best-selling category from a fixed list and label it as general, "
       "and reject offers whose category is not in an allowed list.\n\n"
       "_These two cases are stress tests: read the observed offer and lint line above. If the model handled the case correctly, the recorded "
       "behavior is a near miss that the proposed fix hardens against._\n")
open("docs/lab3-evidence/track-b-examples.md", "w").write(md)
print("wrote docs/lab3-evidence/track-b-examples.md")
