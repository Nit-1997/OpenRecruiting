"""Candidate profile enrichment — isolated ATS-owned pipeline.

A throttled background worker pulls each pending ATS candidate's resume (fresh
presigned URL re-fetched at process time), extracts a role-agnostic structured
profile (Sonnet 4.6), consolidates it with the ATS signals the slim webhook
events drop (screening Q&A, rejection, location/links/applied_at), persists it to
candidates.profile, and pushes it to Cortex. None of this touches the generic
candidate-creation path; OpenRecruiting-created candidates (enrichment_status NULL) are
never picked up.

Spec: docs/superpowers/specs/2026-06-12-knit-ats-candidate-enrichment-design.md
"""
