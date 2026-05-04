# Option 1: tini (recommended for most stacks)
RUN apk add --no-cache tini
ENTRYPOINT ["/sbin/tini", "--"]
CMD ["node", "server.js"]

# Option 2: dumb-init
RUN apt-get update && apt-get install -y --no-install-recommends dumb-init && rm -rf /var/lib/apt/lists/*
ENTRYPOINT ["dumb-init", "--"]

# Option 3: Docker's built-in init (no Dockerfile change needed)
# docker run --init <image>
# In compose: init: true
