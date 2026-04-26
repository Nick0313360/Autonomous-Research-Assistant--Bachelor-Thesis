"""
PrismaLog extension utilities for v2 fields.
"""


def extend_prisma_log(prisma) -> None:
    """
    Attach v2-specific attributes to the PrismaLog singleton at runtime.
    """
    if not hasattr(prisma, "v2_totalCandidates"):
        prisma.v2_totalCandidates = 0
        prisma.v2_excludedLowSim = 0
        prisma.v2_screenedByLLM1 = 0
        prisma.v2_uncertainToLLM2 = 0
        prisma.v2_finalIncluded = 0
        prisma.v2_finalExcluded = 0
        prisma.v2_similarityThreshold = 0.0
        prisma.v2_embeddingModel = ""


# Alias for backward compatibility
_extendPrismaLog = extend_prisma_log