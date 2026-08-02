"""Build the SQLite employee database from the IBM HR Analytics dataset.

Keeps current employees only (Attrition == "No"), enriches every row with a
deterministic synthetic name/email (the source dataset is anonymous) and a
time-off balance so the assistant has something interesting to answer about.

Usage: python data/seed_db.py [--db storage/hr.db]
"""

import argparse
import csv
import random
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / "data" / "ibm_hr_attrition.csv"

FIRST_NAMES = [
    "Olivia", "Liam", "Emma", "Noah", "Amelia", "Oliver", "Sophia", "Elijah",
    "Charlotte", "James", "Ava", "William", "Mia", "Benjamin", "Isabella", "Lucas",
    "Luna", "Henry", "Harper", "Theodore", "Evelyn", "Jack", "Aria", "Levi",
    "Ella", "Alexander", "Nora", "Jackson", "Hazel", "Mateo", "Lily", "Daniel",
    "Chloe", "Michael", "Layla", "Mason", "Zoe", "Ethan", "Stella", "Logan",
]

LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis",
    "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson",
    "Thomas", "Taylor", "Moore", "Jackson", "Martin", "Lee", "Perez", "Thompson",
    "White", "Harris", "Sanchez", "Clark", "Ramirez", "Lewis", "Robinson", "Walker",
    "Young", "Allen", "King", "Wright", "Scott", "Torres", "Nguyen", "Hill", "Flores",
]

EMAIL_DOMAIN = "novatech.example"

SCHEMA = """
DROP TABLE IF EXISTS employees;
DROP TABLE IF EXISTS time_off;

CREATE TABLE employees (
    employee_number INTEGER PRIMARY KEY,
    name            TEXT NOT NULL,
    email           TEXT NOT NULL UNIQUE,
    gender          TEXT,
    age             INTEGER,
    department      TEXT NOT NULL,
    job_role        TEXT NOT NULL,
    job_level       INTEGER,
    education_field TEXT,
    years_at_company INTEGER,
    business_travel TEXT,
    overtime        TEXT,
    work_life_balance INTEGER,   -- 1 (bad) .. 4 (best)
    job_satisfaction  INTEGER    -- 1 (low) .. 4 (very high)
);

CREATE TABLE time_off (
    employee_number INTEGER PRIMARY KEY REFERENCES employees(employee_number),
    vacation_days_total INTEGER NOT NULL,
    vacation_days_used  INTEGER NOT NULL,
    sick_days_used      INTEGER NOT NULL
);

CREATE INDEX idx_employees_department ON employees(department);
CREATE INDEX idx_employees_name ON employees(name);
"""


def make_name(index: int, taken: set[str]) -> str:
    # Deterministic permutation over the 40x40 name grid: unique and well mixed
    # for up to 1600 employees (617 is coprime with 1600).
    j = (index * 617) % (len(FIRST_NAMES) * len(LAST_NAMES))
    first = FIRST_NAMES[j % len(FIRST_NAMES)]
    last = LAST_NAMES[j // len(FIRST_NAMES)]
    name = f"{first} {last}"
    suffix = 2
    while name in taken:
        name = f"{first} {last} {['Jr.', 'II', 'III'][suffix % 3]}"
        suffix += 1
    taken.add(name)
    return name


def make_email(name: str) -> str:
    slug = name.lower().replace(" ", ".").replace("..", ".").rstrip(".")
    for ch in ("jr.", "ii", "iii"):
        slug = slug.removesuffix("." + ch)
    return f"{slug}@{EMAIL_DOMAIN}"


def seed(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)

    with open(CSV_PATH, encoding="utf-8-sig", newline="") as f:
        rows = [r for r in csv.DictReader(f) if r["Attrition"] == "No"]

    taken_names: set[str] = set()
    taken_emails: set[str] = set()
    n_employees = 0
    for index, row in enumerate(rows):
        emp_no = int(row["EmployeeNumber"])
        name = make_name(index, taken_names)
        email = make_email(name)
        if email in taken_emails:  # name suffixes like "Jr." share the base email
            email = email.replace("@", f"{emp_no}@")
        taken_emails.add(email)

        conn.execute(
            """INSERT INTO employees VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                emp_no,
                name,
                email,
                row["Gender"],
                int(row["Age"]),
                row["Department"],
                row["JobRole"],
                int(row["JobLevel"]),
                row["EducationField"],
                int(row["YearsAtCompany"]),
                row["BusinessTravel"],
                row["OverTime"],
                int(row["WorkLifeBalance"]),
                int(row["JobSatisfaction"]),
            ),
        )

        rng = random.Random(emp_no)  # deterministic per employee
        total = 20 + 2 * int(row["JobLevel"])  # 22..30 days by seniority
        used = rng.randint(0, total)
        sick = rng.randint(0, 8)
        conn.execute(
            "INSERT INTO time_off VALUES (?,?,?,?)",
            (emp_no, total, used, sick),
        )
        n_employees += 1

    conn.commit()
    counts = conn.execute(
        "SELECT department, COUNT(*) FROM employees GROUP BY department"
    ).fetchall()
    conn.close()
    print(f"Seeded {n_employees} employees into {db_path}")
    for dept, n in counts:
        print(f"  {dept}: {n}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(ROOT / "storage" / "hr.db"))
    args = parser.parse_args()
    seed(Path(args.db))
