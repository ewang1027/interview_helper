"""`make cost-report` / `python -m api.cost_report` — spend from the `llm_calls`
ledger. See docs/COST.md's "Measuring before optimizing". Prints zeros on an empty
table rather than failing, since no session has run yet in this repo's history.
"""

from __future__ import annotations

from sqlmodel import Session, func, select

from api.db import get_engine
from api.models import LlmCall


def main() -> None:
    with Session(get_engine()) as session:
        total_calls = session.exec(select(func.count()).select_from(LlmCall)).one()
        total_cost = session.exec(select(func.coalesce(func.sum(LlmCall.cost_usd), 0.0))).one()
        by_job = session.exec(
            select(LlmCall.job, func.count(), func.coalesce(func.sum(LlmCall.cost_usd), 0.0))
            .group_by(LlmCall.job)
            .order_by(LlmCall.job)
        ).all()

        print(f"calls: {total_calls}")
        print(f"total cost: ${total_cost:.4f}")
        for job, count, cost in by_job:
            print(f"  {job}: {count} call(s), ${cost:.4f}")


if __name__ == "__main__":
    main()
