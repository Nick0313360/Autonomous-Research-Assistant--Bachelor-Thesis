from typing import List
from module1.model.Paper import Paper


class PaperSampler:
    def __init__(self):
        pass

    def sample(self, papers: List[Paper], n: int) -> List[Paper]:
        withAbstract = [p for p in papers if p.abstract]
        withoutAbstract = [p for p in papers if not p.abstract]
        combined = withAbstract + withoutAbstract
        return combined[:n]

    def buildContext(self, papers: List[Paper]) -> str:
        lines = []
        for i, paper in enumerate(papers, 1):
            lines.append(f"\n[{i}] Title: {paper.title[:150]}")
            if paper.abstract:
                abstract = paper.abstract
                if len(abstract) > 300:
                    abstract = abstract[:300] + "..."
                lines.append(f"    Abstract: {abstract}")
        return "\n".join(lines)