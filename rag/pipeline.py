import glob, json, os, time
import boto3, faiss, numpy as np
from botocore.exceptions import ClientError

REGION = os.environ.get("AWS_REGION", "us-east-1")
EMBED_MODEL = "amazon.titan-embed-text-v2:0"
GEN_MODEL = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
DOCS_DIR, CACHE = "northstar-policy-docs", "rag/.cache"
CHUNK_WORDS, OVERLAP_WORDS = 160, 40  # ~1 policy section per chunk; overlap keeps clauses intact
_br = boto3.client("bedrock-runtime", region_name=REGION)
_state = {}

SAMPLE_PROFILES = [
    {"churn_probability": 0.71, "loyalty_tier": "Bronze", "total_lifetime_value": 420.0, "category_diversity_score": 0.2, "top_categories": ["Home", "Toys"]},
    {"churn_probability": 0.64, "loyalty_tier": "Silver", "total_lifetime_value": 1800.0, "category_diversity_score": 0.4, "top_categories": ["Apparel", "Footwear"]},
    {"churn_probability": 0.58, "loyalty_tier": "Gold", "total_lifetime_value": 4200.0, "category_diversity_score": 0.7, "top_categories": ["Electronics", "Outdoor"]},
    {"churn_probability": 0.55, "loyalty_tier": "Platinum", "total_lifetime_value": 9800.0, "category_diversity_score": 0.8, "top_categories": ["Electronics", "Home"]},
    {"churn_probability": 0.69, "loyalty_tier": "Silver", "total_lifetime_value": 2100.0, "category_diversity_score": 0.1, "top_categories": ["Beauty"]},
]
STRESS_PROFILES = [
    {"churn_probability": 0.6, "loyalty_tier": "Platinum", "total_lifetime_value": 2100.0, "category_diversity_score": 0.3, "top_categories": ["Apparel"]},
    {"churn_probability": 0.6, "loyalty_tier": "Gold", "total_lifetime_value": 4000.0, "category_diversity_score": 0.5, "top_categories": []},
]

def _embed(text):
    r = _br.invoke_model(modelId=EMBED_MODEL, body=json.dumps({"inputText": text, "dimensions": 1024, "normalize": True}))
    return json.loads(r["body"].read())["embedding"]

def _chunk(name, text):
    w, step, out = text.split(), CHUNK_WORDS - OVERLAP_WORDS, []
    for i, s in enumerate(range(0, max(len(w), 1), step)):
        piece = " ".join(w[s:s + CHUNK_WORDS])
        if piece:
            out.append({"id": f"{name}#{i}", "source": name, "text": piece})
        if s + CHUNK_WORDS >= len(w):
            break
    return out

def _load():
    if _state:
        return _state["index"], _state["chunks"]
    ip, cp = f"{CACHE}/index.faiss", f"{CACHE}/chunks.json"
    if os.path.exists(ip) and os.path.exists(cp):
        _state["index"], _state["chunks"] = faiss.read_index(ip), json.load(open(cp))
    else:
        chunks = []
        for p in sorted(glob.glob(f"{DOCS_DIR}/**/*", recursive=True)):
            if os.path.isfile(p) and p.endswith((".md", ".txt")):
                chunks += _chunk(os.path.basename(p), open(p, encoding="utf-8").read())
        vecs = np.array([_embed(c["text"]) for c in chunks], dtype="float32")
        index = faiss.IndexFlatIP(vecs.shape[1]); index.add(vecs)
        os.makedirs(CACHE, exist_ok=True)
        faiss.write_index(index, ip); json.dump(chunks, open(cp, "w"))
        _state["index"], _state["chunks"] = index, chunks
        print(f"indexed {len(chunks)} chunks")
    return _state["index"], _state["chunks"]

def retrieve(query, k=3):
    index, chunks = _load()
    _, ids = index.search(np.array([_embed(query)], dtype="float32"), k)
    return [chunks[i] for i in ids[0] if i >= 0]

SYSTEM = """You write one retention offer for a retail customer.
- Exactly 2-3 sentences. No greeting and no filler such as "we've missed you".
- Use ONLY facts stated in POLICY CONTEXT or CUSTOMER PROFILE. Never invent discounts, percentages, coupons, bonus points, minimum spends, deadlines or expiry windows.
- Mention a loyalty or shipping benefit only if POLICY CONTEXT states it for the customer's tier; if unsure, say "your loyalty benefits" generically.
- Never state the churn probability or lifetime value.
- Recommend one specific product category taken from the customer's top categories (if none are given, do not name a category).
- Attribute a benefit to the customer's tier only if the POLICY CONTEXT sentence names that exact tier. Never mention benefits that belong to other tiers (for example a Platinum-only 60-day return window).
- Do not mention return windows or return shipping at all, and do not state any number of days or dollars unless that figure appears in POLICY CONTEXT for the customer's own tier."""

def generate_offer(profile):
    tier = profile["loyalty_tier"]
    cats = ", ".join(profile.get("top_categories") or []) or "none"
    seen, hits = set(), []
    for q in (f"{tier} loyalty tier benefits", "return window and free shipping policy"):
        for c in retrieve(q, 3):
            if c["id"] not in seen:
                seen.add(c["id"]); hits.append(c)
    prof = (f"Customer profile: loyalty_tier={tier}; total_lifetime_value={profile['total_lifetime_value']}; "
            f"category_diversity_score={profile['category_diversity_score']}; "
            f"predicted_churn_probability={profile['churn_probability']}; top_categories={cats}")
    policy = [c["text"] for c in hits]
    user = "POLICY CONTEXT:\n" + "\n---\n".join(f"[{c['id']}] {c['text']}" for c in hits) + f"\n\nCUSTOMER PROFILE:\n{prof}\n\nWrite the offer."
    for attempt in range(6):
        try:
            r = _br.converse(modelId=GEN_MODEL, system=[{"text": SYSTEM}],
                             messages=[{"role": "user", "content": [{"text": user}]}],
                             inferenceConfig={"maxTokens": 300, "temperature": 0.2})  # temperature OR topP, never both
            break
        except ClientError as e:
            if e.response["Error"]["Code"] not in ("ThrottlingException", "ModelErrorException") or attempt == 5:
                raise
            time.sleep(2 ** attempt)
    return {"offer": r["output"]["message"]["content"][0]["text"].strip(),
            "policy_contexts": policy, "profile_context": prof,
            "contexts": policy + [prof], "chunk_ids": [c["id"] for c in hits]}

if __name__ == "__main__":
    out = generate_offer(SAMPLE_PROFILES[2])
    print(out["offer"]); print(out["chunk_ids"])
