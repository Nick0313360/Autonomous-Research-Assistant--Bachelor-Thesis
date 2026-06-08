# Run benchmarks
go test -bench=. -benchmem ./...

# Run with CPU profiling
go test -bench=BenchmarkMyFunc -cpuprofile=cpu.prof -memprofile=mem.prof ./pkg/...

# Analyze profile
go tool pprof cpu.prof
# (pprof) top20
# (pprof) web  # opens flame graph in browser
# (pprof) list MyFunction  # line-by-line annotation

# Trace execution (goroutine scheduling, GC, syscalls)
go test -trace=trace.out ./...
go tool trace trace.out

# Live profiling of a running server
go tool pprof -http=:8081 http://localhost:6060/debug/pprof/profile?seconds=30
