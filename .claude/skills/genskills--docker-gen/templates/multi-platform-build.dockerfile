# Build for multiple architectures:
# docker buildx build --platform linux/amd64,linux/arm64 -t app:latest --push .

# In Dockerfile, use TARGETARCH for architecture-specific logic:
ARG TARGETARCH
RUN if [ "$TARGETARCH" = "arm64" ]; then \
        echo "ARM-specific setup"; \
    fi
