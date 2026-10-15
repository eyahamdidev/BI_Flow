# Branching and PRs

- `main` is protected: PR required, CI green, one review (CODEOWNERS enforces who).
- Branch per owner and topic: `bo1/langgraph-runner`, `bo3/knn-imputer`, `bo6/driver-decomposition` ...
- Conventional commits: `feat(bo3): add knn imputer`, `fix(bo1): resume skips ok stages`, `docs: ...`.
- Rebase on `main` before opening the PR. Small PRs. Touch only your own folders; changes elsewhere need that owner's review.
- Contract changes: open an issue first, then one PR that changes `contracts/`, runs `make schemas`, bumps `CONTRACT_VERSION` and updates every affected mock.
- Day-1 setup of the repo (admin): enable branch protection on `main`, require the `ci` checks and CODEOWNERS review.
