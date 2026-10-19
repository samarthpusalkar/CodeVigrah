"""Domain definitions: mental model, what is hard and why, questions an owner should answer."""

DOMAINS = {
    'backend': {
        'label': 'Backend / API service',
        'model': 'A backend is a pipeline: request -> routing -> (auth/validation middleware) -> handler -> business logic -> data access -> response. '
        'State lives in a database/cache, not in the process, so that instances are replaceable. Most change difficulty comes from '
        'data shape (schema), contract (API consumers) and cross-cutting concerns (auth, transactions, errors).',
        'hard': [
            (
                'Changing a response/request shape',
                'The API is a contract with clients you do not control. Renaming a field is a breaking change, so the real work is versioning/compat, not the edit.',
            ),
            (
                'Changing a database column',
                'Needs a migration that runs while old code is still serving traffic (expand/contract). Code, schema and data backfill must be sequenced across deploys.',
            ),
            (
                'Adding auth/permissions late',
                'Authorization has to be enforced at every entry point and on every data query (tenant/owner filters). A missing check is a vulnerability, so you must audit all handlers.',
            ),
            (
                'Making something idempotent / retry-safe',
                'Requires a dedup key and a place to store it atomically with the side effect. Everything that retries (clients, queues) multiplies the effect of getting it wrong.',
            ),
            (
                'Fixing performance (N+1, slow queries)',
                'The cause is usually in data access patterns, far from the handler that is slow. You need query logs/EXPLAIN, and caches add invalidation problems.',
            ),
            (
                'Transactions spanning services',
                'No single ACID boundary exists; you get eventual consistency, sagas, outbox tables. Failure modes multiply.',
            ),
        ],
        'questions': [
            'Where does a request enter and where is auth enforced?',
            'Which layer owns transactions?',
            'How are errors mapped to HTTP status codes?',
            'How does the schema evolve (migrations)?',
            'What runs outside the request cycle (jobs/queues)?',
        ],
    },
    'frontend': {
        'label': 'Frontend / UI application',
        'model': 'A frontend is state -> render -> events -> state. Complexity comes from where state lives (local, shared, server cache, URL), '
        'how data is fetched/cached, and how rendering is scheduled. Components are a tree; data flows down, events flow up.',
        'hard': [
            (
                'Moving state between components',
                'State placement is an architectural decision: lifting it causes prop drilling or global-store coupling; every consumer re-renders or must subscribe correctly.',
            ),
            (
                'Fixing re-render/performance issues',
                'Cost hides in referential equality, effect dependencies and list keys. Fixes are non-local: memoisation in one place changes behaviour of children.',
            ),
            (
                'Async data + race conditions',
                'Stale responses, loading/error states, cancellation and optimistic updates multiply the number of UI states beyond what the happy path shows.',
            ),
            (
                'Accessibility and i18n retrofits',
                "They touch every component's markup and text; no single file owns them, so there is no single patch.",
            ),
            (
                'Changing the design system / styles',
                'Global CSS or utility classes couple everything; a visual change is a search across all call sites.',
            ),
            (
                'SSR / hydration bugs',
                'Code runs in two environments (server and browser) with different globals; bugs appear only when the two renders differ.',
            ),
        ],
        'questions': [
            'Where does server data get fetched and cached?',
            'What is global state vs local state?',
            'How is routing defined?',
            'How are forms validated?',
            'What is the build/bundling pipeline?',
        ],
    },
    'cli': {
        'label': 'Command-line tool',
        'model': 'A CLI is an argument parser in front of a library. The contract is the textual interface: flags, exit codes, stdout vs stderr, '
        'and stdin. Users script against it, so the interface is the API.',
        'hard': [
            (
                'Renaming/removing a flag or subcommand',
                'Scripts and CI pipelines in the wild depend on it; deprecation needs a transition period and warnings on stderr.',
            ),
            (
                'Changing output format',
                'stdout is parsed by other programs. Human-friendly output and machine-readable output (--json) need separate paths.',
            ),
            (
                'Cross-platform behaviour',
                'Paths, line endings, shells, TTY detection, colours and signals differ per OS; bugs only show on platforms you did not test.',
            ),
            (
                'Long-running operations',
                'Need progress output, SIGINT cleanup, partial-failure semantics and resumability; exit codes must signal which.',
            ),
            (
                'Config precedence',
                'flags > env > config file > defaults; adding a new source means auditing every option for conflicts.',
            ),
        ],
        'questions': [
            'Where are commands registered?',
            'What is the boundary between parsing and logic?',
            'How are errors turned into exit codes?',
            'What is read from stdin/env/config?',
        ],
    },
    'database': {
        'label': 'Database / storage engine',
        'model': 'A database engine is layers: parser -> planner/optimizer -> executor -> access methods (indexes) -> buffer/page cache -> storage/log. '
        'Correctness (durability, isolation) is the product; performance is the second job.',
        'hard': [
            (
                'Changing the on-disk format',
                'Existing data files must remain readable: versioned formats, upgrade paths, and tests with old files.',
            ),
            (
                'Concurrency control changes',
                'Isolation bugs are rare interleavings; reasoning needs invariants not tests. A small locking change can break serializability.',
            ),
            (
                'Crash recovery',
                'Every write path must be ordered correctly with the log and fsync; you must reason about a crash between any two instructions.',
            ),
            (
                'Adding a query feature',
                'Touches parser, planner, executor and often type system; each stage has its own representation.',
            ),
            (
                'Performance tuning',
                'Cache, I/O and CPU interplay; improvements in microbenchmarks often vanish or regress under mixed workloads.',
            ),
        ],
        'questions': [
            'How are pages laid out on disk?',
            'What guarantees the write-ahead log provides?',
            'Where are locks/latches taken?',
            'How does a query move from text to execution?',
        ],
    },
    'compiler': {
        'label': 'Compiler / interpreter / parser',
        'model': 'Source text -> tokens -> syntax tree -> (analysis/transforms) -> output (bytecode, code, or direct evaluation). Each phase has its own data structure; '
        'a language feature usually touches every phase.',
        'hard': [
            (
                'Adding a language feature',
                'Needs lexer, parser, AST node, semantic analysis, evaluation/codegen and error messages; omissions show up as crashes in the later phases.',
            ),
            (
                'Error messages and recovery',
                'The parser must continue after errors and keep source positions accurate through every transform.',
            ),
            (
                'Backward compatibility',
                'Existing programs define the language; subtle semantic changes break them silently.',
            ),
        ],
        'questions': [
            'Where are tokens and AST nodes defined?',
            'How are source positions preserved?',
            'How is each node evaluated/compiled?',
        ],
    },
    'ml': {
        'label': 'ML / data science / pipelines',
        'model': 'Data in -> transform -> model/computation -> artefacts out. Reproducibility (seeds, versions, data snapshots) and data shape/dtype contracts matter more than control flow.',
        'hard': [
            (
                'Reproducing results',
                'Depends on data versions, seeds, hardware and library versions; code alone does not define the result.',
            ),
            (
                'Changing a data schema',
                'Silent shape/dtype mismatches fail late (mid-training) or worse, produce wrong numbers without errors.',
            ),
            ('Scaling up', 'Memory, batching and device placement cut across every function.'),
        ],
        'questions': [
            'Where does data enter and what is its schema?',
            'What is configurable vs hard-coded?',
            'How are experiments tracked?',
        ],
    },
    'library': {
        'label': 'Library / SDK / package',
        'model': 'A library is a public API surface plus the private code behind it. The public surface is the contract; everything else may change. '
        'Design effort goes into a small, stable, composable API.',
        'hard': [
            (
                'Changing a public function signature',
                'Unknown downstream callers; needs deprecation cycle and semver discipline.',
            ),
            (
                'Supporting multiple runtime/language versions',
                'Compatibility shims leak through the codebase and multiply the test matrix.',
            ),
            ('Adding a dependency', 'Every dependency is inherited by all users and can conflict with theirs.'),
        ],
        'questions': ['What is exported publicly?', 'What is internal-only?', 'How is versioning/deprecation handled?'],
    },
    'infra': {
        'label': 'Infrastructure / DevOps',
        'model': 'Declarative descriptions of environments that are reconciled against reality. State (what exists) and drift matter more than code flow.',
        'hard': [
            (
                'Changing a live resource',
                'Some changes force replacement (downtime/data loss); you need plan output, not just a code diff.',
            ),
            (
                'Secrets and environments',
                'Many environments share code but differ in values; mistakes are environment-specific.',
            ),
        ],
        'questions': ['What are the environments?', 'Where is state stored?', 'What is the deploy order?'],
    },
    'network': {
        'label': 'Networking / protocol tool',
        'model': 'A network program is two (or more) processes exchanging bytes over sockets. A protocol defines how those bytes are framed into messages and in which order they flow. '
        'Each side is a state machine; the hard part is everything that can go wrong in between: slow peers, dropped connections, partial reads, and hostile input.',
        'hard': [
            (
                'Changing the wire protocol',
                'Old clients and new servers will talk to each other in the wild. Any message change needs a version/compat story, or both ends must upgrade together.',
            ),
            (
                'Timeouts and half-open connections',
                'A peer can vanish without closing the socket. Every read/connect needs a timeout and a cleanup path, otherwise resources leak silently.',
            ),
            (
                'Backpressure and throughput',
                'When one side is faster, buffers grow. Correct copying needs flow control, and performance problems only show under real load and latency.',
            ),
            (
                'Security of exposed ports',
                'Anything listening on a public port receives hostile traffic. Authentication, message size limits and abuse limits must hold before any trust is established.',
            ),
            (
                'Testing',
                'Real networks reorder, delay and drop. Unit tests on localhost hide most of these failure modes; end-to-end tests are slower and flakier.',
            ),
        ],
        'questions': [
            'What messages exist and how are they framed on the wire?',
            'What does each side do when the other disappears mid-conversation?',
            'Where are timeouts and size limits enforced?',
            'How is a peer authenticated before it can do anything?',
            'What is the lifetime of each connection/task?',
        ],
    },
    'mobile': {
        'label': 'Mobile app',
        'model': 'UI tree + platform lifecycle + local storage + network. The OS can kill your process at any time; state must survive that.',
        'hard': [
            (
                'Lifecycle and permissions',
                'Behaviour differs by OS version and user choices; bugs depend on device state.',
            ),
            ('Release', 'Cannot hotfix instantly; old versions live on for months, so backend compat is required.'),
        ],
        'questions': ['How is navigation structured?', 'What is persisted locally?'],
    },
    'desktop': {
        'label': 'Desktop app',
        'model': 'Main process + UI process(es) + OS integration. IPC boundaries and packaging dominate.',
        'hard': [
            ('IPC contract changes', 'Both sides must change together and updates roll out unevenly.'),
            ('Packaging/auto-update', 'Signing, platform differences.'),
        ],
        'questions': ['What runs in which process?'],
    },
    'game': {
        'label': 'Game / simulation',
        'model': 'Loop: input -> update -> render at fixed cadence. Entities and systems; performance budget per frame.',
        'hard': [
            ('Per-frame cost', 'Allocation or O(n^2) in the loop shows up as stutter, not failure.'),
            ('Determinism', 'Floating point, ordering and timing make replays and networking hard.'),
        ],
        'questions': ['What does one frame do?'],
    },
}
