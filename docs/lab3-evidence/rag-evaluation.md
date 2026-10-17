# Track B RAGAS evaluation

Judge model: `us.anthropic.claude-haiku-4-5-20251001-v1:0` (Bedrock, temperature 0, judge max_tokens raised to 4096, 2 parallel judge workers). Generator: `us.anthropic.claude-haiku-4-5-20251001-v1:0` (temperature 0.2). 3 runs per condition on all 4 harness cases. Cells still NaN after 2 re-runs: 0 (excluded from means, never counted as zero). The course staff no longer grade the original targets (0.80 / 0.75 / 0.70); scores are reported as measured.

## Per-case scores (mean over 3 runs)
| config | customer_id | faithfulness | answer_relevancy | context_recall |
|---|---|---|---|---|
| after | CUST-10000122 | 0.422 | 0.33 | 0.333 |
| after | CUST-10000317 | 0.467 | 0.279 | 1.0 |
| after | CUST-10000588 | 0.533 | 0.299 | 0.5 |
| after | CUST-10000904 | 0.5 | 0.143 | 0.2 |
| before | CUST-10000122 | 0.524 | 0.311 | 0.333 |
| before | CUST-10000317 | 0.244 | 0.28 | 0.75 |
| before | CUST-10000588 | 0.4 | 0.283 | 0.5 |
| before | CUST-10000904 | 0.458 | 0.176 | 0.4 |

## Mean and range across runs (mean of the 4 cases per run)
| config | faithfulness mean | faithfulness min | faithfulness max | answer_relevancy mean | answer_relevancy min | answer_relevancy max | context_recall mean | context_recall min | context_recall max |
|---|---|---|---|---|---|---|---|---|---|
| after | 0.481 | 0.45 | 0.508 | 0.263 | 0.255 | 0.267 | 0.508 | 0.508 | 0.508 |
| before | 0.407 | 0.35 | 0.451 | 0.262 | 0.256 | 0.276 | 0.496 | 0.496 | 0.496 |

## The one change: profile added as an extra judged context (BEFORE -> AFTER)
Faithfulness 0.407 -> 0.481 (delta +0.074): the change **helped**.
Answer relevancy 0.262 -> 0.263 (delta +0.000): made no measurable difference (within run-to-run noise).
Context recall 0.496 -> 0.508 (delta +0.012): made no measurable difference (within run-to-run noise).
Rationale: the judge can only credit a claim that appears in its contexts. Without the profile entry, every profile fact in the offer (the customer's tier, their top categories) is unsupported even though it is true. The course staff report about +-0.1 run-to-run noise on faithfulness with 4 cases, so deltas under about 0.05 should not be treated as real.

## What limits each metric
**Faithfulness** (weakest case: CUST-10000122, mean 0.422; its offer: "Your Platinum status unlocks early access to sales 48 hours before the general public, plus unlimited free gear repair on eligible items—benefits that reward your loyalty. We'd love to help you find your next great outdoor or electronics purchase with these exclusive perks."; retrieved chunks ['loyalty-program-terms.md#2', 'loyalty-program-terms.md#5', 'loyalty-program-terms.md#4', 'customer-faq.md#7', 'return-policy.md#1', 'return-policy.md#0']). Every claim the contexts do not support counts against it: filler and invented terms, benefits paraphrased beyond the retrieved text, and tier framing such as "close to Gold" for CUST-10000588, which is only supported if the chunk stating the Gold threshold was retrieved. In the weakest case (CUST-10000122, Platinum) the benefit claims themselves (48-hour early access, unlimited gear repair) match the harness ground truth and the loyalty chunks, so the likely lost points are the filler around them: the closing sentence ("We'd love to help you find your next great outdoor or electronics purchase...") and marketing wording ("reward your loyalty", "next great" not found anywhere in the policy corpus). The system prompt forbids filler, yet Haiku still adds it. The offer also omits the $100 annual gear credit that the ground truth names as the strongest lever.
**Answer relevancy** (weakest case: CUST-10000904, mean 0.143). RAGAS reverse-generates questions from the answer and compares them to the original question. The harness questions are instructions ("Generate a retention offer for this ... member ...") and the answers are marketing copy, so reverse-generated questions rarely resemble them even when the offer is correct. The course staff measured about 0.73 as the ceiling for a well-matched pair.
**Context recall** (weakest case: CUST-10000904, mean 0.200). The ground truths contain sentences found in no policy document: for CUST-10000122 "a heavy percentage discount destroys margin on a $447 average order", and for CUST-10000588 the commentary that near-threshold framing is "legitimate and effective" and the note about the feature-store tier versus POL-LOY-011. Those can never be recalled from any context, so recall is capped below 1 regardless of retrieval quality (staff measured 0.61-0.67 with the entire corpus as context).

## Weakest recall / relevancy case: CUST-10000904 (Bronze)
Its offer (last AFTER run): "Your loyalty points expire in 14 days—make a purchase in Apparel to reset the clock and keep your balance active. As a Bronze member, you earn points on every purchase, and your next order could move you closer to Silver tier benefits like free shipping on orders over $50." Of the Bronze specifics in the ground truth, the offer omits: the $75 free-shipping threshold, the $5 birthday reward, the $7.95 return fee, a cross-category angle. It talks about points expiry and Silver benefits instead, so almost no ground-truth statement can be matched, which is why recall is lowest here. Its "expire in 14 days" claim also hurts faithfulness: loyalty-program-terms.md section 3.1 says points expire 18 months after the most recent qualifying purchase and that warnings are sent 60 and 14 days before expiry, so the offer misapplied the 14-day warning window as the expiry. The claim that the next order "could move you closer to Silver" has no supporting context either. Relevancy is lowest because the questions RAGAS reverse-generates from this answer (about point expiry) look nothing like the instruction to write a retention offer for a Bronze member.
