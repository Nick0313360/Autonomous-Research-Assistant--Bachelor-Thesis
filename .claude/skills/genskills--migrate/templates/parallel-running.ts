async function handleRequest(req: Request) {
  const [oldResult, newResult] = await Promise.allSettled([
    legacyHandler(req),
    newHandler(req),
  ]);

  // Log discrepancies for analysis
  if (!deepEqual(oldResult, newResult)) {
    logger.warn('Migration discrepancy', { old: oldResult, new: newResult, req });
  }

  // Serve old result until confident
  return oldResult;
}
