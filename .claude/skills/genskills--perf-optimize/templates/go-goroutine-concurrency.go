// Use semaphore pattern to limit goroutine concurrency
sem := make(chan struct{}, maxConcurrent)
for _, item := range items {
    sem <- struct{}{}
    go func(item Item) {
        defer func() { <-sem }()
        process(item)
    }(item)
}

// Use errgroup for coordinated goroutines with error handling
g, ctx := errgroup.WithContext(ctx)
g.SetLimit(maxConcurrent)
for _, item := range items {
    g.Go(func() error {
        return process(ctx, item)
    })
}
if err := g.Wait(); err != nil { /* handle */ }

// Profile goroutine counts and blocking
// go tool pprof http://localhost:6060/debug/pprof/goroutine
// go tool pprof http://localhost:6060/debug/pprof/block
