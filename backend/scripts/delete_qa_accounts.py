"""One-off QA cleanup: admin-delete specific accounts by email so they can
be re-registered fresh and hit a clean paywall.

Mirrors the cascade in `@api_router.delete("/account/delete")` — users +
subscriptions + stencils + studio_teams membership.

Usage:
    python3 /app/backend/scripts/delete_qa_accounts.py
"""
import asyncio
import os

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv('/app/backend/.env')

QA_EMAILS = [
    "bodyboundstencilapp@gmail.com",
    "formyuselessstuff1@gmail.com",
    "pa1dd3wz@gmail.com",
]


async def main() -> None:
    client = AsyncIOMotorClient(os.environ['MONGO_URL'])
    db = client[os.environ['DB_NAME']]

    for email in QA_EMAILS:
        user = await db.users.find_one({'email': email}, {'_id': 0})
        if not user:
            print(f"[{email}]  not found — already clean.")
            continue

        user_id = user['user_id']
        stencils_n = await db.stencils.count_documents({'user_id': user_id})
        subs_n = await db.subscriptions.count_documents({'user_id': user_id})
        teams_admin = await db.studio_teams.count_documents({'admin_user_id': user_id})
        teams_member = await db.studio_teams.count_documents({'members.user_id': user_id})

        print(f"[{email}]  user_id={user_id}  tier={user.get('tier')}  credits={user.get('available_credits')}  "
              f"stencils={stencils_n}  subs={subs_n}  studio_admin={teams_admin}  studio_member={teams_member}")

        res_u = await db.users.delete_one({'user_id': user_id})
        res_s = await db.subscriptions.delete_many({'user_id': user_id})
        res_st = await db.stencils.delete_many({'user_id': user_id})
        await db.studio_teams.update_many(
            {'members.user_id': user_id},
            {'$pull': {'members': {'user_id': user_id}}},
        )
        res_t = await db.studio_teams.delete_many({'admin_user_id': user_id})

        # Also purge any in-flight jobs / ratings tied to this user (ratings
        # are anonymous-safe but we purge for a clean slate)
        res_jobs = await db.ai_stencil_jobs.delete_many({'user_id': user_id})
        res_rat = await db.stencil_ratings.delete_many({'user_id': user_id})

        print(f"    deleted: users={res_u.deleted_count}  subs={res_s.deleted_count}  "
              f"stencils={res_st.deleted_count}  teams_as_admin={res_t.deleted_count}  "
              f"jobs={res_jobs.deleted_count}  ratings={res_rat.deleted_count}")

    print("\n✅ QA accounts purged. They can now re-register through the app.")
    print("   On re-registration (with their emails in PAYWALL_NO_BYPASS_EMAILS):")
    print("   → tier=None, credits=0, NO 10-credit bypass, immediate paywall.")


if __name__ == "__main__":
    asyncio.run(main())
