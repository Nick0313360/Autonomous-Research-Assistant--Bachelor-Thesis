git bisect start
git bisect bad HEAD
git bisect good <known-good-commit>
# Git checks out a midpoint - test it, then:
git bisect good   # if this commit works
git bisect bad    # if this commit is broken
# Repeat until git identifies the first bad commit
git bisect reset  # clean up when done
