from module1.connector.BaseConnector import BaseConnector
from module1.services.DeduplicationService import DeduplicationService
from module1.services.LLMRefinerService import LLMRefinerService
from module1.model.SearchQuery import SearchQuery
from module1.connector.QueryBuilder import QueryBuilder
from module1.model.Paper import Paper
from module1.model.SearchRun import SearchRun
from module1.connector import PubMedConnector, SemanticScholarConnector
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from module1.data.PrismaLog import PrismaLog
from module1.model.SearchIteration import SearchIteration
import logging
from typing import List, Set
from concurrent.futures import ThreadPoolExecutor
from module1.connector.PubMedConnector import PubMedConnector
from module1.connector.SemanticScholarConnector import SemanticScholarConnector

logger = logging.getLogger(__name__)


class SearchService:
    __MAX_ITERATIONS: int = 3
    __CONVERGENCE_THRESHOLD: float = 0.05  # stop if new papers < 5% of current total

    def __init__(
        self,
        connectors: List[BaseConnector],
        deduplicator: DeduplicationService,
        refiner: LLMRefinerService,
    ):
        self.__connectors: List[BaseConnector] = connectors
        self.__deduplicator: DeduplicationService = deduplicator
        self.__refiner: LLMRefinerService = refiner
        self.__queryBuilder: QueryBuilder = QueryBuilder()

    def runSearch(self, searchQuery: SearchQuery, mode: str) -> SearchRun:
        if mode == "basic":
            return self.__runBasic(searchQuery)
        elif mode == "iterative":
            return self.__runIterative(searchQuery)
        else:
            raise ValueError(f"mode must be 'basic' or 'iterative', got '{mode}'")

    def __runBasic(self, searchQuery: SearchQuery) -> SearchRun:
        logger.info("SearchService: starting basic search")

        searchRun = SearchRun(searchQuery=searchQuery, mode="basic")

        pubmedQuery = self.__queryBuilder.buildPubmed(searchQuery)
        semanticQuery = self.__queryBuilder.buildSemantic(searchQuery)

        # log query used
        prisma = PrismaLog.getInstance()
        prisma.queriesUsed.append(pubmedQuery)
        prisma.iterationsRun = 1

        # fetch from all connectors in parallel
        rawPapers = self.__executeQuery(
            pubmedQuery=pubmedQuery,
            semanticQuery=semanticQuery,
            searchQuery=searchQuery,
        )

        # deduplicate
        uniquePapers, stats = self.__deduplicator.deduplicate(rawPapers)

        # log dedup stats to prisma
        prisma.duplicatesRemovedByDoi += stats.doiDuplicates
        prisma.duplicatesRemovedByTitle += stats.titleDuplicates
        prisma.recordsAfterDeduplication = len(uniquePapers)

        # build iteration record
        iteration = SearchIteration(iterationNumber=1, queryString=pubmedQuery)
        iteration.papers = rawPapers
        iteration.resultCount = len(rawPapers)
        searchRun.addIteration(iteration)

        # finalize run
        searchRun.finalPapers = uniquePapers
        searchRun.computeTotals()

        logger.info(
            "SearchService: basic search complete — %d raw, %d unique",
            len(rawPapers), len(uniquePapers)
        )

        return searchRun
    
    def __runIterative(self, searchQuery: SearchQuery) -> SearchRun:
        # Flow per iteration:
        #   1. Build query (expanded with new terms each round)
        #   2. Fetch from all connectors in parallel
        #   3. Merge with previous results
        #   4. Deduplicate entire pool
        #   5. Feed papers to LLM refiner
        #   6. If new terms accepted → expand query and repeat
        #   7. Stop when no new terms OR max iterations reached

        logger.info("SearchService: starting iterative search")

        searchRun = SearchRun(searchQuery=searchQuery, mode="iterative")
        prisma = PrismaLog.getInstance()

        allPapers: List[Paper] = []
        usedTerms: Set[str] = set()

        # seed used_terms with words already in the PICO fields
        # so LLM does not suggest terms the user already gave us
        for keyword in searchQuery.domainKeywords:
            usedTerms.add(keyword.lower().strip())

        currentPubmedQuery = self.__queryBuilder.buildPubmed(searchQuery)
        currentSemanticQuery = self.__queryBuilder.buildSemantic(searchQuery)

        for iterationNumber in range(1, self.__MAX_ITERATIONS + 1):
            logger.info("SearchService: iteration %d", iterationNumber)

            # log query
            prisma.queriesUsed.append(currentPubmedQuery)

            # fetch
            rawPapers = self.__executeQuery(
                pubmedQuery=currentPubmedQuery,
                semanticQuery=currentSemanticQuery,
                searchQuery=searchQuery,
            )

            # merge with all previously found papers
            allPapers = self.__mergeResults([allPapers, rawPapers])

            # deduplicate entire pool
            uniquePapers, stats = self.__deduplicator.deduplicate(allPapers)

            # log dedup stats — accumulate across iterations
            prisma.duplicatesRemovedByDoi += stats.doiDuplicates
            prisma.duplicatesRemovedByTitle += stats.titleDuplicates
            prisma.recordsAfterDeduplication = len(uniquePapers)

            # record this iteration
            iteration = SearchIteration(
                iterationNumber=iterationNumber,
                queryString=currentPubmedQuery,
            )
            iteration.papers = rawPapers
            iteration.resultCount = len(rawPapers)

            # convergence check — stop early if we are not finding new papers
            if iterationNumber > 1:
                newPaperRatio = len(rawPapers) / max(len(allPapers), 1)
                if newPaperRatio < self.__CONVERGENCE_THRESHOLD:
                    logger.info(
                        "SearchService: converged at iteration %d — new paper ratio %.2f",
                        iterationNumber, newPaperRatio
                    )
                    searchRun.addIteration(iteration)
                    allPapers = uniquePapers
                    break

            # LLM refinement step
            refinementResult = self.__refiner.refineQuery(
                papers=uniquePapers,
                currentQuery=currentPubmedQuery,
                searchQuery=searchQuery,
                usedTerms=usedTerms,
                iteration=iterationNumber,
            )

            iteration.refinementResult = refinementResult
            iteration.newTerms = refinementResult.acceptedTerms
            searchRun.addIteration(iteration)

            # log terms added this iteration to prisma
            prisma.termsAddedPerIteration.append(refinementResult.acceptedTerms)

            # stop if LLM found nothing new
            if not refinementResult.acceptedTerms:
                logger.info(
                    "SearchService: no new terms at iteration %d — stopping",
                    iterationNumber
                )
                allPapers = uniquePapers
                break

            # expand query for next iteration
            # expand query for next iteration
            currentPubmedQuery = refinementResult.expandedQuery

            # S2 gets a fresh short query using only the NEW terms from this iteration
            # not the accumulated string — S2 bulk endpoint breaks above ~100 chars
            if refinementResult.acceptedTerms:
                currentSemanticQuery = " ".join(refinementResult.acceptedTerms)
            else:
                currentSemanticQuery = self.__queryBuilder.buildSemantic(searchQuery)

            allPapers = uniquePapers

        # finalize
        prisma.iterationsRun = len(searchRun.iterations)
        searchRun.finalPapers = allPapers
        searchRun.computeTotals()

        logger.info(
            "SearchService: iterative search complete — %d iterations, %d unique papers",
            len(searchRun.iterations), len(allPapers)
        )

        return searchRun


    def __executeQuery( self, pubmedQuery: str, semanticQuery: str, searchQuery: SearchQuery,) -> List[Paper]:
        pubmedPapers: List[Paper] = []
        semanticPapers: List[Paper] = []

        pubmedConnector = None
        semanticConnector = None

        for connector in self.__connectors:
            if isinstance(connector, PubMedConnector):
                pubmedConnector = connector
            elif isinstance(connector, SemanticScholarConnector):
                semanticConnector = connector

        prisma = PrismaLog.getInstance()

        try:
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = {}

                if pubmedConnector:
                    futures["pubmed"] = executor.submit(
                        pubmedConnector.fetchPapers,
                        pubmedQuery,
                        searchQuery.maxPapersPerDb
                    )
                if semanticConnector:
                    futures["semantic"] = executor.submit(
                        semanticConnector.fetchPapers,
                        semanticQuery,
                        searchQuery.maxPapersPerDb
                    )

                if "pubmed" in futures:
                    try:
                        pubmedPapers = futures["pubmed"].result()
                        prisma.identifiedPubMed += len(pubmedPapers)
                        logger.info("PubMed returned %d papers", len(pubmedPapers))
                    except Exception as e:
                        logger.error("PubMed connector failed: %s", e)

                if "semantic" in futures:
                    try:
                        semanticPapers = futures["semantic"].result()
                        prisma.identifiedSemanticScholar += len(semanticPapers)
                        logger.info("SemanticScholar returned %d papers", len(semanticPapers))
                    except Exception as e:
                        logger.error("SemanticScholar connector failed: %s", e)

        except Exception as e:
            logger.error("SearchService.__executeQuery failed: %s", e)

        return self.__mergeResults([pubmedPapers, semanticPapers])

    def __mergeResults(self, results: List[List[Paper]]) -> List[Paper]:
        flat: List[Paper] = []
        for sublist in results:
            flat.extend(sublist)
        return flat
