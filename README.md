# AI Job Application Agent

[![CI](https://github.com/LEANDERANTONY/AI_Job_Application_Agent/actions/workflows/ci.yml/badge.svg)](https://github.com/LEANDERANTONY/AI_Job_Application_Agent/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Live App](https://img.shields.io/badge/Live%20App-Render-2563eb?logo=render&logoColor=white)](https://ai-job-application-agent.onrender.com/)

AI Job Application Agent is a Streamlit app that turns a resume and job description into a grounded job-application workflow: fit analysis, tailored resume, cover letter, application strategy report, and in-app assistant support.

Live app: [ai-job-application-agent.onrender.com](https://ai-job-application-agent.onrender.com/)

## What It Does

- Parses resumes from PDF, DOCX, or TXT and builds a normalized candidate profile
- Structures job descriptions into title, requirements, skills, and experience signals
- Runs a supervised agentic workflow for fit, tailoring, strategy, review, resume generation, and cover letter generation
- Produces three exportable artifacts:
  - tailored resume
  - cover letter
  - application strategy report
- Uses Google sign-in via Supabase for AI features, saved workspace reload, and persisted daily quota tracking
- Keeps one latest saved workspace per signed-in user and restores it through the sidebar `Reload Workspace` action

## Product Flow

1. Sign in with Google
2. Upload your resume
3. Paste or upload a job description
4. Run the agentic analysis
5. Review the tailored resume, cover letter, and application strategy
6. Ask the assistant grounded questions about the app or current outputs
7. Download Markdown or PDF artifacts

## UI Preview

### 1. Sign In And Load Inputs

![Sidebar navigation](docs/screenshots/sidebar_navigation.jpg)

![Resume parser view](docs/screenshots/resume_parser_view.jpg)

![JD parser view](docs/screenshots/jd_parser_view.jpg)

### 2. Run The Agentic Workflow

![Agentic workflow](docs/screenshots/agentic_workflow.jpg)

### 3. Ask Grounded Follow-Up Questions

![Smart assistant](docs/screenshots/smart_assistant.jpg)

### 4. Review The Generated Outputs

![Classic resume render](docs/screenshots/classic_resume_render.jpg)

![Cover letter render](docs/screenshots/cover_letter_render.jpg)

## Sample Exports

- Application strategy PDF: [docs/pdf_rendered/application_strategy_render.pdf](docs/pdf_rendered/application_strategy_render.pdf)
- Tailored resume PDF: [docs/pdf_rendered/classic_resume_render.pdf](docs/pdf_rendered/classic_resume_render.pdf)
- Cover letter PDF: [docs/pdf_rendered/cover_letter_render.pdf](docs/pdf_rendered/cover_letter_render.pdf)

## Stack

- Streamlit UI
- OpenAI Responses API for assisted generation
- Supabase for Google auth, persisted usage, and saved workspace storage
- WeasyPrint-first PDF generation with fallback handling in code
- `uv` for environment and dependency management
