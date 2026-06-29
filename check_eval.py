import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from src.config.settings import settings

engine = create_async_engine(settings.DATABASE_URL)


async def run():
    async with engine.begin() as conn:
        result = await conn.execute(
            text("""
            SELECT id, candidate_assessment_id, status
            FROM interview_sessions
            ORDER BY created_at DESC
            LIMIT 1;
        """)
        )
        session = result.fetchone()
        if session:
            print(
                f"Latest Session: ID={session[0]}, CA_ID={session[1]}, Status={session[2]}"
            )

            # Check if evaluation exists
            eval_result = await conn.execute(
                text(f"""
                SELECT id, overall_score
                FROM interview_evaluations
                WHERE candidate_assessment_id = '{session[1]}'
                LIMIT 1;
            """)
            )
            evaluation = eval_result.fetchone()
            if evaluation:
                print(f"Evaluation exists! Score={evaluation[1]}")
            else:
                print(
                    "No evaluation record found for this session yet. It might still be processing."
                )
        else:
            print("No interview sessions found.")


if __name__ == "__main__":
    asyncio.run(run())
