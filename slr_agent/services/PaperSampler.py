from typing import List
from module1.models.Paper import Paper


class PaperSampler:
    """
    Selects a representative paper sample and formats it as an LLM context block.
    Stateless utility — no attributes, no dependencies.
    """

    def __init__(self):
        pass

    def sample(self, papers: List[Paper], n: int) -> List[Paper]:
        """
        Select up to n papers, prioritising those with abstracts
        since they give the LLM more signal to work with.
        """
        withAbstract = [p for p in papers if p.abstract]
        withoutAbstract = [p for p in papers if not p.abstract]
        combined = withAbstract + withoutAbstract
        return combined[:n]

    def buildContext(self, papers: List[Paper]) -> str:
        """
        Format a list of papers into a single text block for LLM prompt injection.
        Each paper is one numbered block with title and truncated abstract.
        """
        lines = []
        for i, paper in enumerate(papers, 1):
            lines.append(f"\n[{i}] Title: {paper.title[:150]}")
            if paper.abstract:
                abstract = paper.abstract
                if len(abstract) > 300:
                    abstract = abstract[:300] + "..."
                lines.append(f"    Abstract: {abstract}")
        return "\n".join(lines)