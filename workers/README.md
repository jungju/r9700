# Host controller

`host_controller.py` is the fixed host adapter for validated public UI releases. It consumes request JSON from an operator-configured exchange and writes one terminal receipt per request. It does not run Python from a candidate, accept candidate-provided commands, restore the operations database, or contact DNS, GPUs, or external accounts.

## Operator setup

Create a private controller configuration file (the default is `.local/host-controller.json`) and restrict write access to the host operator and controller service. Keep the configured exchange directory private to the host controller and the trusted ops receipt writer. Candidate runners must not be able to write requests, controller configuration, or receipts.

Example configuration:

```json
{
  "schemaVersion": 1,
  "projectRoot": "C:/service/r9700",
  "hostExchangeDirectory": "C:/service/r9700/.local/host-exchange",
  "commandTimeoutSeconds": 120,
  "deployArgv": ["C:/service/bin/activate-release.exe", "--path", "{releasePath}", "--id", "{releaseId}"],
  "rollbackArgv": ["C:/service/bin/activate-release.exe", "--id", "{previousRelease}"],
  "verifyArgv": {
    "http": ["C:/service/bin/verify-http.exe", "--expected", "{expectedReleaseId}"],
    "search": ["C:/service/bin/verify-search.exe"],
    "prices": ["C:/service/bin/verify-prices.exe"],
    "mobile": ["C:/service/bin/verify-mobile.exe"]
  }
}
```

Every command is an argv array with an existing absolute executable path, launched with `shell=False`. Only the fixed placeholders `{id}`, `{releasePath}`, `{manifestHash}`, `{releaseId}`, `{previousRelease}`, and `{expectedReleaseId}` can be interpolated. The HTTP verifier must exit successfully and print JSON containing the active `releaseId`; the other three verifiers must exit zero. Every verifier must target the local candidate deployment. The controller passes a small OS-runtime environment allowlist rather than inheriting the ops worker's full environment.

The local web health endpoint may report `R9700_CODE_RELEASE` as its active `releaseId` while preserving the separate data release id. The trusted activation command must set this environment value to the activated code release id and restart the web process before the controller's HTTP verifier can confirm that deployment. When unset, the health endpoint keeps its existing data release id behavior.

Run one poll from the project root:

```powershell
python -m workers.host_controller --root . --exchange .local/host-exchange
```

An operator may schedule this fixed command with a local service manager. The exchange name must match the controller config and the `hostExchangeDirectory` configured for ops. Unset or invalid deploy, rollback, or verification configuration yields a `BLOCKED_CONFIG` receipt. No command means no deployment.

## Request and receipt

The controller accepts only `{id, releasePath, manifestHash, previousRelease, requiredChecks, rollbackDatabase}` with the fixed checks `http`, `search`, `prices`, and `mobile`, and `rollbackDatabase:false`. It confines the release to one directory directly under `.local/code-releases`, verifies `digest(validation-receipt.json)` with `ops.common.digest`, requires the fixed passing sandbox check list, checks every approved file hash, compares the complete release tree against the current project, and rejects protected or unapproved changes. `ops/`, tests, the operations database, and `.local` state are never deployed from a request.

Receipts live in `receipts/<id>.json` and contain the request id, manifest hash, `DEPLOYED`, `ROLLED_BACK`, `FAILED`, or `BLOCKED_CONFIG`, per-check `PASS`/`FAIL`, the confirmed active release id when known, and the previous release id. A successful deploy requires all four checks to pass and the health endpoint to report the candidate release id. A regression invokes only the configured rollback argv, then confirms the previous release id through the trusted HTTP check. Database state is never restored.

Atomic receipts, a process liveness lock, and a per-request intent journal prevent concurrent or duplicate activation. Existing receipts are terminal. If a controller dies after recording intent but before a receipt, the next poll records a terminal failure and does not replay a deploy or rollback command; an operator must reconcile the actual release state before any new request. `BLOCKED_CONFIG` is also terminal for that request, so fix configuration and submit a new request id.

This is a host-side adapter around operator-configured deployment and health-check commands. It narrows the command surface and validates immutable evidence; it does not claim blanket process isolation or make arbitrary host commands safe. Configure only fixed commands that serve the release path and leave `.local/operations.sqlite3` unchanged. Tests use temporary project trees, fake trusted commands, and a loopback health server; they never deploy, change DNS, run GPU work, or touch production files.
