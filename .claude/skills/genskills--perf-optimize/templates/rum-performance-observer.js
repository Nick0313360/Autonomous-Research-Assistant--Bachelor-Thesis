const observer = new PerformanceObserver((list) => {
  for (const entry of list.getEntries()) {
    // Report: entry.name, entry.startTime, entry.duration, entry.transferSize
    sendToAnalytics(entry);
  }
});
observer.observe({ type: 'resource', buffered: true });
observer.observe({ type: 'navigation', buffered: true });
observer.observe({ type: 'longtask', buffered: true });
observer.observe({ type: 'largest-contentful-paint', buffered: true });
observer.observe({ type: 'layout-shift', buffered: true });
