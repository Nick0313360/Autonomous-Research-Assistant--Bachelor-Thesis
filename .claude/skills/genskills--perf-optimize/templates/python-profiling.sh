# cProfile - function-level profiling
python -m cProfile -s cumulative app.py
# Or programmatic:
# import cProfile; cProfile.run('main()', 'output.prof')
# Then visualize: python -m snakeviz output.prof

# line_profiler - line-by-line timing (decorate functions with @profile)
pip install line_profiler
kernprof -l -v script.py

# py-spy - sampling profiler, attaches to running process with no code changes
pip install py-spy
py-spy top --pid <PID>
py-spy record -o profile.svg --pid <PID>  # generates flame graph SVG

# scalene - CPU, GPU, and memory profiler combined
pip install scalene
python -m scalene script.py
