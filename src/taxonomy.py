HARD_SKILL_KEYWORDS = [
    # Programming languages
    "Python",
    "R",
    "Java",
    "Scala",
    "C++",
    "C#",
    "JavaScript",
    "TypeScript",
    "Go",
    "Rust",
    "Ruby",
    "PHP",
    "Swift",
    "Kotlin",
    "Julia",
    "MATLAB",
    "SAS",
    "Bash",
    "Shell Scripting",
    # Data and ML
    "SQL",
    "NoSQL",
    "Machine Learning",
    "Data Analysis",
    "Data Engineering",
    "Data Modeling",
    "Data Warehousing",
    "Data Visualization",
    "Deep Learning",
    "NLP",
    "Natural Language Processing",
    "Computer Vision",
    "Reinforcement Learning",
    "Generative AI",
    "LLM",
    "RAG",
    "Prompt Engineering",
    "MLOps",
    "Feature Engineering",
    "A/B Testing",
    "Statistical Modeling",
    "Time Series",
    "Recommendation Systems",
    "ETL",
    "ELT",
    "Data Pipeline",
    # ML/AI frameworks
    "TensorFlow",
    "TensorFlow Federated",
    "PyTorch",
    "JAX",
    "Scikit-learn",
    "Keras",
    "XGBoost",
    "LightGBM",
    "Hugging Face",
    "OpenAI",
    "LangChain",
    "LlamaIndex",
    "Transformers",
    "ONNX",
    "MLflow",
    "Kubeflow",
    "Weights and Biases",
    "CUDA",
    "MPI",
    "Distributed Training",
    # Data tools
    "Pandas",
    "NumPy",
    "Spark",
    "PySpark",
    "Hadoop",
    "Hive",
    "Kafka",
    "Airflow",
    "dbt",
    "Dagster",
    "Prefect",
    "Dask",
    "Polars",
    # Visualization
    "Tableau",
    "Power BI",
    "Looker",
    "Matplotlib",
    "Plotly",
    "D3.js",
    "Grafana",
    "Excel",
    "Google Sheets",
    # Databases
    "PostgreSQL",
    "MySQL",
    "MongoDB",
    "Redis",
    "Elasticsearch",
    "DynamoDB",
    "Cassandra",
    "Neo4j",
    "Snowflake",
    "BigQuery",
    "Redshift",
    "Databricks",
    "Pinecone",
    "ChromaDB",
    "Weaviate",
    # Cloud and infrastructure
    "AWS",
    "Azure",
    "GCP",
    "Google Cloud",
    "Docker",
    "Kubernetes",
    "Terraform",
    "Ansible",
    "CI/CD",
    "GitHub Actions",
    "Jenkins",
    "Linux",
    "Nginx",
    # Web and API
    "FastAPI",
    "Flask",
    "Django",
    "Node.js",
    "Express",
    "Next.js",
    "React",
    "Vue",
    "Angular",
    "REST API",
    "REST APIs",
    "GraphQL",
    "gRPC",
    "Streamlit",
    "Gradio",
    "Tailwind",
    "Tailwind CSS",
    "Prisma",
    "LaTeX",
    # DevOps and tools
    "Git",
    "Jira",
    "Confluence",
    "Agile",
    "Scrum",
    # Security and compliance
    "OAuth",
    "RBAC",
    "SOC 2",
    "GDPR",
    "HIPAA",
    # Other technical
    "Microservices",
    "Event-Driven Architecture",
    "System Design",
    "API Design",
    "Testing",
    "Unit Testing",
    "Integration Testing",
    "Performance Testing",
    "Playwright",
    "Selenium",
    "Figma",
]

SOFT_SKILL_KEYWORDS = [
    "communication",
    "teamwork",
    "problem-solving",
    "leadership",
    "adaptability",
    "time management",
    "collaboration",
    "critical thinking",
    "stakeholder management",
    "mentoring",
    "cross-functional",
    "project management",
    "decision-making",
    "presentation",
    "negotiation",
    "conflict resolution",
    "strategic thinking",
    "attention to detail",
    "self-motivated",
    "analytical thinking",
    "creative thinking",
    "customer-focused",
    "prioritization",
    "ownership",
    "accountability",
    "empathy",
    "coaching",
    "initiative",
    "resilience",
    "influence",
]


# ---------------------------------------------------------------------------
# Skill canonicalization
# ---------------------------------------------------------------------------
#
# Both LLM parsers (resume + JD) sometimes emit different casings or short-
# forms of the same skill ('Postgres' vs 'PostgreSQL', 'k8s' vs 'Kubernetes',
# 'JS' vs 'JavaScript'). The deterministic fit-matching layer is a string-
# equality intersection — without canonicalization, synonyms fall on opposite
# sides of the match and surface as both 'matched' (rare) or 'missing' (more
# common), which then nudges TailoringAgent to recommend adding skills the
# candidate already has.
#
# This map is hand-curated and conservative. Each key is a lowercase variant
# that should collapse to the canonical lowercase form on the right. Generic
# acronyms like 'AI' / 'ML' are deliberately NOT aliased because they have
# domain-specific meanings (Adobe Illustrator vs Artificial Intelligence,
# Machine Learning vs Microsoft Lync etc.) — keeping them as-is is safer than
# false positives. Add an entry only when the synonymy is unambiguous in a
# tech-job context.

SKILL_ALIAS_MAP: dict[str, str] = {
    # Databases / storage
    "postgres": "postgresql",
    "psql": "postgresql",
    "ms sql": "sql server",
    "mssql": "sql server",
    "microsoft sql server": "sql server",
    "mongo": "mongodb",
    # Container / orchestration
    "k8s": "kubernetes",
    "kube": "kubernetes",
    # JavaScript / TypeScript ecosystem
    "js": "javascript",
    "ts": "typescript",
    "node": "node.js",
    "nodejs": "node.js",
    "node js": "node.js",
    "react.js": "react",
    "reactjs": "react",
    "react js": "react",
    "vue.js": "vue",
    "vuejs": "vue",
    "vue js": "vue",
    "next js": "next.js",
    "nextjs": "next.js",
    # Cloud platforms
    "amazon web services": "aws",
    "google cloud platform": "google cloud",
    "gcp": "google cloud",
    # Languages
    "golang": "go",
    "csharp": "c#",
    "c sharp": "c#",
    "cpp": "c++",
    "c plus plus": "c++",
    # ML frameworks
    "tf": "tensorflow",
    "tensor flow": "tensorflow",
    "scikit learn": "scikit-learn",
    "sklearn": "scikit-learn",
    "huggingface": "hugging face",
    "hugging-face": "hugging face",
    # CI / CD
    "github actions": "github actions",
    "gha": "github actions",
    "cicd": "ci/cd",
    "ci-cd": "ci/cd",
    # Data / warehousing
    "big query": "bigquery",
    # APIs
    "rest apis": "rest api",
    "restapi": "rest api",
    "graph ql": "graphql",
}


def canonicalize_skill(skill: str) -> str:
    """Return a canonical lowercase key for skill matching.

    Common synonym variants ('Postgres' / 'PostgreSQL' / 'k8s' /
    'Kubernetes' / 'JS' / 'JavaScript') all collapse to the same
    key via SKILL_ALIAS_MAP. Skills not in the map are returned
    lowercased and whitespace-normalized as their own canonical
    form. Apply on BOTH sides of a comparison so synonymous skills
    match.
    """
    if not skill:
        return ""
    normalized = " ".join(str(skill).lower().split())
    return SKILL_ALIAS_MAP.get(normalized, normalized)
