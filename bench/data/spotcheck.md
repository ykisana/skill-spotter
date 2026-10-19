# Human spot-check (50 items)

Mark each item: is the label right, and do the actions look like what Claude would do?
Fill in the last two columns (ok / wrong) and commit.

| item | kind | family/label | prompt | first actions | label ok? | actions ok? |
|---|---|---|---|---|---|---|
| o04954 | one_off | o04954 | JIRA-891 is about the cart validation logic. which file should I be looking at? | main.py; package.json; mcp__jira__get_issue |  |  |
| o02305 | one_off | o02305 | the getting started guide assumes yarn but we switched to pnpm, fix it | git branch; getting-started.md; getting-started.md |  |  |
| f094-n2 | hard_negative | f094-n2 | cut a release branch for the next version | Makefile; git checkout -b release/v1.14.1; git checkout -b release/v1.14.1 |  |  |
| o03684 | one_off | o03684 | security check: is the debug endpoint exposed in production? | debug.py; Grep |  |  |
| o03745 | one_off | o03745 | Verify all dependencies are using HTTPS for source control | go.mod; grep -E 'git:// http://' go.mod; ls |  |  |
| f073-v10 | positive | f073 | triage the cargo dependency PRs in checkout-services and merge anything that builds clean | mcp__github__list_pull_requests; gh pr list --label dependencies --repo p; gh pr checkout pr_number-82 |  |  |
| o02949 | one_off | o02949 | I need to query our analytics database for DAU trends - can you write the SQL? | schema.sql; dau_trends.sql |  |  |
| o01523 | one_off | o01523 | create migration to establish many-to-many relationship between users and roles | git status; 1729435000000_create_user_roles_junction |  |  |
| f048-v01 | positive | f048 | update the config reference doc for auth-service with the current env vars | Grep; settings.py; rg 'getenv\|environ' -n auth-service > /t |  |  |
| o03776 | one_off | o03776 | which SPM packages are pinned and why? | README.md; Package.swift; Package.resolved |  |  |
| o04300 | one_off | o04300 | Generate API client types from OpenAPI | openapi.yaml; npx openapi-generator-cli generate -i se |  |  |
| o04202 | one_off | o04202 | add rate limiting middleware to API endpoints - prevent abuse and DDoS | ratelimit.go; main.go; main.go |  |  |
| o02716 | one_off | o02716 | The heatmap data structure is too nested. Can we flatten it for the frontend? | heatmapBuilder.js; grep -n 'nested\\|deep\\|structure' src/re |  |  |
| o03895 | one_off | o03895 | why can't we upgrade @types/node past 18.11.9? find version constraints blocking it | npm ls @types/node; Grep; Grep |  |  |
| o02111 | one_off | o02111 | latency is high on the metrics endpoint, what's slow? | metrics.py; grep metrics logs/app.log \| grep duratio; ls -la |  |  |
| f050-v02 | positive | f050 | generate the weekly active users report for this week | weekly_metrics.sql; psql $WAREHOUSE_URL -f queries/weekly_me; python scripts/generate_report.py --week |  |  |
| o04769 | one_off | o04769 | set up automatic code signing renewal in the match lane | Fastfile; Fastfile |  |  |
| o04405 | one_off | o04405 | set up database connection pooling with configurable limits | git branch; pwd; git diff |  |  |
| o02211 | one_off | o02211 | add a debug mode that logs all flag values at startup for troubleshooting | main.go; main.go |  |  |
| o02227 | one_off | o02227 | add latency breakdowns to understand where requests spend time | middleware.go; middleware.go |  |  |
| o00053 | one_off | o00053 | get the commit hash I need for something | git log --oneline -5; git rev-parse HEAD; package.json |  |  |
| f007-v03 | positive | f007 | this PR needs eyes on it, figure out who owns these files and request their review | git diff; gh pr view 353; gh pr view 353 |  |  |
| o00233 | one_off | o00233 | are there any uncommitted changes in the working directory | git status --porcelain; ls -la |  |  |
| o00519 | one_off | o00519 | is the build number in sync with the version number? | project.pbxproj; git status; grep -i 'build\\|version' ios-app.xcodepr |  |  |
| f058-v03 | positive | f058 | we need those infra changes in eks-cluster pushed live, go through plan then ship it to production | cd terraform/eks-cluster && terraform in; terraform workspace select dev; terraform fmt -check |  |  |
| o04134 | one_off | o04134 | stub out a PagingSource for infinite scroll with Room + Retrofit | build.gradle; git log --oneline -5; UserPagingSource.kt |  |  |
| o01189 | one_off | o01189 | How long should a staging deploy take? | deployment-guide.md; pwd |  |  |
| o00485 | one_off | o00485 | backport the changelog entry from main to the 2.4.x branch | Changelog.md; git show 2.4.x:Changelog.md; Changelog.md |  |  |
| o01267 | one_off | o01267 | where's the script that does the final health check after deploy? | index.ts; find . -name '*health*' -o -name '*check; ls |  |  |
| f079-v03 | positive | f079 | bootstrap a fresh python service for fraud-detector with a dockerfile, health route, and ci pipeline wired up | uv init services/fraud-detector --python; uv init services/fraud-detector --python; pyproject.toml |  |  |
| o01715 | one_off | o01715 | the data migration is taking forever. can we optimize it with batch processing? | 2026_10_18_backfill_user_segments.sql; psql $DATABASE_URL -c "SELECT COUNT(*) F |  |  |
| o00438 | one_off | o00438 | create a changelog entry for the hotfix | CHANGELOG.md; CHANGELOG.md |  |  |
| o03596 | one_off | o03596 | Apply suggested changes to make this function more testable | git log --oneline -5; git branch; DataProcessor.swift |  |  |
| o02920 | one_off | o02920 | Find all records where the timestamp is NULL or malformed | malformed_timestamps.sql; sqlite3 analytics.db < queries/malformed |  |  |
| o04777 | one_off | o04777 | Android resource conflict: duplicate resource 'color/primary' in two libraries | build.gradle; Makefile; Grep |  |  |
| o04195 | one_off | o04195 | create a pre-commit hook that validates all YAML files before we commit them | ls -la .git/hooks/; ls -la .git/hooks/; ls -la |  |  |
| o03036 | one_off | o03036 | Why does the docker network keep disconnecting? | docker network ls; docker network inspect bridge; docker-compose.yml |  |  |
| o01219 | one_off | o01219 | List all environment variables for production | .env.prod; Grep |  |  |
| o03280 | one_off | o03280 | i need to temporarily disable the autoscaling policy on the app cluster for load testing next week | autoscaling.tf; grep -n 'autoscaling\\|HPA\\|scale_target' |  |  |
| o01508 | one_off | o01508 | create migration to add permissions column with default value | 1729410000000_add_permissions_column.sql; ls -la |  |  |
| f016-n3 | hard_negative | f016-n3 | cancel the running CI job on PR #510, I need to push a fix first | gh run list --branch feature/x; gh run cancel run_id-22 |  |  |
| o01099 | one_off | o01099 | Sentry is showing 500+ crashes from image caching—where's the code? | git status; Grep; ImageCache.swift |  |  |
| o03472 | one_off | o03472 | check if concurrent map access is safe in the metrics collector | collector.go; README.md; Grep |  |  |
| o02660 | one_off | o02660 | The customer lifetime value includes canceled subscriptions. Should we exclude them? | pwd; customer_ltv.sql; Grep |  |  |
| o01035 | one_off | o01035 | our coverage reports aren't being uploaded to codecov anymore - did someone break the CI? | ci.yml; Grep |  |  |
| f084-n1 | hard_negative | f084-n1 | apply the terraform changes to staging | terraform plan -var-file=environments/st; git status; terraform apply -var-file=environments/s |  |  |
| o04151 | one_off | o04151 | create unit test boilerplate for a Repository class | app; UserRepositoryTest.kt |  |  |
| o02278 | one_off | o02278 | Add docstring examples showing common usage patterns for the Client class | client.py; ls; client.py |  |  |
| f006-v05 | positive | f006 | kick off the release process - new branch, version bump, git tag, and a draft release on github | pyproject.toml; git checkout main && git pull origin mai; git checkout -b release/2.4.1 |  |  |
| o02673 | one_off | o02673 | The data freshness SLA is 4 hours but we're seeing 8-hour delays. Where's the bottleneck? | git diff; data_pipeline.py; grep -n 'sleep\\|wait\\|join\\|map' jobs/da |  |  |
