"""
MODULE 4B — Knowledge Graph (Fixed)
=====================================
Neo4j connection fix:
  - neo4j://   is the browser URL scheme — NOT for the Python driver
  - bolt://    is the correct scheme for neo4j-python-driver
  - Credentials hardcoded as defaults (confirmed working)
  - Connection test on startup with explicit error message
  - load_dotenv() called at top level before any client init
"""

import json
import logging
import os

from dotenv import load_dotenv

# Load .env BEFORE anything else reads env vars
load_dotenv()

from neo4j import GraphDatabase
from neo4j.exceptions import ServiceUnavailable, AuthError

log = logging.getLogger(__name__)

# ── Connection settings ────────────────────────────────────────────────────
# IMPORTANT: Use bolt:// not neo4j:// for the Python driver.
# neo4j:// is only for Neo4j Browser / Compass.
NEO4J_URI      = os.getenv("NEO4J_URI",      "bolt://127.0.0.1:7687")
NEO4J_USER     = os.getenv("NEO4J_USER",     "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "45682600")

# Normalise URI: if someone put neo4j:// in .env, convert to bolt://
if NEO4J_URI.startswith("neo4j://"):
    NEO4J_URI = NEO4J_URI.replace("neo4j://", "bolt://", 1)
    log.info("URI scheme converted neo4j:// → bolt://  (%s)", NEO4J_URI)

# ── LLM for GraphCypherQAChain ─────────────────────────────────────────────
from langchain_neo4j import Neo4jGraph, GraphCypherQAChain
from langchain_openai import ChatOpenAI

_llm = ChatOpenAI(
    base_url=os.getenv("API_URL", "https://inference.mlmp.ti.bfh.ch/api/v1"),
    api_key=os.getenv("OPENAI_API_KEY", ""),
    model=os.getenv("GRAPH_MODEL", "gpt-oss:120b"),
    temperature=0.0,
    timeout=120,
)


# ══════════════════════════════════════════════════════════════════════════════
# CONNECTION TEST
# ══════════════════════════════════════════════════════════════════════════════

def test_connection() -> bool:
    """
    Test Neo4j connectivity before attempting any writes.
    Returns True if connection succeeds, False otherwise.
    Prints a clear diagnostic message on failure.
    """
    log.info("Testing Neo4j connection: %s  user=%s", NEO4J_URI, NEO4J_USER)
    try:
        driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        driver.verify_connectivity()
        driver.close()
        log.info("✅ Neo4j connection OK")
        return True
    except ServiceUnavailable as e:
        log.error(
            "❌ Neo4j ServiceUnavailable: %s\n"
            "   Check: Is Neo4j Desktop running? Is the database started?\n"
            "   URI: %s  (must use bolt://, not neo4j://)",
            e, NEO4J_URI
        )
        return False
    except AuthError as e:
        log.error(
            "❌ Neo4j AuthError: %s\n"
            "   Check: user=%s  password=%s\n"
            "   In Neo4j Desktop → Manage → Reset password if needed.",
            e, NEO4J_USER, NEO4J_PASSWORD
        )
        return False
    except Exception as e:
        log.error("❌ Neo4j connection failed: %s  (URI: %s)", e, NEO4J_URI)
        return False


# ══════════════════════════════════════════════════════════════════════════════
# KNOWLEDGE GRAPH CLASS
# ══════════════════════════════════════════════════════════════════════════════

class KnowledgeGraph:

    def __init__(self):
        self.driver = GraphDatabase.driver(
            NEO4J_URI,
            auth=(NEO4J_USER, NEO4J_PASSWORD)
        )
        # Verify immediately — fail fast with a clear message
        self.driver.verify_connectivity()
        log.info("Connected to Neo4j at %s", NEO4J_URI)

    def close(self):
        self.driver.close()

    def run(self, cypher: str, **params):
        with self.driver.session() as session:
            # Use parameters= dict instead of **kwargs to avoid reserved keyword
            # conflicts (e.g. 'from', 'to' are Python reserved words)
            result = session.run(cypher, parameters=params)
            return result.data()

    def create_constraints(self):
        constraints = [
            "CREATE CONSTRAINT paper_doi IF NOT EXISTS FOR (p:Paper) REQUIRE p.doi IS UNIQUE",
            "CREATE CONSTRAINT stage_name IF NOT EXISTS FOR (s:Stage) REQUIRE s.name IS UNIQUE",
        ]
        for c in constraints:
            try:
                self.run(c)
            except Exception as exc:
                log.debug("Constraint: %s", exc)

    def create_prisma_stages(self):
        stages = ["Identification", "Screening", "Eligibility", "Inclusion"]
        for stage in stages:
            self.run("MERGE (s:Stage {name: $name})", name=stage)
        for i in range(len(stages) - 1):
            # Fix: renamed from/to to from_stage/to_stage — 'from' is a Python keyword
            self.run(
                "MATCH (a:Stage {name: $from_stage}) "
                "MATCH (b:Stage {name: $to_stage}) "
                "MERGE (a)-[:LEADS_TO]->(b)",
                from_stage=stages[i],
                to_stage=stages[i + 1],
            )
        log.info("PRISMA stage nodes ready")

    def write_search_metadata(self, metadata: dict, papers: list):
        self.run(
            """
            MERGE (sq:SearchQuery {query: $query, timestamp: $timestamp})
            SET sq.ai_mode     = $ai_mode,
                sq.total_found = $total_found
            """,
            query=metadata.get("initial_query", ""),
            timestamp=metadata.get("timestamp", ""),
            ai_mode=metadata.get("ai_mode", False),
            total_found=metadata.get("total_found", 0),
        )
        for paper in papers:
            doi = paper.get("doi") or f"notitle:{paper.get('title','')[:50]}"
            self.run(
                """
                MERGE (p:Paper {doi: $doi})
                SET p.title    = $title,
                    p.abstract = $abstract,
                    p.source   = $source
                WITH p
                MATCH (sq:SearchQuery {query: $query})
                MERGE (sq)-[:PRODUCED]->(p)
                """,
                doi=doi,
                title=paper.get("title", ""),
                abstract=(paper.get("abstract") or "")[:2000],
                source=paper.get("source", ""),
                query=metadata.get("initial_query", ""),
            )
        log.info("Wrote %d paper nodes", len(papers))

    def write_decisions(self, decision_log: list):
        for entry in decision_log:
            paper = entry.get("paper", {})
            doi   = paper.get("doi") or f"notitle:{paper.get('title','')[:50]}"
            stage = entry.get("stage", "2A")
            prisma_stage = "Screening" if stage == "2A" else "Eligibility"
            self.run(
                """
                MERGE (p:Paper {doi: $doi})
                CREATE (d:Decision {
                    stage: $stage, decision: $decision,
                    confidence: $confidence, reason: $reason,
                    supporting_text: $supporting_text
                })
                MERGE (s:Stage {name: $prisma_stage})
                CREATE (p)-[:HAS_DECISION {at_stage: $stage}]->(d)
                CREATE (d)-[:AT_STAGE]->(s)
                """,
                doi=doi, stage=stage,
                decision=entry.get("decision", ""),
                confidence=float(entry.get("confidence") or 0.0),
                reason=(entry.get("reason") or "")[:500],
                supporting_text=(entry.get("supporting_text") or "")[:500],
                prisma_stage=prisma_stage,
            )
        log.info("Wrote %d decision nodes", len(decision_log))

    def write_extractions(self, extracted_papers: list):
        skip = {"title", "doi", "sources"}
        for paper in extracted_papers:
            doi     = paper.get("doi") or f"notitle:{paper.get('title','')[:50]}"
            sources = paper.get("sources", {})
            self.run(
                "MERGE (p:Paper {doi: $doi}) MERGE (s:Stage {name: 'Inclusion'}) MERGE (p)-[:REACHED]->(s)",
                doi=doi,
            )
            for field_name, value in paper.items():
                if field_name in skip or value is None:
                    continue
                source = sources.get(field_name, {})
                self.run(
                    """
                    MERGE (p:Paper {doi: $doi})
                    CREATE (e:Extraction {
                        field_name: $field_name, value: $value,
                        supporting_text: $supporting_text, page: $page
                    })
                    CREATE (p)-[:HAS_EXTRACTION]->(e)
                    """,
                    doi=doi, field_name=field_name,
                    value=str(value)[:1000],
                    supporting_text=(source.get("text") or "")[:500],
                    page=source.get("page", 0),
                )
        log.info("Wrote extraction nodes for %d papers", len(extracted_papers))

    def write_quality_assessments(self, assessments: list):
        for qa in assessments:
            doi = qa.get("doi") or f"notitle:{qa.get('title','')[:50]}"
            self.run(
                """
                MERGE (p:Paper {doi: $doi})
                CREATE (q:QualityAssessment {
                    casp_score: $casp, rob_score: $rob,
                    overall_score: $overall, quality_grade: $grade
                })
                CREATE (p)-[:HAS_QUALITY]->(q)
                """,
                doi=doi,
                casp=qa.get("casp_score", 0.0),
                rob=qa.get("rob_score", 0.0),
                overall=qa.get("overall_score", 0.0),
                grade=qa.get("quality_grade", "low"),
            )
            for answer in qa.get("answers", []):
                self.run(
                    """
                    MATCH (p:Paper {doi: $doi})-[:HAS_QUALITY]->(q:QualityAssessment)
                    CREATE (a:ChecklistAnswer {
                        question_id: $qid, question_text: $qtext,
                        answer: $answer, confidence: $conf,
                        supporting_text: $supp, page: $page
                    })
                    CREATE (q)-[:HAS_ANSWER]->(a)
                    """,
                    doi=doi,
                    qid=answer.get("question_id", ""),
                    qtext=answer.get("question_text", "")[:300],
                    answer=answer.get("answer", "unclear"),
                    conf=float(answer.get("confidence") or 0.0),
                    supp=(answer.get("supporting_text") or "")[:500],
                    page=answer.get("page", 0),
                )
        log.info("Wrote quality assessments for %d papers", len(assessments))

    def get_stats(self) -> dict:
        return {
            "papers_in_graph":      self.run("MATCH (p:Paper) RETURN count(p) as n")[0]["n"],
            "decisions_in_graph":   self.run("MATCH (d:Decision) RETURN count(d) as n")[0]["n"],
            "extractions_in_graph": self.run("MATCH (e:Extraction) RETURN count(e) as n")[0]["n"],
            "quality_nodes":        self.run("MATCH (q:QualityAssessment) RETURN count(q) as n")[0]["n"],
        }


# ══════════════════════════════════════════════════════════════════════════════
# QA CHAIN
# ══════════════════════════════════════════════════════════════════════════════

def build_qa_chain() -> GraphCypherQAChain:
    graph = Neo4jGraph(url=NEO4J_URI, username=NEO4J_USER, password=NEO4J_PASSWORD)
    graph.refresh_schema()
    return GraphCypherQAChain.from_llm(
        llm=_llm, graph=graph,
        verbose=True, return_intermediate_steps=True,
    )

def answer_research_questions(qa_chain: GraphCypherQAChain) -> dict:
    questions = [
        "How many papers were included in the final synthesis?",
        "What AI tools were evaluated for systematic review automation and which LLMs did they use?",
        "What is the average reported sensitivity and specificity across all included tools?",
        "Which PRISMA stages are most commonly covered by the included tools?",
        "What proportion of included papers achieved a high quality grade in the CASP assessment?",
        "What are the most frequently reported limitations across included studies?",
    ]
    answers = {}
    for q in questions:
        try:
            result = qa_chain.invoke({"query": q})
            answers[q] = {
                "answer": result.get("result", ""),
                "cypher": (result.get("intermediate_steps") or [{}])[0].get("query", ""),
            }
        except Exception as exc:
            log.warning("RQ failed: %s — %s", q[:50], exc)
            answers[q] = {"answer": f"Error: {exc}", "cypher": ""}
    return answers


# ══════════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ══════════════════════════════════════════════════════════════════════════════

def run_knowledge_graph(
    search_metadata: dict,
    papers: list,
    decision_log: list,
    extracted_papers: list,
    quality_assessments: list,
) -> dict:
    """
    Populate Neo4j and answer research questions.
    Returns empty result dict (with error key) if connection fails.
    """
    # ── connection test first ─────────────────────────────────────────────────
    if not test_connection():
        return {
            "graph_stats": {},
            "research_qa_answers": {},
            "error": (
                f"Cannot connect to Neo4j at {NEO4J_URI}. "
                "Check: 1) Neo4j Desktop is running, 2) database is started, "
                "3) bolt:// not neo4j:// in URI."
            ),
        }

    kg = KnowledgeGraph()
    try:
        log.info("Setting up Neo4j schema…")
        kg.create_constraints()
        kg.create_prisma_stages()

        log.info("Writing Module 1 data (%d papers)…", len(papers))
        kg.write_search_metadata(search_metadata, papers)

        log.info("Writing Module 2 data (%d decisions)…", len(decision_log))
        kg.write_decisions(decision_log)

        log.info("Writing Module 3 data (%d extracted papers)…", len(extracted_papers))
        kg.write_extractions(extracted_papers)

        log.info("Writing Module 4A data (%d quality assessments)…", len(quality_assessments))
        kg.write_quality_assessments(quality_assessments)

        stats = kg.get_stats()
        log.info("Graph populated: %s", stats)

        log.info("Building QA chain and answering research questions…")
        qa_chain = build_qa_chain()
        rq_answers = answer_research_questions(qa_chain)

        return {"graph_stats": stats, "research_qa_answers": rq_answers}

    except Exception as exc:
        log.exception("Knowledge graph population failed")
        return {
            "graph_stats": {},
            "research_qa_answers": {},
            "error": str(exc),
        }
    finally:
        kg.close()