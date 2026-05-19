# Outreach — Ringo + 6 Power Users
## Post-May-6-Outage Retention Push (drafted May 19, 2026)

---

## Context Recap (for sender)

- **May 6 outage timeline:** Wrong-reference validator over-rejected legit Gemini outputs (~16:00) → soft-log hotfix (~16:15) → unrelated production 520 outage discovered (~17:35) → restart restored service (~18:42) → 3 stability fixes deployed afterward.
- **Ringo** sent the first video evidence (Medium-stencil "Regeneration Failed" loop) that surfaced the validator bug. Already comped **25 credits** via `POST /api/admin/comp-credits`.
- **Power users** = top paid users by stencil generation activity over the last 30 days. Use the new `/api/admin/top-power-users?days=30&limit=10` endpoint (admin auth required) to surface the list after the next prod deploy. Until then, pick from any combination of:
  - Active paid subscribers who generated stencils during the May 6 outage window (16:00–18:42 UTC)
  - Users on Booked-Out / The-Shop tiers (highest LTV)
  - Anyone whose ticket / message landed during the incident

---

## Message 1 — Ringo (already comped, send confirmation)

**Channel:** Email (`ringopiniontattoo@gmail.com`) or whatever channel he sent the video on.
**Tone:** Direct, builder-to-artist, not corporate. Acknowledge the video evidence helped fix the bug for everyone.

---

> **Subject:** Found it. Fixed it. Your comp credits are in.
>
> Hey Ringo,
>
> Real quick — the "Regeneration Failed" loop you sent the video of on Medium yesterday wasn't a fluke and it wasn't your photos. There was a bug in the new quality-check we shipped that morning that was rejecting good stencils as if they were bad ones. Your video was the smoking gun that let me trace it.
>
> Three things:
>
> 1. **It's fixed.** The check is in observation-only mode now. No more rejections.
> 2. **I comped 25 credits to your account** as an apology for the wasted attempts. Should already be there.
> 3. **If you have a minute,** run the same photos again and tell me if you get a result you'd actually put on someone. Even better, tell me where it falls short — I'm tuning Heavy mode this week and your eye on it would matter.
>
> Sorry for the friction. Thanks for sending the video instead of just leaving a 1-star review.
>
> — Brian
> Body Bound

---

## Message 2 — Power Users (generic, personalize per user)

**Channel:** Email preferred (use the email on file). For Apple-only users without an email, skip — Apple doesn't expose it.
**Tone:** Personal, brief, no marketing speak. Goal: retain the user + collect a quality signal.

**Personalization slots:**
- `{first_name}` — pull from `users.name` first token, or omit and start with "Hey,"
- `{tier_label}` — "Walk-In" / "Booked-Out" / "The Shop" (titlecase from `tier`)
- `{recent_session_count}` — from `top-power-users.session_count`

---

> **Subject:** Quick note from Body Bound — bug fix + a few comp credits
>
> Hey{first_name_or_empty},
>
> If you tried to generate a stencil on May 6 between roughly 11 AM and 2 PM EST and got "Regeneration Failed" over and over — that was a bug on our end, not your photo. A new quality-check I deployed that morning was over-rejecting good outputs. It's been off since the same afternoon and the underlying math is fixed.
>
> Two things:
>
> 1. **I'm comping you 10 credits** for the friction. Should be on your account next time you open the app.
> 2. **You're on {tier_label} and you've been one of the most active accounts this month ({recent_session_count} sessions).** That means a lot. If anything ever feels off — a stencil missing detail, a charge that didn't seem right, a feature you'd kill for — reply to this email. I read every one.
>
> Thanks for sticking around through the bumps.
>
> — Brian
> Body Bound

---

## Comp Credits Script (after identifying the 6)

```bash
# Step 1: identify the list
PROD="https://bodybound-subs.emergent.host"
TOKEN=$(curl -s -X POST "$PROD/api/admin-auth/login" \
  -H "Content-Type: application/json" \
  -d '{"email":"bodyboundstencil@yahoo.com","password":"Body.Bound.Admin.72410"}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['token'])")

curl -s -X GET "$PROD/api/admin/top-power-users?days=30&limit=10" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool

# Step 2: pick 6 (Brian's judgment). Comp them 10 credits each.
for EMAIL in user1@x.com user2@x.com user3@x.com user4@x.com user5@x.com user6@x.com; do
  curl -s -X POST "$PROD/api/admin/comp-credits" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d "{\"email\":\"$EMAIL\",\"credits\":10,\"reason\":\"May 6 outage apology — power user retention\"}"
  echo ""  # newline
done

# Step 3: verify via comp-credits-history
curl -s -X GET "$PROD/api/admin/comp-credits-history?days=7" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

**Reasoning on amounts:**
- **Ringo:** 25 credits (already granted) — sent video, lost real billable hours during the outage.
- **Power users:** 10 credits each — meaningful but not over-comped. Walk-In is 125/month, so 10 = ~8% of their monthly cap; Booked-Out is 500, so 10 = ~2% — still feels like a deliberate gift, not a pittance.
- **Total comp cost:** 25 + (6 × 10) = 85 credits across 7 accounts. At ~$0.15 LLM-cost-per-credit absolute ceiling, downside is ~$13. Cheap retention insurance.

---

## After Sending — Track Replies

Create a simple section below for actual responses (date, user, what they said, action taken). Use this to inform the next month's roadmap.

| Date | User | Tier | Reply Summary | Action Taken |
|------|------|------|---------------|--------------|
|      |      |      |               |              |

---

**Status:** Templates ready. Brian to identify 6 power users (after next prod deploy enables the `top-power-users` endpoint) and send messages manually. Ringo's message can go out immediately — comp is already applied.
