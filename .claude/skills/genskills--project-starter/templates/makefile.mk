.PHONY: dev test build lint format clean docker-up docker-down db-migrate db-seed

dev:                     ## Start development server
	pnpm dev

test:                    ## Run unit tests
	pnpm test

test-coverage:           ## Run tests with coverage
	pnpm test:coverage

test-e2e:                ## Run E2E tests
	pnpm test:e2e

lint:                    ## Run linter
	pnpm lint

format:                  ## Format code
	pnpm format

build:                   ## Build for production
	pnpm build

clean:                   ## Remove build artifacts
	rm -rf dist node_modules .turbo

docker-up:               ## Start Docker services
	docker compose up -d

docker-down:             ## Stop Docker services
	docker compose down

db-migrate:              ## Run database migrations
	pnpm db:migrate

db-seed:                 ## Seed database
	pnpm db:seed

help:                    ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

.DEFAULT_GOAL := help
