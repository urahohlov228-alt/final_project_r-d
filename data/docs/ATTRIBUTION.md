# Data Attribution

## Knowledge base documents (this directory)

The markdown documents in this directory are pages from the **GitLab Employee Handbook**,
used as a realistic open-source corpus of HR policies for the RAG knowledge base.

- Source repository: <https://gitlab.com/gitlab-com/content-sites/handbook>
- Snapshot commit: `46180fa3686c8baa55f91bf32c6e1d676eefd475` (main, 2026-08-02)
- License: [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/) — © GitLab Inc.
- Changes: files were renamed and are indexed/chunked for retrieval; content is unmodified.

| Local file | Original path in the handbook repo |
|---|---|
| `time-off.md` | `content/handbook/people-group/time-off-and-absence/_index.md` |
| `time-off-types.md` | `content/handbook/people-group/time-off-and-absence/time-off-types.md` |
| `onboarding.md` | `content/handbook/people-group/general-onboarding/_index.md` |
| `benefits.md` | `content/handbook/total-rewards/benefits/_index.md` |
| `total-rewards.md` | `content/handbook/total-rewards/_index.md` |
| `spending-company-money.md` | `content/handbook/finance/spending-company-money.md` |
| `remote-work.md` | `content/handbook/company/culture/all-remote/getting-started.md` |
| `anti-harassment.md` | `content/handbook/people-group/anti-harassment.md` |

## Employee database

`data/ibm_hr_attrition.csv` is the **IBM HR Analytics Employee Attrition & Performance**
dataset (a fictional dataset created by IBM data scientists, widely used for
teaching/testing), downloaded from IBM's public repository:

- Source: <https://github.com/IBM/employee-attrition-aif360> (`data/emp_attrition.csv`)
- The seed script keeps current employees only, and adds deterministic synthetic
  names/emails and time-off balances for a more realistic assistant demo.

## Live external APIs

- Public holidays: [Nager.Date](https://date.nager.at) — free, no API key
- Exchange rates: [open.er-api.com](https://www.exchangerate-api.com) — free tier, no API key
