<agents_guidance>
  <global_rule>
    All critical preconditions must fail fast (schema, embeddings, dependency versions). Never allow silent fallbacks.
  </global_rule>

  <neo4j_usage>
    <rule>Always create and close drivers/sessions with context managers.</rule>
    <rule>Do not mutate existing DB data implicitly; flows must not need manual repair.</rule>
    <rule>Ensure constraints/indexes exist before writes; fail fast if missing.</rule>
  </neo4j_usage>

  <embedding_property>
    <rule>Use canonical property via src/constants.py: EMBEDDING_PROPERTY = f("embedding_{EMBEDDING_TYPE}")</rule>
    <rule>All writers/readers must use the constant; never hardcode.</rule>
    <rule>Similarity must fail early if no methods have EMBEDDING_PROPERTY set.</rule>
  </embedding_property>

  <cve_handling>
    <rule>Link CVEs only when version constraints match dependency version.</rule>
    <rule>Only consider ExternalDependency nodes with version IS NOT NULL for AFFECTS.</rule>
    <rule>Ignore CVEs without version constraints (precise and fuzzy).</rule>
    <rule>Persist caches; resume partial searches; respect TTL.</rule>
    <rule>Never link to dependencies lacking a version; on version parse failure, skip.</rule>
  </cve_handling>

  <nvd_searches>
    <coverage>Cover 100% of detected external dependencies.</coverage>
    <limits with_api_key="50/30s" without_api_key="5/30s"/>
    <rule>Group terms; iterate all groups until fully processed.</rule>
    <rule>Backoff on 429 and honor Retry-After.</rule>
    <rule>Log: covered X/Y dependencies.</rule>
  </nvd_searches>

  <temporal_coupling>
    <rule>Use apoc.periodic.iterate; skip pathological commits; support time windows.</rule>
    <rule>Compute confidence and prune below threshold.</rule>
  </temporal_coupling>

  <testing>
    <rule>Use driver/session context managers; avoid deprecation warnings.</rule>
    <rule>Prefer live integration tests for critical paths; unit tests for small helpers.</rule>
  </testing>

  <planning>
    <self_reflection>
      <step>Define and refine an internal rubric (5–7 categories).</step>
      <step>Iterate until response meets top marks across categories.</step>
    </self_reflection>
    <ops>
      <rule>Apply self_reflection before complex implementation proposals.</rule>
      <rule>Keep rubric internal; communicate only resulting plan/edits.</rule>
      <rule>State trade-offs (time, reliability, scope) explicitly.</rule>
    </ops>
  </planning>

  <execution_eagerness_and_parallelism>
    <rule>Act decisively; do not ask for confirmation unless blocked. Document assumptions.</rule>
    <rule>Parallelize read-only discovery/tool calls.</rule>
    <rule>Set a tool budget; stop scanning when sufficient signal.</rule>
    <rule>Validate prerequisites early; fail fast on long-running steps.</rule>
    <rule>Be explicit about exhaustiveness vs. narrowness and when to check in.</rule>
    <rule>Persist progress/context; avoid repeating discovery when cached results exist.</rule>
  </execution_eagerness_and_parallelism>

  <systemic_fixes>
    <policy>All fixes must be systemic and flow through the DAG; no ad-hoc DB mutations or one-off scripts to amend graph state post hoc.</policy>
    <rule>Pipeline stages must produce correct outputs by themselves; do not rely on external repair scripts.</rule>
    <rule>Add fail-fast guards when critical derived data is missing (e.g., dependency versions with build files present).</rule>
    <rule>Documentation and tests must reflect DAG-first behavior; remove or quarantine repair utilities.</rule>
  </systemic_fixes>

  <dependency_resolution_policy>
    <rule>ExternalDependency nodes MUST be versioned. Accept either full GAV (group_id, artifact_id, version) or package+version when GAV is unknown.</rule>
    <rule>Fail fast when an external import cannot be resolved to a versioned ExternalDependency; unresolved imports abort the run.</rule>
    <rule>Do not create or rely on versionless dependency nodes. The legacy ExternalDependencyPackage label is removed.</rule>
    <rule>Link CVEs only to versioned ExternalDependency nodes (AFFECTS requires version); never link to package-only nodes.</rule>
    <rule>Resolver heuristics and mappings must be deterministic, provider-agnostic, and centralized in code (e.g., src/data/writers/imports.py); adding mappings is a systemic change and must be covered by tests.</rule>
    <rule>No run-specific environment flags to relax dependency rules; CI and local runs enforce the same fail-fast policy.</rule>
  </dependency_resolution_policy>

  <ci_zero_tolerance>
    <pre_commit>
      <command>pre-commit run --all-files</command>
      <rule>All checks must pass locally before commit; CI runs the same hooks.</rule>
    </pre_commit>
    <git_hook>
      <rule>Pre-commit hook runs automatically on git commit and blocks failures.</rule>
    </git_hook>
    <manual_method>
      <rule>Run pre-commit hooks before EVERY commit.</rule>
    </manual_method>
    <golden_rule>pre-commit run --all-files must show "Passed" for all checks.</golden_rule>
  </ci_zero_tolerance>

  <development_setup>
    <env>
      <rule>ALWAYS use the dedicated conda environment: neo4j-code-graph</rule>
      <step>conda activate neo4j-code-graph</step>
      <step>pip install -e .[dev]</step>
      <step>pip install -r config/requirements.txt</step>
      <step>cp .env.example .env and edit with Neo4j credentials</step>
      <note>All project commands and scripts must be run inside the 'neo4j-code-graph' conda environment. Activate it first: conda activate neo4j-code-graph.</note>
    </env>
    <quality_tools>
      <step>isort src/ tests/ scripts/</step>
      <step>black src/ tests/ scripts/</step>
      <step>isort --check-only --diff src/ tests/ scripts/</step>
      <step>black --check --diff src/ tests/ scripts/</step>
      <step>flake8 src/ tests/ --max-line-length=100</step>
      <step>mypy src/ --ignore-missing-imports</step>
      <step>make format-check; make lint</step>
      <step>make format</step>
      <step>pytest -v</step>
    </quality_tools>
    <import_sorting_critical>
      <rule>Use isort with black profile ordering.</rule>
    </import_sorting_critical>
  </development_setup>

  <architecture_overview>
    <entry file="code_to_graph.py" desc="Loads Java code structure with embeddings"/>
    <entry file="git_history_to_graph.py" desc="Imports Git history and developer data"/>
    <entry file="create_method_similarity.py" desc="Creates method similarity relationships using KNN"/>
    <entry file="cleanup_graph.py" desc="Flexible cleanup tool"/>
    <entry file="temporal_analysis.py" desc="Temporal analyses"/>
    <entry file="common.py" desc="Shared utilities"/>
    <entry file="utils.py" desc="Core utility functions"/>
  </architecture_overview>

  <provider_agnostic_policy>
    <rule>No vendor-specific integrations in pipeline logic.</rule>
    <rule>Works with any Git repository URL; no vendor API dependency.</rule>
    <rule>External vulnerability data must come from NVD only.</rule>
  </provider_agnostic_policy>

  <neo4j_aura_compatibility>
    <allowed>Standard Cypher, APOC core, standard GDS algorithms</allowed>
    <disallowed>APOC extended; custom plugins; unsupported features</disallowed>
    <design_rule>Provide Aura-compatible alternatives if needed.</design_rule>
  </neo4j_aura_compatibility>

  <testing_strategy>
    <alignment>
      <rule>Tests reflect the active DAG and code paths only.</rule>
      <rule>Avoid optional/future features in tests unless active.</rule>
      <rule>Prefer unit tests for helpers; live tests for Neo4j/GDS.</rule>
    </alignment>
    <use_of_test_doubles>
      <rule>Avoid mocks/monkeypatch; use real paths where feasible.</rule>
      <rule>If unavoidable, scope narrowly and assert real outputs/side effects.</rule>
    </use_of_test_doubles>
    <connection_config>
      <rule>Use get_neo4j_config(); CLI args override .env.</rule>
      <rule>No hardcoded localhost or database name; abort if unset.</rule>
      <rule>Never assume default passwords.</rule>
    </connection_config>
    <schema_enforcement>
      <rule>All writes run only after core constraints exist; fail fast.</rule>
    </schema_enforcement>
  </testing_strategy>

  <performance_considerations>
    <gpu>
      <rule>Prefer GPU (CUDA/MPS); process in batches; manage memory.</rule>
    </gpu>
    <transformers>
      <rule>Centralize batch sizes/settings in src/constants.py; CLS pooling.</rule>
    </transformers>
    <progress_visibility>
      <rule>Use tqdm for long-running loops; fallback to periodic logs.</rule>
    </progress_visibility>
    <git_history>
      <rule>Use efficient CREATE/UNWIND batching with progress logging.</rule>
    </git_history>
  </performance_considerations>

  <dependency_management>
    <gds_version>Match config/requirements.txt</gds_version>
    <pyarrow_compat>&gt;=17.0,&lt;21.0</pyarrow_compat>
  </dependency_management>

  <common_issues>
    <issue>Session timeouts: use --skip-file-changes</issue>
    <issue>Memory limits: consider cleanup or reduce max commits</issue>
    <issue>Import errors: verify environment and dependencies</issue>
    <issue>Connection failures: verify .env and credentials</issue>
    <issue>OpenMP conflicts on macOS: export KMP_DUPLICATE_LIB_OK=TRUE</issue>
    <issue>Branch not found: auto-detect main/master/HEAD</issue>
    <issue>Slow performance: ensure environment and GPU detection</issue>
    <issue>CI failures: always run pre-commit locally first</issue>
  </common_issues>

  <commit_checklist>
    <mandatory>Pre-commit hooks pass: pre-commit run --all-files</mandatory>
    <fixes>
      <step>make format</step>
      <step>re-run pre-commit</step>
    </fixes>
    <never_commit>If any hook fails, do not commit.</never_commit>
  </commit_checklist>

  <code_quality_guidelines>
    <avoid_overused_terms>
      <term>optimized</term>
      <term>enhanced</term>
      <term>improved</term>
      <term>better</term>
      <term>faster</term>
      <term>efficient</term>
    </avoid_overused_terms>
    <neo4j_connection_hygiene>
      <rule>Always use context managers for Driver and Session.</rule>
    </neo4j_connection_hygiene>
    <consistency_conventions>
      <logging>logging.getLogger(__name__) with INFO/DEBUG levels</logging>
      <progress>Use tqdm for batch loops</progress>
      <connections>with GraphDatabase.driver and with driver.session</connections>
      <schema>verify via src.data.schema_management.ensure_constraints_exist_or_fail</schema>
      <constants>keep tunables in src/constants.py</constants>
      <transformers>prefer GPU; batch; progress</transformers>
      <reuse>reuse helpers in src/utils</reuse>
    </consistency_conventions>
    <deprecation_policy>
      <rule>Never ship code emitting deprecation warnings; update to stable APIs.</rule>
    </deprecation_policy>
  </code_quality_guidelines>

  <automated_tools_summary>
    <safe_commit>./scripts/safe_commit.sh "Add new feature"</safe_commit>
    <git_hook>git commit -m "message" (pre-commit validates)</git_hook>
    <manual_checks>
      <command>pre-commit run --all-files</command>
      <note>CI runs the exact same hooks.</note>
    </manual_checks>
  </automated_tools_summary>
</agents_guidance>
