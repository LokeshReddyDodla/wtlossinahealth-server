"""
How-to video catalog for the Dashboard Help agent.

Each entry maps a clip id (also the S3 object name, `<id>.mp4`) to a short
description of when it applies. The description is what the classifier reads to
decide which clip — if any — matches a user's question.

Adding a new help video later = (1) upload `<id>.mp4` to the help-videos/ prefix
in S3, and (2) add one line here. No other code changes needed.

Clips are served publicly from the existing media bucket:
    https://user-assets.aihealth.clinic/help-videos/<id>.mp4
Override via env (HELP_VIDEOS_BASE_URL / HELP_VIDEOS_S3_BUCKET / HELP_VIDEOS_PREFIX).
"""

from __future__ import annotations

from decouple import config

HELP_VIDEOS_S3_BUCKET = config("HELP_VIDEOS_S3_BUCKET", default="user-assets.aihealth.clinic")
HELP_VIDEOS_PREFIX = config("HELP_VIDEOS_PREFIX", default="help-videos")
HELP_VIDEOS_BASE_URL = config(
    "HELP_VIDEOS_BASE_URL",
    default=f"https://{HELP_VIDEOS_S3_BUCKET}/{HELP_VIDEOS_PREFIX}",
)

# id -> when this clip applies
VIDEO_CATALOG: dict[str, str] = {
    "dashboard-tour": "A general tour / overview of the dashboard; what things are; getting started after first login.",
    "find-and-open-patient": "Finding a patient and opening their profile (search, the row's menu, View).",
    "smbg-report": "Finding or opening a patient's SMBG (finger-prick glucose) report.",
    "cgm-glucose-stats": "Viewing blood glucose statistics / the CGM report over a date range (time in range, average, variability).",
    "assign-package": "Assigning a package or care plan to a patient.",
    "chat-with-documents": "Selecting a patient's documents and chatting with them using AI.",
    "upload-patient-data": "Uploading patient data — CGM raw CSV, reports, or other documents.",
    "cgm-not-syncing": "CGM or glucose data not syncing; Connected Apps; Sync Now; LibreView.",
    "toggle-chips": "Can't find a section/tab on the patient page; the toggle chips that show/hide sections.",
    "add-prescription": "Adding a prescription or medication for a patient.",
    "create-diet-plan": "Creating a diet plan for a patient.",
    "read-meal-report": "Reading a patient's meal report — calories, macros, what they ate.",
    "read-fitness-report": "Reading a patient's fitness/activity report — steps, active energy.",
    "proactive-insights": "Viewing the AI Proactive Insights for a patient.",
    "notifications": "Viewing and filtering a patient's notifications.",
    "research-module": "Using the Research module and its clinical domain tabs.",
    "export-patient": "Exporting a patient's data.",
    "filter-patients": "Filtering the patient list (e.g. SMBG patients, patients with no package).",
    "add-patient": "Adding a new patient.",
    "add-care-provider": "Adding a new care provider.",
    "manage-provider-permissions": "Managing a care provider's permissions (read/create/update/delete per module).",
    "share-invite-code": "Sharing a provider invite code or a package join code.",
    "create-package": "Creating a new package.",
    "message-a-patient": "Messaging a patient via Chats.",
    "overview-triage": "The Overview triage screen — at-risk patients, glucose events across all patients.",
    "exercises-search-filter": "Searching or filtering the exercise library.",
    "add-exercise": "Adding a custom exercise.",
    "gamification-create-group": "Creating a gamification group.",
    "gamification-create-challenge": "Creating a gamification challenge.",
    "health-agent": "Using the in-app Health Agent (the floating robot) for patient-data questions.",
}


def video_url(video_id: str) -> str:
    """Public URL for a clip id."""
    return f"{HELP_VIDEOS_BASE_URL}/{video_id}.mp4"
