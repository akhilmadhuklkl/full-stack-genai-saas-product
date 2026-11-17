# Full-Stack GenAI SaaS Product

An AI-powered SaaS application with authentication, dashboards, APIs, streaming responses, usage limits, and an agent service.

## Project goal

Build a production-style AI application such as a code reviewer, research assistant, sales assistant, or support bot. The first implementation will focus on a small, complete vertical slice before adding advanced agent tools, retrieval, billing, and background jobs.

## Planned architecture

```text
Web UI -> API gateway -> Business logic API
                         |-> AI agent service
                         |-> Billing and usage service
                         v
                  PostgreSQL / Redis / Vector search
```

## Development status

Project setup only. Application implementation will be added incrementally.

## Local setup

The stack and setup instructions will be documented here as the application is scaffolded.
