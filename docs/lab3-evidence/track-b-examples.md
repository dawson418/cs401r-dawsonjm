# Track B examples

## Correct behavior (5 input/output pairs)

### Example 1
- Profile: `{'churn_probability': 0.71, 'loyalty_tier': 'Bronze', 'total_lifetime_value': 420.0, 'category_diversity_score': 0.2, 'top_categories': ['Home', 'Toys']}`
- Offer: Your Home purchases have been a great fit for your account, and we'd love to have you back. As a Bronze member, you earn points on every purchase, and any qualifying buy resets your points expiration clock—so your current balance stays active. Come back soon to keep building toward your next tier.
- Retrieved chunk IDs: ['loyalty-program-terms.md#4', 'customer-faq.md#2', 'loyalty-program-terms.md#3', 'customer-faq.md#7', 'return-policy.md#1', 'return-policy.md#0']
- Terms in the offer not found in any retrieved context (auto-lint): none

### Example 2
- Profile: `{'churn_probability': 0.64, 'loyalty_tier': 'Silver', 'total_lifetime_value': 1800.0, 'category_diversity_score': 0.4, 'top_categories': ['Apparel', 'Footwear']}`
- Offer: As a Silver member, you earn points 25% faster on every purchase and get free standard shipping on orders over $50. We'd love to see you back shopping Apparel with us soon.
- Retrieved chunk IDs: ['loyalty-program-terms.md#4', 'loyalty-program-terms.md#0', 'customer-faq.md#2', 'customer-faq.md#7', 'return-policy.md#1', 'return-policy.md#0']
- Terms in the offer not found in any retrieved context (auto-lint): ['25%']

### Example 3
- Profile: `{'churn_probability': 0.58, 'loyalty_tier': 'Gold', 'total_lifetime_value': 4200.0, 'category_diversity_score': 0.7, 'top_categories': ['Electronics', 'Outdoor']}`
- Offer: Your Gold membership unlocks always-free standard shipping and free return shipping on all orders, plus early access to our sales 24 hours before they go live. We'd love to have you back shopping Electronics with us soon.
- Retrieved chunk IDs: ['loyalty-program-terms.md#4', 'loyalty-program-terms.md#1', 'customer-faq.md#2', 'customer-faq.md#7', 'return-policy.md#1', 'return-policy.md#0']
- Terms in the offer not found in any retrieved context (auto-lint): none

### Example 4
- Profile: `{'churn_probability': 0.55, 'loyalty_tier': 'Platinum', 'total_lifetime_value': 9800.0, 'category_diversity_score': 0.8, 'top_categories': ['Electronics', 'Home']}`
- Offer: Your Platinum membership includes unlimited free gear repair and a $100 annual gear credit each January, plus you earn 2 points per $1 on all qualifying purchases—redeemable for rewards in-store or online. We'd love to have you back shopping Electronics with us.
- Retrieved chunk IDs: ['loyalty-program-terms.md#2', 'loyalty-program-terms.md#5', 'loyalty-program-terms.md#4', 'customer-faq.md#7', 'return-policy.md#1', 'return-policy.md#0']
- Terms in the offer not found in any retrieved context (auto-lint): none

### Example 5
- Profile: `{'churn_probability': 0.69, 'loyalty_tier': 'Silver', 'total_lifetime_value': 2100.0, 'category_diversity_score': 0.1, 'top_categories': ['Beauty']}`
- Offer: Your Silver tier membership unlocks 12-hour early access to our sales and free standard shipping on orders over $50—benefits that reward your loyalty. As a Beauty category shopper, you'll want to catch our upcoming promotions first, so keep an eye on your inbox for exclusive Silver member previews.
- Retrieved chunk IDs: ['loyalty-program-terms.md#4', 'loyalty-program-terms.md#0', 'customer-faq.md#2', 'customer-faq.md#7', 'return-policy.md#1', 'return-policy.md#0']
- Terms in the offer not found in any retrieved context (auto-lint): ['exclusive']

## Failure cases (stress profiles)

### Failure case 1
- Profile: `{'churn_probability': 0.6, 'loyalty_tier': 'Platinum', 'total_lifetime_value': 2100.0, 'category_diversity_score': 0.3, 'top_categories': ['Apparel']}`
- Offer: Your Platinum membership earns 2 points per $1 on Apparel purchases, and you have unlimited free gear repair available year-round. As a valued Platinum member, you also enjoy your loyalty benefits including early access to sales and an annual $100 gear credit each January.
- Retrieved chunk IDs: ['loyalty-program-terms.md#2', 'loyalty-program-terms.md#5', 'loyalty-program-terms.md#4', 'customer-faq.md#7', 'return-policy.md#1', 'return-policy.md#0']
- Terms in the offer not found in any retrieved context (auto-lint): none

**Risk:** the feature-store tier comes from lifetime value, while policy defines tier by trailing-12-month spend, so a Platinum label on low lifetime value may not match the customer's real tier, and the offer may state a Platinum-only benefit. **Proposed fix:** read tier from the system of record at generation time; until then, phrase tier benefits conditionally ("if you are Platinum...") and add a post-generation check that every named benefit appears in a retrieved chunk for that tier.

### Failure case 2
- Profile: `{'churn_probability': 0.6, 'loyalty_tier': 'Gold', 'total_lifetime_value': 4000.0, 'category_diversity_score': 0.5, 'top_categories': []}`
- Offer: Your Gold tier gives you always-free standard shipping and free return shipping on every order, plus early access to sales 24 hours before they go live. We'd love to have you back shopping with us.
- Retrieved chunk IDs: ['loyalty-program-terms.md#4', 'loyalty-program-terms.md#1', 'customer-faq.md#2', 'customer-faq.md#7', 'return-policy.md#1', 'return-policy.md#0']
- Terms in the offer not found in any retrieved context (auto-lint): none

**Risk:** with no top categories the model may invent a category the customer never bought. **Proposed fix:** when top_categories is empty, fall back to the store's best-selling category from a fixed list and label it as general, and reject offers whose category is not in an allowed list.

_These two cases are stress tests: read the observed offer and lint line above. If the model handled the case correctly, the recorded behavior is a near miss that the proposed fix hardens against._

## Observed failure during development (fixed)
- Profile: Gold tier, top categories Electronics and Outdoor.
- Observed offer: "Your Gold membership includes free return shipping and a 60-day return window on all purchases..."
- Why it failed: the 60-day window is Platinum-only (Gold is 30 days). Retrieval returned chunks covering several tiers, and the generator attributed another tier's benefit to this customer. My auto-lint did not flag it because "60-day" appears in the retrieved Platinum text, so it counted as supported.
- Fix applied: the system prompt now requires a benefit's source sentence to name the customer's own tier, forbids other tiers' benefits, and forbids mentioning return windows or numeric terms not stated for the customer's tier. Proposed further fix: filter retrieved chunks by tier metadata before generation, and add a lint that checks each benefit against the chunk naming the customer's tier, not any retrieved chunk.
- Evaluation was re-run after this fix; scores are in rag-evaluation.md.

## Observed failure 2 (found in the RAGAS run, Bronze customer CUST-10000904)
- Observed offer: "Your loyalty points expire in 14 days—make a purchase in Apparel to reset the clock and keep your balance active. As a Bronze member, you earn points on every purchase, and your next order could move you closer to Silver tier benefits like free shipping on orders over $50."
- Why it failed: the number is real but misapplied. loyalty-program-terms.md section 3.1 says points expire 18 months after the member's most recent qualifying purchase and that warnings go out at 60 and 14 days before expiry; the offer turned the 14-day warning into "points expire in 14 days", a false urgency claim. It also implies the customer is close to Silver, which no retrieved context supports. A substring check for "14 days" passes because the phrase is in the corpus, the same blind spot that let the 60-day claim through. The failure is intermittent at temperature 0.2: other generations for the same customer were accurate.
- Proposed fix: (1) claim-level verification: split each offer into claims and have a temperature-0 verifier call check each numeric or time claim against the chunk it came from, regenerating (at most 3 times) when a claim is unsupported or applies to a different thing than the chunk says; (2) treat customer-specific state such as a points-expiry date as data read from the system of record and passed in, never inferred by the model, and forbid urgency or expiry language when that date is not supplied.
