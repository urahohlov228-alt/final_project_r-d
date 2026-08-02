"""Read-only access to the employee SQLite database.

Security note: this module is the safe context boundary for employee data.
Sensitive columns (e.g. monthly_income from the source dataset) are never
selected here, so they can never leak into an LLM context or a chat reply.
"""

import sqlite3
from pathlib import Path

# The only employee fields that may enter an LLM context.
SAFE_FIELDS = (
    "employee_number, name, email, department, job_role, job_level, "
    "education_field, years_at_company, business_travel, overtime"
)


class EmployeeDB:
    def __init__(self, db_path: Path):
        self._db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(f"file:{self._db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    def find_employee(self, query: str) -> dict | None:
        """Find one employee by exact email, employee number, or (fuzzy) name."""
        query = query.strip()
        with self._connect() as conn:
            if query.isdigit():
                row = conn.execute(
                    f"SELECT {SAFE_FIELDS} FROM employees WHERE employee_number = ?",
                    (int(query),),
                ).fetchone()
            elif "@" in query:
                row = conn.execute(
                    f"SELECT {SAFE_FIELDS} FROM employees WHERE lower(email) = lower(?)",
                    (query,),
                ).fetchone()
            else:
                row = conn.execute(
                    f"SELECT {SAFE_FIELDS} FROM employees WHERE lower(name) = lower(?)",
                    (query,),
                ).fetchone()
                if row is None:
                    row = conn.execute(
                        f"SELECT {SAFE_FIELDS} FROM employees "
                        "WHERE name LIKE ? ORDER BY name LIMIT 1",
                        (f"%{query}%",),
                    ).fetchone()
            return dict(row) if row else None

    def suggest_names(self, query: str, limit: int = 5) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT name FROM employees WHERE name LIKE ? ORDER BY name LIMIT ?",
                (f"%{query.strip()}%", limit),
            ).fetchall()
            return [r["name"] for r in rows]

    def list_employees(self, department: str = "", job_role: str = "", limit: int = 10) -> dict:
        clauses, params = [], []
        if department:
            clauses.append("lower(department) LIKE lower(?)")
            params.append(f"%{department.strip()}%")
        if job_role:
            clauses.append("lower(job_role) LIKE lower(?)")
            params.append(f"%{job_role.strip()}%")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        limit = max(1, min(int(limit), 50))
        with self._connect() as conn:
            total = conn.execute(
                f"SELECT COUNT(*) AS n FROM employees {where}", params
            ).fetchone()["n"]
            rows = conn.execute(
                f"SELECT {SAFE_FIELDS} FROM employees {where} ORDER BY name LIMIT ?",
                [*params, limit],
            ).fetchall()
        return {
            "total_matching": total,
            "returned": len(rows),
            "employees": [dict(r) for r in rows],
        }

    def departments(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT department, COUNT(*) AS headcount FROM employees "
                "GROUP BY department ORDER BY headcount DESC"
            ).fetchall()
            return [dict(r) for r in rows]

    def get_time_off(self, employee_query: str) -> dict | None:
        employee = self.find_employee(employee_query)
        if employee is None:
            return None
        with self._connect() as conn:
            row = conn.execute(
                "SELECT vacation_days_total, vacation_days_used, sick_days_used "
                "FROM time_off WHERE employee_number = ?",
                (employee["employee_number"],),
            ).fetchone()
        if row is None:
            return None
        balance = dict(row)
        balance["vacation_days_remaining"] = (
            balance["vacation_days_total"] - balance["vacation_days_used"]
        )
        return {
            "employee_number": employee["employee_number"],
            "name": employee["name"],
            "department": employee["department"],
            **balance,
        }
