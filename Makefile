.PHONY: up down logs ps verify build test test-cortex

up:            ## Start the whole stack
	docker compose up -d --build

down:          ## Stop and remove containers
	docker compose down

build:         ## Build every image without starting anything
	docker compose build

logs:          ## Tail all logs
	docker compose logs -f

ps:            ## Show service status
	docker compose ps

verify:        ## Health-check every service and print the URL map
	@echo "Services"
	@curl -fsS --max-time 5 http://localhost:8004/health        >/dev/null 2>&1 && echo "  ok    backend         http://localhost:8004"        || echo "  DOWN  backend         http://localhost:8004"
	@curl -fsS --max-time 5 http://localhost:3000               >/dev/null 2>&1 && echo "  ok    landing         http://localhost:3000"        || echo "  DOWN  landing         http://localhost:3000  (needs NEXT_PUBLIC_SUPABASE_* set)"
	@curl -fsS --max-time 5 http://localhost:3005               >/dev/null 2>&1 && echo "  ok    recruiter-app   http://localhost:3005"        || echo "  DOWN  recruiter-app   http://localhost:3005"
	@curl -fsS --max-time 5 http://localhost:3001               >/dev/null 2>&1 && echo "  ok    admin-app       http://localhost:3001  (staff only)" || echo "  DOWN  admin-app       http://localhost:3001"
	@curl -fsS --max-time 5 http://localhost:8010/api/v1/health >/dev/null 2>&1 && echo "  ok    cortex-backend  http://localhost:8010"        || echo "  DOWN  cortex-backend  http://localhost:8010"
	@curl -fsS --max-time 5 http://localhost:8020/health        >/dev/null 2>&1 && echo "  ok    cortex-mcp      http://localhost:8020"        || echo "  DOWN  cortex-mcp      http://localhost:8020"
	@curl -fsS --max-time 5 http://localhost:7474               >/dev/null 2>&1 && echo "  ok    neo4j           http://localhost:7474"        || echo "  DOWN  neo4j           http://localhost:7474"
	@curl -fsS --max-time 5 http://localhost:8011/health        >/dev/null 2>&1 && echo "  ok    voice-agent     http://localhost:8011"        || echo "  DOWN  voice-agent     http://localhost:8011  (needs OPENAI_API_KEY + DEEPGRAM_API_KEY)"
	@curl -fsS --max-time 5 http://localhost:3003               >/dev/null 2>&1 && echo "  ok    voice-frontend  http://localhost:3003"        || echo "  note  voice-frontend  http://localhost:3003  (no root page; serves /<session-token>)"
	@echo ""
	@echo "The workers are internal-only and are not published to the host:"
	@docker compose ps --format '  {{.Service}}\t{{.Status}}' 2>/dev/null | grep -E 'feedback-agent|intake-agent|intake-context-builder' || true
	@echo ""
	@echo "Open the app:  http://localhost:3005"

test:          ## Run the backend suite (Python 3.11 in Docker)
	docker build -f backend/Dockerfile.test -t openrecruiting-backend-test .
	docker run --rm -e ENV=test -v "$(PWD)/backend:/app" -w /app openrecruiting-backend-test python -m pytest -q

# tests/integration and tests/e2e need Neo4j and Supabase, so they are out of scope here.
test-cortex:   ## Run the cortex-backend unit suite (Python 3.11 in Docker)
	docker build -f cortex-backend/Dockerfile.test -t openrecruiting-cortex-backend-test cortex-backend
	docker run --rm -e ENV=test -v "$(PWD)/cortex-backend:/app" -w /app openrecruiting-cortex-backend-test python -m pytest -q tests/unit
