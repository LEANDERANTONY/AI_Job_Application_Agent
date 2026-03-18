from textwrap import dedent

import streamlit as st

from src.config import APP_BASE_URL


def get_homepage_url(base_url: str | None = None):
    normalized = str(base_url or APP_BASE_URL or "").strip()
    return normalized.rstrip("/") if normalized else ""


def get_privacy_policy_url(base_url: str | None = None):
    homepage_url = get_homepage_url(base_url)
    if not homepage_url:
        return "?view=privacy"
    return homepage_url + "/?view=privacy"


def get_privacy_policy_markdown():
    return dedent(
        """
        Last updated: March 18, 2026

        Job Application Copilot is a Streamlit-based application workflow tool for resume parsing, job-description analysis, tailored document generation, authenticated usage tracking, and optional AI-assisted guidance.

        ## What this app collects

        ### Information you choose to provide

        - Resume files and extracted resume text that you upload.
        - Job descriptions that you upload or paste.
        - Application materials generated from those inputs, such as tailored resumes, cover letters, and application reports.

        ### Google sign-in information

        If you sign in with Google through Supabase Auth, the app receives basic identity information associated with your account:

        - your unique auth user id
        - your email address
        - your display name, if Google provides one
        - your profile image URL, if Google provides one

        The app does not request access to your Gmail inbox, Google Drive, Google Calendar, contacts, or any other sensitive Google data.

        ### Usage and account records

        For authenticated users, the app stores limited product-operational records, including:

        - your plan tier and account status
        - sign-in and last-seen timestamps
        - AI-assisted usage events such as task name, model name, token counts, response id, status, and timestamp

        ### Saved workspace data

        If you are signed in and use the authenticated workflow, the app can store your latest saved workspace so you can reload it later. That saved workspace can contain:

        - normalized resume and job-description data
        - workflow state
        - generated report, cover-letter, and tailored-resume payloads

        ## How the app uses your information

        The app uses your information to:

        - authenticate you and maintain signed-in state
        - parse resumes and job descriptions
        - generate tailored application outputs
        - enforce session and account-level usage limits
        - restore your latest saved workspace
        - monitor product health and diagnose operational failures

        ## When data is sent to third parties

        The app uses the following service providers:

        - Supabase for authentication and product data storage
        - OpenAI for optional AI-assisted workflow steps and assistant responses
        - Render for hosted application infrastructure

        Resume content, job-description content, and generated application materials are sent to OpenAI only when you are signed in and explicitly run AI-assisted features or use the in-app assistant while AI support is enabled. Deterministic parsing and non-assisted flows do not require OpenAI.

        Google sign-in is mediated through Supabase Auth. The app itself does not directly handle your Google password.

        ## Data retention

        - The latest saved workspace for an authenticated user is retained for 24 hours by default, then expires.
        - Authenticated account records and usage-event records remain in Supabase until they are updated or removed by the app operator.
        - Browser-session state used for the current run remains in your active browser session until it is cleared, expires, or you sign out.

        ## What the app does not do

        - It does not sell your personal data.
        - It does not request Gmail mailbox access.
        - It does not request Google Drive, Calendar, or contacts access.
        - It does not use your Google account to post, send messages, or act on your behalf outside authentication.

        ## Security and access

        The app relies on Supabase authentication, hosted infrastructure controls, and application-level access checks to limit access to authenticated records. No internet-facing system can guarantee absolute security, so you should avoid uploading information you do not want processed by the services described above.

        ## Your choices

        You may use the non-authenticated parts of the app without Google sign-in, subject to the app's current feature configuration. AI-assisted workflow and assistant features require login. If you do not want resume or job-description content processed by OpenAI, do not run those assisted features.

        ## Contact

        For privacy or support questions about this app, use the support channel or contact method provided by the app operator in the app listing, repository, or OAuth consent configuration.
        """
    ).strip()


def render_privacy_policy_page():
    st.title("Privacy Policy")
    homepage_url = get_homepage_url()
    if homepage_url:
        st.caption("Homepage: [{url}]({url})".format(url=homepage_url))
    st.markdown(get_privacy_policy_markdown())
