# tracemalloc - built-in, shows top allocations by file/line
python -c "
import tracemalloc
tracemalloc.start()
# ... run code ...
snapshot = tracemalloc.take_snapshot()
for stat in snapshot.statistics('lineno')[:20]:
    print(stat)
"

# objgraph - find reference chains holding objects alive
python -c "
import objgraph
objgraph.show_most_common_types(limit=20)
objgraph.show_growth(limit=10)  # call twice to see what's growing
# objgraph.show_backrefs(obj, max_depth=5, filename='refs.png')
"

# memory_profiler - line-by-line memory usage
python -m memory_profiler script.py

# pympler - summarize heap by type
python -c "
from pympler import summary, muppy
all_objects = muppy.get_objects()
sum1 = summary.summarize(all_objects)
summary.print_(sum1)
"
