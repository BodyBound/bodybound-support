"""Validation helper: dump a user's paywall / subscription / credit state.

Used during QA paywall testing to quickly answer:
  - current tier
  - available credits / total cycle credits
  - last_product_id / last_event / last_refill_at
  - bypass / received_temp_credits flags
  - revenuecat_customer_id
  - most recent stencils timestamp

Usage:
    python3 /app/backend/scripts/inspect_user.py <email>
    python3 /app/backend/scripts/inspect_user.py bodyboundstencilapp@gmail.com

Or pass multiple:
    python3 /app/backend/scripts/inspect_user.py a@x.com b@x.com
"""
import asyncio
import json
import os
import sys

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv('/app/backend/.env')


async def dump(db, email: str) -> None:
    print(f"\n{'=' * 72}")
    print(f"  {email}")
    print(f"{'=' * 72}")

    user = await db.users.find_one({'email': email}, {'_id': 0})
    if not user:
        print("  ❌ No user record — account does not exist.")
        return

    user_id = user['user_id']
    sub = await db.subscriptions.find_one({'user_id': user_id}, {'_id': 0})
    stencils_n = await db.stencils.count_documents({'user_id': user_id})
    latest = await db.stencils.find({'user_id': user_id}, {'_id': 0, 'created_at': 1}).sort('created_at', -1).limit(1).to_list(1)

    print(f"  user_id:                  {user_id}")
    print(f"  email:                    {user.get('email')}")
    print(f"  name:                     {user.get('name')}")
    print(f"  created_at:               {user.get('created_at')}")
    print(f"  received_temp_credits:    {user.get('received_temp_credits')}    (early-access bridge flag)")
    print()

    if not sub:
        print("  ⚠️  No subscription record — user exists but never had a sub row.")
        print("     Expected on first login if subscription sync hasn't fired yet.")
    else:
        print("  --- subscriptions collection ---")
        interesting = [
            'tier', 'available_credits', 'total_monthly_credits', 'credits_consumed_this_cycle',
            'last_product_id', 'last_event', 'last_refill_at', 'in_trial',
            'revenuecat_customer_id', 'revenuecat_customer_aliases',
            'referral_premium_until', 'status',
        ]
        for k in interesting:
            if k in sub:
                v = sub[k]
                print(f"  {k:30s} {v}")

    print()
    print(f"  stencils generated:       {stencils_n}")
    if latest:
        print(f"  most recent stencil at:   {latest[0].get('created_at')}")
    print()


async def main() -> None:
    if len(sys.argv) < 2:
        print("usage: inspect_user.py <email> [<email> ...]", file=sys.stderr)
        sys.exit(1)
    client = AsyncIOMotorClient(os.environ['MONGO_URL'])
    db = client[os.environ['DB_NAME']]
    for email in sys.argv[1:]:
        await dump(db, email)


if __name__ == "__main__":
    asyncio.run(main())
