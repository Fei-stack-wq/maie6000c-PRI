# W04 Team Architecture Proposal and Project Plan

> Historical Week 04 proposal for the earlier Startup Pitch project; it is not the current implementation.
> Current project: [Week 07](../week07/README.md), [Architecture](../../../docs/architecture.md).
>
> 这是早期创业提案项目的 Week 04 历史材料，不代表当前实现。
> 当前项目见 [Week 07](../week07/README.md)和[系统架构](../../../docs/architecture.md)。

## 1. Project Overview

- **Team:** Project Group 15
- **Project Title:** AI Startup Pitch Feedback Assistant
- **Submission Tag:** `w04-proposal`

Our team proposes an AI Startup Pitch Feedback Assistant
designed to help student entrepreneurs improve how they
present their business ideas.

Users will submit a short startup pitch, and the system
will provide structured feedback covering four key elements:

- Problem
- Target Customer
- Solution
- Value Proposition

The system will also identify missing or unclear information
and provide three actionable improvement suggestions.

Our goal is to help students communicate their ideas more
clearly, rather than predict business success or provide
investment recommendations.

This Week 4 submission describes our proposed architecture,
implementation plan, milestones, and major risks. The system
has not yet been fully implemented or tested.


## 2. Primary Workflow and Architecture

### Primary Workflow

The proposed workflow consists of the following steps:

1. The user submits a project title and a short startup pitch.
2. The API validates the input and stores the original pitch.
3. The system creates a background analysis job.
4. A worker retrieves the job and calls the internal AI service.
5. The AI analyzes the pitch and generates structured feedback.
6. The worker saves the analysis result and updates the job status.
7. The user retrieves the feedback through the API or web interface.

The generated feedback will include:

- A concise pitch summary.
- The four key business elements.
- Missing or unclear information.
- Three actionable improvement suggestions.

If the AI analysis fails, the system will preserve the
original pitch, report the failure, and support retrying.

Users will review the generated feedback and decide which
suggestions to accept, modify, or ignore.

### Architecture Summary

The system will extend the course starter repository
using four main components:

| Component | Responsibility |
| --- | --- |
| API Service | Validate submissions, store pitches, and expose status and results. |
| PostgreSQL | Store pitches, processing jobs, and analysis results. |
| Worker | Process background jobs and handle AI requests. |
| Internal AI Service | Analyze startup pitches and generate structured feedback. |

We will initially use one worker and a database-backed
job queue to keep the architecture simple and manageable.

The API will return after creating the analysis job,
while AI processing will run asynchronously.

Detailed component responsibilities, API design,
data models, and failure handling are described in
the architecture document.


## 3. Milestone Plan

Our team plans to complete the project through the
following milestones:

| Timeline | Planned Work | Expected Outcome |
| --- | --- | --- |
| Week 4 | Define project scope, architecture, interfaces, and risks. | Completed proposal and architecture documents. |
| Weeks 5–6 | Implement pitch storage, job creation, status retrieval, and AI integration. | Basic background processing workflow. |
| Week 7 | Complete the minimum end-to-end workflow. | Submit a pitch, retrieve AI feedback, and demonstrate failure handling and retry. |
| Weeks 8–10 | Improve output validation, feedback quality, and reliability. | Verified results using representative pitch examples. |
| Weeks 11–12 | Improve testing, deployment, and documentation. | Reproducible deployment and stable core workflow. |
| Week 13 | Prepare the final demonstration and report. | Final demonstration and documented results. |

### Minimum Viable Product (MVP)

By Week 7, we aim to demonstrate:

- Pitch submission and persistent storage.
- Background AI analysis.
- Structured feedback covering the four business elements.
- Three improvement suggestions.
- Status and result retrieval.
- Basic failure handling and retry.

Our priority is to complete a reliable end-to-end workflow
before adding optional features.


## 4. Key Risks and Scope Management

### Core Scope

The project will focus on:

- Text-based startup pitch submission.
- Persistent storage and background processing.
- AI-generated structured pitch feedback.
- Missing-information identification.
- Three actionable improvement suggestions.
- Status retrieval, error handling, and retry.

### Optional Features

If time permits, we may add:

- A simple web interface for pitch submission.
- A result page displaying feedback and processing status.

The API workflow will be sufficient for the initial
demonstration if the web interface is not completed.

### Out of Scope

The following features are excluded:

- Investment prediction or financial recommendations.
- Commercial profitability evaluation.
- Comprehensive market research.
- Investor matching.
- Mobile application development.

### Key Risks and Mitigation

| Risk | Mitigation | Fallback |
| --- | --- | --- |
| AI model access or API limitations | Confirm model availability and test access early. | Use another accessible model. Mock responses may be used for engineering tests but not as evidence of working AI analysis. |
| Incomplete or inaccurate AI feedback | Validate output structure and review sample results. | Narrow the prompt and report missing information rather than inventing details. |
| AI service failures or timeouts | Track job status and preserve original submissions. | Support retry without losing the original pitch. |
| Implementation delays | Prioritize the core backend and AI workflow. | Defer frontend development and optional features. |
| Difficulty evaluating feedback quality | Review representative pitch examples against the original inputs. | Document limitations and retain human review. |

If development time becomes limited, we will prioritize
the API, background processing, and structured feedback
generation over frontend development and optional features.


## 5. Artifact Index

The following documents support this Week 4 submission:

| Artifact | Description |
| --- | --- |
| [Architecture Proposal](../../../docs/architecture.md) | Detailed system architecture, component responsibilities, API design, data models, and failure handling. |
| [Week 4 README](README.md) | Project overview, workflow, milestone plan, scope, risks, and AI use statement. |

The architecture document provides the technical details
supporting this concise submission summary.


## 6. AI Use Statement / AI 使用说明

We used ChatGPT to improve and polish the documentation and to assist with code scaffolding and testing.

我们使用 ChatGPT 完善和润色文档说明，并辅助进行代码框架构造和测试。

## 7. Supporting artifacts

**ERD diagram:**

![alt text](assets/ERD.png)

**architecture diagram:**

![alt text](<assets/architecture diagram.png>)
