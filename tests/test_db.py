from hr_assistant.db import EmployeeDB
from hr_assistant.db.queries import SAFE_FIELDS


def test_find_employee_by_name_email_and_number(seeded_db):
    db = EmployeeDB(seeded_db)
    by_number = db.find_employee("2")
    assert by_number is not None
    by_name = db.find_employee(by_number["name"])
    by_email = db.find_employee(by_number["email"])
    assert by_name["employee_number"] == by_email["employee_number"] == 2


def test_sensitive_fields_never_selected(seeded_db):
    assert "monthly_income" not in SAFE_FIELDS
    employee = EmployeeDB(seeded_db).find_employee("2")
    assert "monthly_income" not in employee
    assert "job_satisfaction" not in employee


def test_unknown_employee_returns_none_with_suggestions(seeded_db):
    db = EmployeeDB(seeded_db)
    assert db.find_employee("Definitely Nobody") is None
    assert db.suggest_names("Oliv")  # partial match still suggests


def test_list_employees_filters_and_limits(seeded_db):
    db = EmployeeDB(seeded_db)
    result = db.list_employees(department="Sales", limit=5)
    assert result["total_matching"] > 100
    assert result["returned"] == 5
    assert all(e["department"] == "Sales" for e in result["employees"])

    result = db.list_employees(limit=999)  # limit is clamped
    assert result["returned"] <= 50


def test_departments_headcounts(seeded_db):
    departments = EmployeeDB(seeded_db).departments()
    assert {d["department"] for d in departments} == {
        "Human Resources",
        "Research & Development",
        "Sales",
    }
    assert sum(d["headcount"] for d in departments) == 1233


def test_time_off_balance_math(seeded_db):
    balance = EmployeeDB(seeded_db).get_time_off("2")
    assert balance is not None
    assert (
        balance["vacation_days_remaining"]
        == balance["vacation_days_total"] - balance["vacation_days_used"]
    )
