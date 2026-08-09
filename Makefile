.PHONY: up down logs ps verify build test test-cortex verify-local-llm

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
	@# /health/liveliness answers 200 with no key and with a wrong one, so it cannot
	@# tell a working master key from a broken one. Probe an authenticated endpoint
	@# instead, and fall back to liveliness only to tell "key is wrong" from "down".
	@KEY=$$(grep '^LITELLM_MASTER_KEY=' .env 2>/dev/null | cut -d= -f2-); \
	if curl -fsS --max-time 5 -H "Authorization: Bearer $$KEY" http://localhost:4000/model/info >/dev/null 2>&1; then \
		echo "  ok    litellm         http://localhost:4000"; \
	elif curl -fsS --max-time 5 http://localhost:4000/health/liveliness >/dev/null 2>&1; then \
		echo "  WARN  litellm         http://localhost:4000  (up, but LITELLM_MASTER_KEY is missing or rejected)"; \
	else \
		echo "  DOWN  litellm         http://localhost:4000"; \
	fi
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

# tests/integration is hermetic (it mocks Supabase/Graphiti), so it runs here too;
# tests marked live_infra want a real Neo4j/Supabase and drop out. Excluded: tests/e2e is
# order-fragile via the @lru_cache'd get_settings(), and tests/test_health.py has an async
# fixture that pytest-asyncio strict mode cannot run. See cortex-backend/Dockerfile.test.
test-cortex:   ## Run the cortex-backend unit + integration suite (Python 3.11 in Docker)
	docker build -f cortex-backend/Dockerfile.test -t openrecruiting-cortex-backend-test cortex-backend
	docker run --rm -e ENV=test -v "$(PWD)/cortex-backend:/app" -w /app openrecruiting-cortex-backend-test python -m pytest -q -m "not live_infra" tests/unit tests/integration

verify-local-llm: ## Prove the gateway reaches a local Ollama model
	@echo "Checking Ollama is up on the host..."
	@curl -fsS --max-time 5 http://localhost:11434/api/tags >/dev/null 2>&1 \
		&& echo "  ok    ollama          http://localhost:11434" \
		|| { echo "  DOWN  ollama — start it with: ollama serve"; exit 1; }
	@echo "Asking the gateway for gemma-local..."
	@KEY=$$(grep '^LITELLM_MASTER_KEY=' .env | cut -d= -f2-); \
	curl -fsS --max-time 120 http://localhost:4000/v1/chat/completions \
		-H "Authorization: Bearer $$KEY" \
		-H "Content-Type: application/json" \
		-d '{"model":"gemma-local","messages":[{"role":"user","content":"Reply with the single word: ready"}],"max_tokens":16}' \
		| python3 -c "import sys,json; d=json.load(sys.stdin); print('  reply:', d['choices'][0]['message']['content'].strip())"
