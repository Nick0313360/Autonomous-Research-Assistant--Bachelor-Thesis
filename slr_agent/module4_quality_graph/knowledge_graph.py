"""
MODULE 4 — Part B: Knowledge Graph
=====================================
Stores all pipeline data in Neo4j and answers research questions
via natural language using GraphCypherQAChain.

Node types:
  Paper            — title, DOI, abstract, year, source database
  SearchQuery      — query string, database, timestamp, result count
  Decision         — include/exclude/uncertain, reason, confidence, stage
  Extraction       — one field value, source passage, page number
  QualityAssessment— CASP answers, scores, grade, risk of bias
  Stage            — PRISMA stage (Identification/Screening/Eligibility/Inclusion)

Edge types:
  (SearchQuery)-[:PRODUCED]->(Paper)
  (Paper)-[:HAS_DECISION {at_stage}]->(Decision)
  (Paper)-[:HAS_EXTRACTION]->(Extraction)
  (Paper)-[:HAS_QUALITY]->(QualityAssessment)
  (Stage)-[:LEADS_TO]->(Stage)

Setup:
  1. Install Neo4j Desktop (free): https://neo4j.com/download/
  2. Create a new database, set password
  3. Add to .env:
       NEO4J_URI=bolt://localhost:7687
       NEO4J_USER=neo4j
       NEO4J_PASSWORD=your-password

Install Python deps:
  pip install langchain-neo4j neo4j langchain-openai
"""

import json
import logging
import os
from typing import Optional

from dotenv import load_dotenv
from neo4j import GraphDatabase
from langchain_neo4j import Neo4jGraph, GraphCypherQAChain
from langchain_openai import ChatOpenAI

load_dotenv()

log = logging.getLogger(__name__)

# ── Neo4j connection settings ─────────────────────────────────────────────────
NEO4J_URI      = os.getenv("NEO4J_URI",      "bolt://localhost:7687")
NEO4J_USER     = os.getenv("NEO4J_USER",     "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "password")

# ── LLM for GraphCypherQAChain ────────────────────────────────────────────────
# GraphCypherQAChain needs an LLM to convert English → Cypher query
# We use the same BFH proxy as all other modules
_llm = ChatOpenAI(
    base_url=os.getenv("API_URL"),
    api_key=os.getenv("OPENAI_API_KEY"),
    model=os.getenv("GRAPH_MODEL", "gpt-oss:120b"),
    temperature=0.0,
)


# ══════════════════════════════════════════════════════════════════════════════
# NEO4J DRIVER WRAPPER
# ══════════════════════════════════════════════════════════════════════════════

class KnowledgeGraph:
    """
    Thin wrapper around the Neo4j driver.
    Handles connection, schema setup, and all write operations.
    """

    def __init__(self):
        self.driver = GraphDatabase.driver(
            NEO4J_URI,
            auth=(NEO4J_USER, NEO4J_PASSWORD)
        )
        log.info("Connected to Neo4j at %s", NEO4J_URI)

    def close(self):
        self.driver.close()

    def run(self, cypher: str, **params):
        """Execute a Cypher query and return results."""
        with self.driver.session() as session:
            result = session.run(cypher, **params)
            return result.data()

    # ── schema / constraints ──────────────────────────────────────────────────

    def create_constraints(self):
        """
        Create uniqueness constraints so duplicate nodes are never inserted.
        These also create indexes that make lookups fast.
        """
        constraints = [
            # each paper is unique by DOI (or title if no DOI)
            "CREATE CONSTRAINT paper_doi IF NOT EXISTS "
            "FOR (p:Paper) REQUIRE p.doi IS UNIQUE",

            # each stage has a unique name
            "CREATE CONSTRAINT stage_name IF NOT EXISTS "
            "FOR (s:Stage) REQUIRE s.name IS UNIQUE",
        ]
        for c in constraints:
            try:
                self.run(c)
            except Exception as exc:
                log.debug("Constraint already exists or error: %s", exc)

    def create_prisma_stages(self):
        """
        Create the four PRISMA stage nodes and link them in order.
        These are fixed nodes that represent the pipeline stages.
        """
        stages = ["Identification", "Screening", "Eligibility", "Inclusion"]

        for stage in stages:
            self.run(
                "MERGE (s:Stage {name: $name})",
                name=stage
            )

        # link stages in order: Identification → Screening → Eligibility → Inclusion
        for i in range(len(stages) - 1):
            self.run(
                """
                MATCH (a:Stage {name: $from_stage})
                MATCH (b:Stage {name: $to_stage})
                MERGE (a)-[:LEADS_TO]->(b)
                """,
                from_stage=stages[i],
                to_stage=stages[i + 1],
            )

        log.info("PRISMA stage nodes created")


    # ── Module 1: write search metadata ──────────────────────────────────────

    def write_search_metadata(self, metadata: dict, papers: list[dict]):
        """
        Create SearchQuery node and link it to all Paper nodes it produced.
        Called once after Module 1 completes.
        """
        # create the SearchQuery node
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

        # create Paper nodes (MERGE = create if not exists, skip if exists)
        for paper in papers:
            doi = paper.get("doi") or f"notitle:{paper.get('title', '')[:50]}"
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
                abstract=paper.get("abstract", ""),
                source=paper.get("source", ""),
                query=metadata.get("initial_query", ""),
            )

        log.info("Wrote search metadata + %d paper nodes", len(papers))


    # ── Module 2: write screening decisions ──────────────────────────────────

    def write_decisions(self, decision_log: list[dict]):
        """
        Create Decision nodes and link them to Paper nodes.
        Each decision records stage, outcome, confidence, reason, and evidence.

        Called after Module 2 completes.
        """
        for entry in decision_log:
            paper  = entry.get("paper", {})
            doi    = paper.get("doi") or f"notitle:{paper.get('title', '')[:50]}"
            stage  = entry.get("stage", "2A")

            # map stage code to PRISMA stage name
            prisma_stage = "Screening"   if stage == "2A" else "Eligibility"

            self.run(
                """
                MERGE (p:Paper {doi: $doi})
                CREATE (d:Decision {
                    stage:          $stage,
                    decision:       $decision,
                    confidence:     $confidence,
                    reason:         $reason,
                    supporting_text:$supporting_text
                })
                MERGE (s:Stage {name: $prisma_stage})
                CREATE (p)-[:HAS_DECISION {at_stage: $stage}]->(d)
                CREATE (d)-[:AT_STAGE]->(s)
                """,
                doi=doi,
                stage=stage,
                decision=entry.get("decision", ""),
                confidence=entry.get("confidence") or 0.0,
                reason=entry.get("reason", ""),
                supporting_text=entry.get("supporting_text", ""),
                prisma_stage=prisma_stage,
            )

        log.info("Wrote %d decision nodes", len(decision_log))


    # ── Module 3: write extraction results ───────────────────────────────────

    def write_extractions(self, extracted_papers: list[dict]):
        """
        Create Extraction nodes for every field extracted from each paper.
        Each node stores: field name, value, source passage, page number.

        Also marks the Paper node as reaching the Inclusion stage.
        Called after Module 3 completes.
        """
        skip_keys = {"title", "doi", "sources"}  # not extracted fields

        for paper in extracted_papers:
            doi     = paper.get("doi") or f"notitle:{paper.get('title', '')[:50]}"
            sources = paper.get("sources", {})

            # mark paper as included (reached Inclusion stage)
            self.run(
                """
                MERGE (p:Paper {doi: $doi})
                MERGE (s:Stage {name: 'Inclusion'})
                MERGE (p)-[:REACHED]->(s)
                """,
                doi=doi,
            )

            # create one Extraction node per field
            for field_name, value in paper.items():
                if field_name in skip_keys or value is None:
                    continue

                source = sources.get(field_name, {})

                self.run(
                    """
                    MERGE (p:Paper {doi: $doi})
                    CREATE (e:Extraction {
                        field_name:      $field_name,
                        value:           $value,
                        supporting_text: $supporting_text,
                        page:            $page
                    })
                    CREATE (p)-[:HAS_EXTRACTION]->(e)
                    """,
                    doi=doi,
                    field_name=field_name,
                    value=str(value),   # Neo4j stores as string; Cypher can parse back
                    supporting_text=source.get("text", ""),
                    page=source.get("page", 0),
                )

        log.info("Wrote extraction nodes for %d papers", len(extracted_papers))


    # ── Module 4A: write quality assessments ─────────────────────────────────

    def write_quality_assessments(self, assessments: list[dict]):
        """
        Create QualityAssessment nodes and individual ChecklistAnswer nodes.
        Links each to its Paper node.

        Called after Module 4A completes.
        """
        for qa in assessments:
            doi = qa.get("doi") or f"notitle:{qa.get('title', '')[:50]}"

            # create the top-level QualityAssessment node
            self.run(
                """
                MERGE (p:Paper {doi: $doi})
                CREATE (q:QualityAssessment {
                    casp_score:    $casp_score,
                    rob_score:     $rob_score,
                    overall_score: $overall_score,
                    quality_grade: $quality_grade
                })
                CREATE (p)-[:HAS_QUALITY]->(q)
                """,
                doi=doi,
                casp_score=qa.get("casp_score", 0.0),
                rob_score=qa.get("rob_score", 0.0),
                overall_score=qa.get("overall_score", 0.0),
                quality_grade=qa.get("quality_grade", "low"),
            )

            # create individual answer nodes linked to the QualityAssessment
            for answer in qa.get("answers", []):
                self.run(
                    """
                    MATCH (p:Paper {doi: $doi})
                    MATCH (p)-[:HAS_QUALITY]->(q:QualityAssessment)
                    CREATE (a:ChecklistAnswer {
                        question_id:     $question_id,
                        question_text:   $question_text,
                        answer:          $answer,
                        confidence:      $confidence,
                        supporting_text: $supporting_text,
                        page:            $page
                    })
                    CREATE (q)-[:HAS_ANSWER]->(a)
                    """,
                    doi=doi,
                    question_id=answer.get("question_id", ""),
                    question_text=answer.get("question_text", ""),
                    answer=answer.get("answer", "unclear"),
                    confidence=answer.get("confidence", 0.0),
                    supporting_text=answer.get("supporting_text", ""),
                    page=answer.get("page", 0),
                )

        log.info("Wrote quality assessment nodes for %d papers", len(assessments))


# ══════════════════════════════════════════════════════════════════════════════
# GRAPHCYPHERQACHAIN — answers research questions in natural language
# ══════════════════════════════════════════════════════════════════════════════

def build_qa_chain() -> GraphCypherQAChain:
    """
    Build the LangChain GraphCypherQAChain.

    This is what lets you ask plain English questions like:
      "What is the average sensitivity of included tools?"
    And get back answers by automatically generating and running Cypher queries.

    How it works:
      1. Your question → LLM converts to Cypher query
      2. Cypher runs against Neo4j
      3. Result → LLM formats as natural language answer
    """
    graph = Neo4jGraph(
        url=NEO4J_URI,
        username=NEO4J_USER,
        password=NEO4J_PASSWORD,
    )

    # refresh schema so the chain knows what nodes/edges exist
    graph.refresh_schema()

    chain = GraphCypherQAChain.from_llm(
        llm=_llm,
        graph=graph,
        verbose=True,       # prints the generated Cypher query — useful for debugging
        return_intermediate_steps=True,  # lets you see the Cypher that ran
    )

    return chain


def answer_research_questions(qa_chain: GraphCypherQAChain) -> dict:
    """
    Run your six thesis research questions against the knowledge graph.

    Each question gets answered by:
      1. GraphCypherQAChain generating a Cypher query
      2. Running it against Neo4j
      3. LLM formatting the result as a natural language answer

    Returns dict of question → answer.
    """
    # your six research questions — edit these to match your actual RQs
    research_questions = [
        "How many papers were included in the final synthesis?",
        "What AI tools were evaluated for systematic review automation and which LLMs did they use?",
        "What is the average reported sensitivity and specificity across all included tools?",
        "Which PRISMA stages are most commonly covered by the included tools?",
        "What proportion of included papers achieved a high quality grade in the CASP assessment?",
        "What are the most frequently reported limitations across included studies?",
    ]

    answers = {}

    for question in research_questions:
        log.info("Answering: %s", question)
        try:
            result = qa_chain.invoke({"query": question})
            answers[question] = {
                "answer": result.get("result", "No answer generated"),
                "cypher": result.get("intermediate_steps", [{}])[0].get("query", ""),
            }
        except Exception as exc:
            log.warning("Failed to answer '%s': %s", question[:50], exc)
            answers[question] = {
                "answer": f"Error: {exc}",
                "cypher": "",
            }

    return answers


# ══════════════════════════════════════════════════════════════════════════════
# MAIN GRAPH POPULATION FUNCTION
# ══════════════════════════════════════════════════════════════════════════════

def run_knowledge_graph(
    search_metadata:    dict,
    papers:             list[dict],
    decision_log:       list[dict],
    extracted_papers:   list[dict],
    quality_assessments: list[dict],
) -> dict:
    """
    Populate the Neo4j knowledge graph with all pipeline outputs
    and answer the research questions.

    Called from pipeline.py knowledge_graph_node after all other modules complete.

    Input: outputs from Modules 1, 2, 3, and 4A
    Output: dict with graph stats + research question answers
    """
    kg = KnowledgeGraph()

    try:
        # ── setup ─────────────────────────────────────────────────────────────
        log.info("Setting up Neo4j schema and PRISMA stage nodes...")
        kg.create_constraints()
        kg.create_prisma_stages()

        # ── write all data ────────────────────────────────────────────────────
        log.info("Writing Module 1 data (search + papers)...")
        kg.write_search_metadata(search_metadata, papers)

        log.info("Writing Module 2 data (screening decisions)...")
        kg.write_decisions(decision_log)

        log.info("Writing Module 3 data (extraction results)...")
        kg.write_extractions(extracted_papers)

        log.info("Writing Module 4A data (quality assessments)...")
        kg.write_quality_assessments(quality_assessments)

        # ── answer research questions ─────────────────────────────────────────
        log.info("Building QA chain and answering research questions...")
        qa_chain = build_qa_chain()
        rq_answers = answer_research_questions(qa_chain)

        # ── graph stats ───────────────────────────────────────────────────────
        stats = {
            "papers_in_graph":      kg.run("MATCH (p:Paper) RETURN count(p) as n")[0]["n"],
            "decisions_in_graph":   kg.run("MATCH (d:Decision) RETURN count(d) as n")[0]["n"],
            "extractions_in_graph": kg.run("MATCH (e:Extraction) RETURN count(e) as n")[0]["n"],
            "quality_nodes":        kg.run("MATCH (q:QualityAssessment) RETURN count(q) as n")[0]["n"],
        }

        log.info("Knowledge graph populated: %s", stats)

        return {
            "graph_stats":          stats,
            "research_qa_answers":  rq_answers,
        }

    finally:
        kg.close()