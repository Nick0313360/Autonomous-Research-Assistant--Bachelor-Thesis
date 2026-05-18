# Add to your Go server:
# import _ "net/http/pprof"
# go func() { http.ListenAndServe(":6060", nil) }()

# Capture heap profile
go tool pprof http://localhost:6060/debug/pprof/heap

# Compare two heap profiles to find growth
go tool pprof -base heap_before.prof heap_after.prof

# Analyze allocations (alloc_space shows total allocated, inuse_space shows current)
go tool pprof -inuse_space -cum -top http://localhost:6060/debug/pprof/heap

# Generate flame graph
go tool pprof -http=:8081 http://localhost:6060/debug/pprof/heap
