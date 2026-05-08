// Mock data shared between both directions — realistic enough that the
// prototype shows the actual readability problems being solved.

const MOCK = {
  candidate: {
    name: "Leander Antony",
    title: "Machine Learning Engineer",
    location: "Bengaluru, India",
    skills: [
      "Python", "FastAPI", "PyTorch", "LangChain", "Docker",
      "PostgreSQL", "AWS", "Kubernetes", "RAG", "vLLM", "Redis", "TypeScript"
    ],
    experience: [
      { title: "ML Engineer", org: "Helpmate AI", period: "2023 — Now" },
      { title: "Data Scientist", org: "Quantiphi", period: "2021 — 2023" },
    ],
    signals: [
      "Resume parsed cleanly — 3 roles, 12 skills detected",
      "Strong RAG and LLM serving signal",
      "Education and certifications structured",
    ],
  },

  jobResults: [
    {
      id: "job-1",
      title: "Senior ML Engineer, Inference Platform",
      company: "Anthropic",
      source: "greenhouse",
      location: "San Francisco · Remote OK",
      posted: "2d ago",
      saved: true,
      summary: "Build the runtime that serves Claude. Ownership over latency, throughput, and reliability of the model-serving stack. Strong Python and systems background expected.",
      badges: ["Remote", "$220k–$320k", "Full-time"],
    },
    {
      id: "job-2",
      title: "Applied AI Engineer",
      company: "Cursor",
      source: "lever",
      location: "Remote",
      posted: "5d ago",
      saved: false,
      summary: "Ship features end-to-end across the editor and the model side. Comfort with model fine-tuning, retrieval, and product engineering equally weighted.",
      badges: ["Remote", "Full-time"],
    },
    {
      id: "job-3",
      title: "Machine Learning Engineer, Search Quality",
      company: "Perplexity",
      source: "greenhouse",
      location: "San Francisco",
      posted: "1w ago",
      saved: false,
      summary: "Improve relevance and grounding for the answer engine. Heavy focus on retrieval, ranking, and eval pipelines.",
      badges: ["Hybrid", "$200k–$280k"],
    },
    {
      id: "job-4",
      title: "ML Platform Engineer",
      company: "Replicate",
      source: "lever",
      location: "Remote · US/EU",
      posted: "3d ago",
      saved: true,
      summary: "Build the platform that runs open-source models for thousands of developers. Strong Kubernetes and GPU scheduling background.",
      badges: ["Remote", "Full-time"],
    },
  ],

  jd: {
    title: "Senior ML Engineer, Inference Platform",
    company: "Anthropic",
    summary:
      "We're building the inference systems that serve Claude to hundreds of millions of users. You'll own latency, throughput, and reliability of the model-serving stack, work across CUDA kernels and high-level Python orchestration, and partner with researchers turning new architectures into production systems.",
    hardSkills: ["Python", "CUDA", "PyTorch", "vLLM", "Kubernetes", "Distributed systems", "GPU scheduling", "Triton"],
    softSkills: ["Ownership", "Cross-team collaboration", "Written communication"],
    sections: [
      {
        title: "What you'll do",
        body: "Own the latency and throughput of the model-serving stack. Profile and optimize hot paths in CUDA, Triton, or vLLM. Partner with research engineers to turn new model architectures into production systems. Drive reliability across global inference clusters.",
      },
      {
        title: "What we're looking for",
        body: "5+ years of systems-leaning ML or ML-leaning systems engineering. Production experience with at least one of vLLM, TensorRT, or a comparable stack. Strong written communication — you'll write design docs that ship.",
      },
      {
        title: "Compensation",
        body: "$220,000 – $320,000 base salary plus equity. Comprehensive health, dental, and vision. Remote-friendly across the US.",
      },
    ],
    metrics: [
      { label: "Match score",    value: "84",  unit: "%" },
      { label: "Hard skills",    value: "8",   unit: "" },
      { label: "Years required", value: "5+",  unit: "" },
    ],
  },

  workflow: {
    mode: "AI-assisted",
    stages: [
      { id: "crew",        title: "Workflow crew",     detail: "Coordinating agents",        value: 100 },
      { id: "matchmaker",  title: "Matchmaker agent",  detail: "Scoring role fit",           value: 100 },
      { id: "forge",       title: "Forge agent",       detail: "Drafting tailored resume",   value: 100 },
      { id: "gatekeeper",  title: "Gatekeeper agent",  detail: "ATS + keyword check",        value: 100 },
      { id: "builder",     title: "Builder agent",     detail: "Assembling final resume",    value: 72  },
      { id: "coverletter", title: "Cover letter agent",detail: "Drafting cover letter",      value: 0   },
      { id: "backup",      title: "Backup workflow",   detail: "Standby · idle",             value: 0   },
    ],
  },

  artifact: {
    resume: {
      title: "Tailored Resume — Anthropic, ML Engineer",
      summary: "Reframed your inference-platform work, surfaced 6 quantified achievements, mapped 8/8 hard-skill keywords from the JD.",
      preview: `# Leander Antony
Machine Learning Engineer · Bengaluru, India
leander@example.com · linkedin.com/in/leander · github.com/leander

## Summary
ML engineer with 4 years building production model-serving and retrieval systems.
Shipped a vLLM-backed inference layer serving 40M req/day with p99 < 220ms. Strong
Python and systems background; comfortable from CUDA kernel down to product API.

## Experience

**Helpmate AI** — ML Engineer
2023 — Now
- Designed and shipped vLLM-backed inference platform serving 40M req/day,
  reducing p99 latency 38% by tuning continuous batching and KV-cache reuse.
- Owned the RAG retrieval stack: hybrid BM25 + dense, reranker, eval harness.
  Lifted answer-grounding score from 71 → 89 over two quarters.
- Mentored 3 engineers; wrote the team's inference design-doc template.

**Quantiphi** — Data Scientist
2021 — 2023
- Productionized 6 NLP models on AWS SageMaker, cutting inference cost 42%.
- Built the team's eval framework adopted across 4 client engagements.

## Skills
Python · PyTorch · vLLM · CUDA (basic) · Kubernetes · Triton · FastAPI ·
PostgreSQL · Redis · AWS · Docker
`,
    },
    cover: {
      title: "Cover Letter — Anthropic",
      summary: "Opens with the inference-platform angle, ties your vLLM and reliability work to their stack, ends with a concrete first-90-days hypothesis.",
      preview: `Dear Anthropic team,

I'm writing about the Senior ML Engineer role on the Inference Platform team.
The reason this role caught my attention specifically is that I've spent the
last two years on the same problem at a smaller scale: making large models
serve cheap and stay fast under real traffic.

At Helpmate AI I built and own a vLLM-backed inference layer that serves
40M requests/day with p99 latency under 220ms. The hardest wins came from
reading kernels carefully — continuous batching tuning, KV-cache reuse, and
draft-token speculation each shaved 10–20% off p99. I expect Claude's stack
runs on a different order of magnitude, but the muscle memory is the same:
profile hard, write the design doc, run the experiment.

If I joined, my first 90 days would focus on getting deep into the request
path and the regression-eval harness — I'd want to be fast at "this PR
regressed p99 by 4ms, here's why" before I propose anything bigger.

Best,
Leander
`,
    },
  },

  assistant: {
    suggestions: [
      "Strengthen the inference-platform bullet",
      "Why did Gatekeeper flag the skills section?",
      "Rewrite the cover-letter opener",
    ],
    turns: [
      {
        role: "user",
        text: "Why did the resume drop 'Quantiphi' down to two bullets?",
      },
      {
        role: "assistant",
        text: "The JD weights inference-platform and CUDA work heavily, and your most recent role at Helpmate AI matches both. To give that experience visual weight, the older Quantiphi role was compressed to its two strongest, quantified bullets. Want me to expand it?",
      },
    ],
  },
};

window.MOCK = MOCK;
