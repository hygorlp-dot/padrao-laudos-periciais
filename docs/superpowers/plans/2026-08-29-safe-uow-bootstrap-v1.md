# SAFE_UOW_BOOTSTRAP_V1 implementation plan

Issue: #140 (C1B)
Base: `1f3f5dc479433dde0ce75600c7f16f84816e2637`

## Scope

Add one first-party command that fetches an explicitly named remote branch,
resolves its exact commit/tree, creates a new isolated worktree without
touching existing worktrees, verifies postconditions, and emits a canonical
ephemeral UOW manifest under the repository common Git directory.

## Causal DAG

1. Define the closed manifest schema and deterministic serializer.
2. RED path, Git-state, collision, hook/filter and concurrency adversarials.
3. Implement read-only preflight and an exclusive repository-scoped lock.
4. Create the worktree with hooks disabled; verify exact HEAD, tree, branch,
   cleanliness and upstream before emitting the manifest.
5. Run focused/change-impact tests, shadow review, terminal assurance and
   independent reviews on one frozen HEAD.

## Non-goals

- No reset, clean, prune, deletion, force operation or existing-worktree edit.
- No implicit remote, branch, destination, Issue or policy authority.
- No submodule initialization, external filter, hook, private path or egress
  beyond the explicit Git fetch.
- The manifest is evidence only and never replaces GitHub or repository policy.
