"""Backward-compatible wrapper for the v2 job-role catalog seed.

Run with: python -m app.seed_v21_roles
"""

from app.seed_job_roles import seed_job_roles

if __name__ == "__main__":
    seed_job_roles()
