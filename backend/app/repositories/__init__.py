"""Repositories: the only layer that builds database queries.

Services call repositories; API routes call services. Keeping queries here means
business rules never contain SQL and queries are easy to find and test.
"""
