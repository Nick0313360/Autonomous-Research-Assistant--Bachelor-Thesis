# Graph Report - systematic-review-system  (2026-05-03)

## Corpus Check
- 120 files · ~1,079,042 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1393 nodes · 2207 edges · 52 communities detected
- Extraction: 76% EXTRACTED · 24% INFERRED · 0% AMBIGUOUS · INFERRED: 519 edges (avg confidence: 0.69)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Community 0|Community 0]]
- [[_COMMUNITY_Community 1|Community 1]]
- [[_COMMUNITY_Community 2|Community 2]]
- [[_COMMUNITY_Community 3|Community 3]]
- [[_COMMUNITY_Community 4|Community 4]]
- [[_COMMUNITY_Community 5|Community 5]]
- [[_COMMUNITY_Community 6|Community 6]]
- [[_COMMUNITY_Community 7|Community 7]]
- [[_COMMUNITY_Community 8|Community 8]]
- [[_COMMUNITY_Community 9|Community 9]]
- [[_COMMUNITY_Community 10|Community 10]]
- [[_COMMUNITY_Community 11|Community 11]]
- [[_COMMUNITY_Community 12|Community 12]]
- [[_COMMUNITY_Community 13|Community 13]]
- [[_COMMUNITY_Community 14|Community 14]]
- [[_COMMUNITY_Community 15|Community 15]]
- [[_COMMUNITY_Community 16|Community 16]]
- [[_COMMUNITY_Community 17|Community 17]]
- [[_COMMUNITY_Community 18|Community 18]]
- [[_COMMUNITY_Community 19|Community 19]]
- [[_COMMUNITY_Community 20|Community 20]]
- [[_COMMUNITY_Community 21|Community 21]]
- [[_COMMUNITY_Community 22|Community 22]]
- [[_COMMUNITY_Community 23|Community 23]]
- [[_COMMUNITY_Community 24|Community 24]]
- [[_COMMUNITY_Community 25|Community 25]]
- [[_COMMUNITY_Community 26|Community 26]]
- [[_COMMUNITY_Community 27|Community 27]]
- [[_COMMUNITY_Community 28|Community 28]]
- [[_COMMUNITY_Community 29|Community 29]]
- [[_COMMUNITY_Community 30|Community 30]]
- [[_COMMUNITY_Community 31|Community 31]]
- [[_COMMUNITY_Community 32|Community 32]]
- [[_COMMUNITY_Community 34|Community 34]]
- [[_COMMUNITY_Community 36|Community 36]]
- [[_COMMUNITY_Community 49|Community 49]]
- [[_COMMUNITY_Community 54|Community 54]]
- [[_COMMUNITY_Community 55|Community 55]]
- [[_COMMUNITY_Community 56|Community 56]]
- [[_COMMUNITY_Community 57|Community 57]]
- [[_COMMUNITY_Community 58|Community 58]]
- [[_COMMUNITY_Community 59|Community 59]]
- [[_COMMUNITY_Community 60|Community 60]]
- [[_COMMUNITY_Community 61|Community 61]]
- [[_COMMUNITY_Community 62|Community 62]]
- [[_COMMUNITY_Community 63|Community 63]]
- [[_COMMUNITY_Community 64|Community 64]]
- [[_COMMUNITY_Community 65|Community 65]]
- [[_COMMUNITY_Community 66|Community 66]]
- [[_COMMUNITY_Community 67|Community 67]]
- [[_COMMUNITY_Community 68|Community 68]]
- [[_COMMUNITY_Community 69|Community 69]]

## God Nodes (most connected - your core abstractions)
1. `ScreeningOrchestrator` - 26 edges
2. `ScreeningOutput` - 24 edges
3. `Assessor` - 23 edges
4. `ReviewProtocol` - 20 edges
5. `FullTextScreener` - 20 edges
6. `CandidateRecord` - 19 edges
7. `screen_abstract_ensemble()` - 19 edges
8. `calibrate()` - 19 edges
9. `PRISMAManager` - 19 edges
10. `StructuredDocument` - 18 edges

## Surprising Connections (you probably didn't know these)
- `load_protocol()` --calls--> `ReviewProtocol`  [INFERRED]
  main.py → models/data_classes.py
- `_run()` --calls--> `MainOrchestrator`  [INFERRED]
  main.py → orchestrators/main_orchestrator.py
- `MainOrchestrator` --uses--> `PRISMAReporter`  [INFERRED]
  orchestrators/main_orchestrator.py → tier3_synthesis/prisma_reporter.py
- `DomainJudgment` --uses--> `SectionLabel`  [INFERRED]
  tier3_synthesis/quality_assessor.py → models/data_classes.py
- `DomainJudgment` --uses--> `StructuredDocument`  [INFERRED]
  tier3_synthesis/quality_assessor.py → models/data_classes.py

## Communities

### Community 0 - "Community 0"
Cohesion: 0.03
Nodes (100): BaseModel, compute_raw_scores(), Run the Tier-2 hybrid ranker on *topic_parquet* and return raw scores.      Para, Enum, AbstractContext, CandidateRecord, CriterionResult, CriterionType (+92 more)

### Community 1 - "Community 1"
Cohesion: 0.03
Nodes (54): main(), object, Assessor, Manager the assessment module of the TAR framework., Provide training data for training ranker         :param type:         :return:, bm25_okapi_rank(), preprocess_text(), Ranker (+46 more)

### Community 2 - "Community 2"
Cohesion: 0.03
Nodes (57): _cache_key(), cosine_similarity(), _l2_normalize(), output_dim(), infrastructure/encoder.py ========================= Shared embedding service for, Embed a paper title + abstract.          Returns shape (128,) — or (768,) in fal, Embed a PICO struct.          Returns shape (128,) — or (768,) in fallback mode., Embed a document section prefixed with its label.          Returns shape (256,) (+49 more)

### Community 3 - "Community 3"
Cohesion: 0.03
Nodes (56): fetch_abstracts(), Fetch title+abstract for each PMID from PubMed (MEDLINE format), caching in cach, SearchQuery, Manages the iterative search-refine loop for a single review.      Parameters, Execute the full search pipeline and return deduplicated candidates.          Pa, SearchOrchestrator, _check_keywords(), _check_saturation() (+48 more)

### Community 4 - "Community 4"
Cohesion: 0.04
Nodes (70): _compute_wss(), _empty_dataframe(), _find_theta_hat_idx(), main(), _plot_pareto(), run_sweep(), _run_topic(), _compute_wss() (+62 more)

### Community 5 - "Community 5"
Cohesion: 0.05
Nodes (62): EnsembleResult, _int_to_vote(), _majority_and_u(), _parse_vote(), cascade_rc/cache/llm_ensemble.py =================================== B=5 stochas, Run B=n_calls stochastic screenings of one abstract and aggregate the votes., Map a parsed LLM JSON response to a vote label., Map Vote label to integer: Include→1, Exclude→0, Uncertain→2. (+54 more)

### Community 6 - "Community 6"
Cohesion: 0.04
Nodes (38): dict, __getattr__(), Lazy-load heavy modules (encoder, storage) only when accessed., DecisionLogger, infrastructure/logger.py ======================== Thread-safe SQLite audit log f, Persist one DecisionRecord.  Overwrites on duplicate record_id., Return all decisions for a single paper, oldest first., Return all decisions recorded at a given pipeline stage. (+30 more)

### Community 7 - "Community 7"
Cohesion: 0.04
Nodes (59): _empty_df(), _get_topic_title(), AUTOSTOP baseline driver for CASCADE-RC.  Runs the AUTOSTOP CAL loop (Li & Kanou, Run AUTOSTOP sweep and write autostop_results.parquet to out_dir., Return the systematic review title from CLEF-TAR topic file, or topic_id as fall, Run AUTOSTOP for a single (topic_id, target_recall) pair., _run_one(), run_sweep() (+51 more)

### Community 8 - "Community 8"
Cohesion: 0.05
Nodes (20): AreaBasedMeasures, CostBasedMeasure, CountBasedMeasures, DescriptionMeasures, EvalMeasure, GainBasedMeasures, LossBasedMeasures, MAPBasedMeasures (+12 more)

### Community 9 - "Community 9"
Cohesion: 0.06
Nodes (30): _bm25_rank(), _build_training_dicts(), _empty_df(), _get_topic_title(), _infer_one(), _inject_globals(), _linear_schedule(), _load_training_qrels() (+22 more)

### Community 10 - "Community 10"
Cohesion: 0.07
Nodes (39): apply_platt(), CalibratorBundle, fit_calibrators(), fit_platt(), load_calibrator(), main(), cascade_rc/data/score_normalizer.py ===================================== Calibr, Fit iso + Platt on train fold; pick lower-NLL on val fold; return bundle dict. (+31 more)

### Community 11 - "Community 11"
Cohesion: 0.06
Nodes (45): abstention_rate(), bootstrap_eta_upper(), _derive_routing(), llm_query_volume(), main(), _predictions_from_routing(), Evaluation metrics for CASCADE-RC systematic review screening., Bootstrap (1−delta) upper confidence bound on mean slack per grid point.      Ar (+37 more)

### Community 12 - "Community 12"
Cohesion: 0.07
Nodes (11): AutoVivification, file_exists(), Helper function which returns a boolean value indicating if the file specified b, TopicDocumentFileHandler, For TREC QREL the Format is:             Topic Iteration Document Judgement, TrecQrelHandler, process_trec_line(), Returns an ordered list of tuples (doc,rank, score) (+3 more)

### Community 13 - "Community 13"
Cohesion: 0.07
Nodes (29): _crc_threshold(), _empty_df(), Selective Conformal Risk Control (SCRC-I and SCRC-T) baseline.  Reference: Xu, G, Fit selection threshold tau_ and CRC threshold lambda_star_.          Args:, Classify each document as 'accept' or 'abstain'.          Returns an object-dtyp, Run SCRC sweep and write scrc_results.parquet to out_dir.      Args:         dat, Split-conformal FNR quantile threshold.      Among n_pos calibration positive sc, Selective Conformal Risk Control for TAR document screening.      Two variants: (+21 more)

### Community 14 - "Community 14"
Cohesion: 0.07
Nodes (29): ExtractedElement, _decide(), _fill_template(), _format_pico(), _map_p_satisfy(), _noisy_or(), tier2_screening/abstract_screener.py ====================================== Abst, Safely substitute named placeholders without interpreting other braces. (+21 more)

### Community 15 - "Community 15"
Cohesion: 0.09
Nodes (31): _compute_m_grid(), _compute_wss(), _empty_dataframe(), main(), _plot_overview(), _plot_topic(), Run m-sensitivity sweep for one topic.      Returns:         (rows, skipped): ro, Save 3-panel figure for one topic: WSS@95 / mean η̂⁻⋆ / abstention. (+23 more)

### Community 16 - "Community 16"
Cohesion: 0.11
Nodes (23): grid(), loss_tensor(), Vectorised dominating loss tensor for CASCADE-RC calibration (§4).  Loss formula, Return an equispaced grid on [0,1]^3 with λ_lo ≤ λ_hi enforced.      Args:, Compute the dominating loss for every (θ, positive example) pair.      Args:, Slack η_i(θ) = L̃_i(θ) − L_i(θ) for each (grid point, calibration positive)., slack_tensor(), loss_reference_python() (+15 more)

### Community 17 - "Community 17"
Cohesion: 0.13
Nodes (22): _cert_dir(), CertificateStore, CertificationResult, delete_partial(), _json_path(), load(), load_partial(), _partial_path() (+14 more)

### Community 18 - "Community 18"
Cohesion: 0.13
Nodes (17): _approx_tokens(), build(), _build_context(), _criterion_keywords(), _decide(), _fill_template(), _format_pico(), _infer_section() (+9 more)

### Community 19 - "Community 19"
Cohesion: 0.13
Nodes (18): _ons_lambda(), Predictable-plug-in betting lower confidence bounds (CASCADE-RC §5.2).  Provides, Online Newton Step betting strategy for [0,1]-bounded observations.      Impleme, Return the time-uniform one-sided lower confidence bound at level 1-delta., Bonferroni-corrected LCB for every point on the calibration grid.      Each grid, wsr_lcb_grid(), wsr_lcb_one_sided(), _hoeffding_lcb() (+10 more)

### Community 20 - "Community 20"
Cohesion: 0.13
Nodes (18): _h1_scalar(), _h1_vec(), hb_pvalue_scalar(), hb_pvalues(), Hoeffding-Bentkus hybrid p-value for LTT grid calibration.  Implements the HB p-, KL divergence h₁(a, b) for scalars; returns 1 when a > b., Vectorised h₁; a must satisfy a ≤ b element-wise (enforced by caller)., Single-θ HB p-value — reference implementation for cross-checking.      Equivale (+10 more)

### Community 21 - "Community 21"
Cohesion: 0.19
Nodes (10): _aggregate(), DomainJudgment, _fill_template(), _gather_domains(), QualityAssessor, tier3_synthesis/quality_assessor.py ======================================= Meth, Safely substitute named placeholders without interpreting other braces., Assesses methodological quality for each included study.      Uses RoB 2 for RCT (+2 more)

### Community 22 - "Community 22"
Cohesion: 0.13
Nodes (17): _order_riskiest_to_safest(), Safest-to-riskiest fixed-sequence walker for LTT grid calibration.  Implements t, Return indices that lex-sort the grid by (λ_lo, λ_hi, τ_SE) ascending.      The, Fixed-sequence walk: reject H_θ for each θ in order until first acceptance., safest_to_riskiest_order(), walk_reject(), Tests for safest-to-riskiest walker (cascade_rc/calibration/walker.py).  TDD RED, Fixed-sequence walk rejects until the first acceptance, then stops.      p-value (+9 more)

### Community 23 - "Community 23"
Cohesion: 0.14
Nodes (6): DataLoader, Load data.         @param query_file: e.g. {"id": 1, "query": , "title": }, read_doc_ids(), read_doc_texts(), read_qrels(), read_title()

### Community 24 - "Community 24"
Cohesion: 0.21
Nodes (9): Outcome of a full-text retrieval attempt for a single candidate., RetrievalResult, _best_pdf_url(), _download_file(), FullTextRetriever, tier2_screening/fulltext_retriever.py ======================================= Fu, Convert a PubMed ID to a PMC ID via Entrez elink., Retrieves full-text documents for a list of abstract-screened candidates.      P (+1 more)

### Community 25 - "Community 25"
Cohesion: 0.17
Nodes (8): ExampleBuffer, tier2_screening/example_buffer.py ==================================== In-memory, Rebuild faiss IndexFlatIP from all stored embeddings., Few-shot example store.      ``get_similar`` retrieves examples whose embeddings, Parameters         ----------         encoder : SharedEncoderService, optional, Add *example* if its confidence is >= 0.90.          Rebuilds the faiss index af, Return up to *n* examples nearest to *query_embedding* (cosine)., ScreeningExample

### Community 26 - "Community 26"
Cohesion: 0.18
Nodes (10): _fake_autostop(), _make_topic_parquet(), Tests for cascade_rc.baselines.run_autostop., Verify astype(_OUTPUT_SCHEMA) produces correct column dtypes., pd.concat of autostop_df and rlstop_df must yield 8 rows, no NaN method column., Side-effect for mock: write fake CSV and run file to current RET_DIR.      Must, Functional test: mocked autostop_method writes expected files; driver parses the, test_output_schema_dtypes_after_real_run() (+2 more)

### Community 27 - "Community 27"
Cohesion: 0.21
Nodes (7): infrastructure/storage.py ========================= Simple versioned JSON artifa, Load and deserialise a previously stored artifact.          Raises         -----, Return a sorted list of available version tags for *artifact_type*.          The, Versioned JSON artifact store for one review run.      Parameters     ----------, Serialise *content* to JSON and save it under the appropriate subfolder., _subfolder_for(), VersionedStorage

### Community 28 - "Community 28"
Cohesion: 0.25
Nodes (10): fetch_abstracts(), _fetch_batch(), _make_retry(), _parse_pubmed_article(), Async PubMed abstract fetcher with per-PMID caching and rate limiting., Fetch PubMed abstracts for *pmids* with per-PMID JSON caching.      Returns a ma, Remove residual XML/HTML tags and normalise whitespace., Extract title, abstract, and MeSH terms from a single <PubmedArticle>. (+2 more)

### Community 29 - "Community 29"
Cohesion: 0.5
Nodes (3): Subprocess wrapper for the vendored CLEF TAR evaluation script.  Output format:, Run vendored CLEF tar_eval.py and return parsed metric dict.      Captures both, run_tar_eval()

### Community 30 - "Community 30"
Cohesion: 0.67
Nodes (1): config/settings.py ================== Central configuration for the autonomous s

### Community 31 - "Community 31"
Cohesion: 1.0
Nodes (1): Run domain tasks concurrently; substitute SOME_CONCERNS on failure.

### Community 32 - "Community 32"
Cohesion: 1.0
Nodes (1): Return a new SearchQuery with new_terms merged into domain_keywords.

### Community 34 - "Community 34"
Cohesion: 1.0
Nodes (1): Run the full orchestrator once and stash the result + PRISMA on the         clas

### Community 36 - "Community 36"
Cohesion: 1.0
Nodes (1): Convert abstract-stage decisions to FinalDecision objects when full-text

### Community 49 - "Community 49"
Cohesion: 1.0
Nodes (1): Only used in autotar_method.         @param doc_text_file:         @return:

### Community 54 - "Community 54"
Cohesion: 1.0
Nodes (1): Return the SectionLabel of the section that contains *span*.

### Community 55 - "Community 55"
Cohesion: 1.0
Nodes (1): Aggregate criterion results into a ScreeningResult.

### Community 56 - "Community 56"
Cohesion: 1.0
Nodes (1): Return sentences from METHODS and RESULTS sections.

### Community 57 - "Community 57"
Cohesion: 1.0
Nodes (1): Return up to _MAX_CANDIDATES sentences that contain any keyword.

### Community 58 - "Community 58"
Cohesion: 1.0
Nodes (1): Return a PICORecord populated from the protocol targets at low confidence.

### Community 59 - "Community 59"
Cohesion: 1.0
Nodes (1): Return the most direct OA PDF URL from an Unpaywall response.          Only retu

### Community 60 - "Community 60"
Cohesion: 1.0
Nodes (1): Stream *url* to *dest*.  Raises aiohttp.ClientResponseError on HTTP error.

### Community 61 - "Community 61"
Cohesion: 1.0
Nodes (1): Tokenise document into sentences and build both indices.

### Community 62 - "Community 62"
Cohesion: 1.0
Nodes (1): Concatenate top-scored sentences up to _TOKEN_BUDGET tokens.         Preserves s

### Community 63 - "Community 63"
Cohesion: 1.0
Nodes (1): Concatenate all section texts into a single string.

### Community 64 - "Community 64"
Cohesion: 1.0
Nodes (1): Extract text from <abstract> elements.

### Community 65 - "Community 65"
Cohesion: 1.0
Nodes (1): Map a <sec> element to a SectionLabel.

### Community 66 - "Community 66"
Cohesion: 1.0
Nodes (1): Recursively concatenate all text content of an element.

### Community 67 - "Community 67"
Cohesion: 1.0
Nodes (1): Cosine similarity between two vectors.          Because all outputs from this se

### Community 68 - "Community 68"
Cohesion: 1.0
Nodes (1): Expected output dimensionality per head (768 in fallback mode).

### Community 69 - "Community 69"
Cohesion: 1.0
Nodes (1): Return a shallow copy of the current PRISMAState (thread-safe read).

## Knowledge Gaps
- **437 isolated node(s):** `main.py ======= CLI entry point for the Autonomous Systematic Review System.  Us`, `Deserialise a ReviewProtocol from a JSON file.`, `tier3_synthesis/prisma_reporter.py ===================================== Generat`, `Accept either a dict (prisma_counts) or a PRISMAManager / PRISMAState.`, `Parameters     ----------     output_dir : str | Path — base directory for saved` (+432 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **Thin community `Community 30`** (3 nodes): `__init__.py`, `settings.py`, `config/settings.py ================== Central configuration for the autonomous s`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 31`** (1 nodes): `Run domain tasks concurrently; substitute SOME_CONCERNS on failure.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 32`** (1 nodes): `Return a new SearchQuery with new_terms merged into domain_keywords.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 34`** (1 nodes): `Run the full orchestrator once and stash the result + PRISMA on the         clas`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 36`** (1 nodes): `Convert abstract-stage decisions to FinalDecision objects when full-text`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 49`** (1 nodes): `Only used in autotar_method.         @param doc_text_file:         @return:`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 54`** (1 nodes): `Return the SectionLabel of the section that contains *span*.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 55`** (1 nodes): `Aggregate criterion results into a ScreeningResult.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 56`** (1 nodes): `Return sentences from METHODS and RESULTS sections.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 57`** (1 nodes): `Return up to _MAX_CANDIDATES sentences that contain any keyword.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 58`** (1 nodes): `Return a PICORecord populated from the protocol targets at low confidence.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 59`** (1 nodes): `Return the most direct OA PDF URL from an Unpaywall response.          Only retu`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 60`** (1 nodes): `Stream *url* to *dest*.  Raises aiohttp.ClientResponseError on HTTP error.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 61`** (1 nodes): `Tokenise document into sentences and build both indices.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 62`** (1 nodes): `Concatenate top-scored sentences up to _TOKEN_BUDGET tokens.         Preserves s`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 63`** (1 nodes): `Concatenate all section texts into a single string.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 64`** (1 nodes): `Extract text from <abstract> elements.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 65`** (1 nodes): `Map a <sec> element to a SectionLabel.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 66`** (1 nodes): `Recursively concatenate all text content of an element.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 67`** (1 nodes): `Cosine similarity between two vectors.          Because all outputs from this se`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 68`** (1 nodes): `Expected output dimensionality per head (768 in fallback mode).`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 69`** (1 nodes): `Return a shallow copy of the current PRISMAState (thread-safe read).`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `CascadeRCConfig` connect `Community 4` to `Community 11`, `Community 15`, `Community 5`, `Community 7`?**
  _High betweenness centrality (0.169) - this node is a cross-community bridge._
- **Why does `_infer_one()` connect `Community 9` to `Community 11`, `Community 6`?**
  _High betweenness centrality (0.147) - this node is a cross-community bridge._
- **Why does `wss_at_recall()` connect `Community 11` to `Community 4`, `Community 7`, `Community 9`, `Community 13`, `Community 15`?**
  _High betweenness centrality (0.147) - this node is a cross-community bridge._
- **Are the 21 inferred relationships involving `ScreeningOrchestrator` (e.g. with `MainOrchestrator` and `AbstractContext`) actually correct?**
  _`ScreeningOrchestrator` has 21 INFERRED edges - model-reasoned connections that need verification._
- **Are the 20 inferred relationships involving `ScreeningOutput` (e.g. with `MainOrchestrator` and `AbstractContext`) actually correct?**
  _`ScreeningOutput` has 20 INFERRED edges - model-reasoned connections that need verification._
- **Are the 8 inferred relationships involving `Assessor` (e.g. with `score_distribion_training_fitting()` and `score_distribion_feedback_uniform()`) actually correct?**
  _`Assessor` has 8 INFERRED edges - model-reasoned connections that need verification._
- **Are the 18 inferred relationships involving `ReviewProtocol` (e.g. with `ExtractedField` and `ExtractedData`) actually correct?**
  _`ReviewProtocol` has 18 INFERRED edges - model-reasoned connections that need verification._