# AWS Integration — NOT IMPLEMENTED

> **No AWS resource exists.** No AWS account is used by this project. No
> instance, bucket, table, function or dashboard has been created. Nothing has
> been benchmarked on AWS hardware. The $150 compute grant was **not awarded**.
> SightOps runs entirely on the existing Azure VM, on CPU, and does not require
> AWS in any way.

Everything below this line is a **plan**. It describes what integration would
look like if it were authorised and funded. It is written down because the
provider interfaces were designed for it from the start, and because a credible
path is more useful than a vague promise.

---

## 1. Why the code is already shaped for it

Four interfaces exist with exactly one implementation each today. None of them
leaks its implementation into a caller, which is what makes the adapters below
additions rather than a rewrite.

| Interface | File | Today's implementation |
|---|---|---|
| `EvidenceStorage` | `app/storage/evidence.py` | `LocalEvidenceStorage` (filesystem) |
| `Repository` | `app/storage/repo.py` | SQLite via `aiosqlite` |
| `ModelProvider` | `app/providers/base.py` | `NebiusProvider` |
| `VoiceProvider` | `app/providers/base.py` | `ElevenLabsVoiceProvider` |

The API routes, the agent loop and the vision engine import the interfaces or
the models, never a vendor SDK. `app/api/deps.py` is the single place that
constructs concrete implementations, so substituting one is a change to that
factory and nothing else.

Two design choices that were made for this reason and are already in the code:

- **Metadata is separate from blobs.** The `images` table stores a `stored_path`
  key; the bytes live behind `EvidenceStorage`. An object store needs no schema
  change.
- **Keys are opaque and root-relative.** `put()` returns
  `<inspection_id>/<image_id><suffix>` and `LocalEvidenceStorage._resolve()`
  rejects anything that escapes the root. An S3 adapter can keep the same key
  scheme as an object prefix.

---

## 2. Planned adapters

### 2.1 `S3EvidenceStorage` — object storage for evidence

Replaces `LocalEvidenceStorage`. Implemented against the same three-method
interface (`put`, `get`, `exists`).

```
put(inspection_id, image_id, suffix, data) -> key
    key = f"{evidence_prefix}/{inspection_id}/{image_id}{suffix}"
    s3.put_object(Bucket=..., Key=key, Body=data, ContentType=...,
                  ServerSideEncryption="aws:kms", SSEKMSKeyId=...)
    return key
```

Considerations that are already visible in the current code and would carry
over:

- `put` is synchronous in the interface while `boto3` is blocking. The adapter
  would need `aioboto3` or an executor, or the interface would become `async` —
  a breaking change to three call sites (`inspections.py`, `demo.py`, `loop.py`),
  which is the honest cost.
- Annotated derivatives are written back with `set_annotated_path`. Under S3 they
  should be a separate prefix so a lifecycle rule can expire derivatives without
  touching originals.
- `retrieve` currently raises `FileNotFoundError`, mapped to HTTP 410. S3
  `NoSuchKey` would map to the same response.

### 2.2 `DynamoDBInspectionRepository` — inspection state

Replaces `Repository`. The access patterns are already known because every
method in `repo.py` is one of them.

| Access pattern | Table / index |
|---|---|
| Get inspection by id | `inspections` (PK `id`) |
| List inspections newest-first | GSI on `created_at` |
| Images for an inspection, ordered | `images` (PK `inspection_id`, SK `sequence`) |
| Observations for an inspection, ordered | `observations` (PK `inspection_id`, SK `sequence`) |
| Timeline for an inspection, ordered | `timeline` (PK `inspection_id`, SK auto-increment id) |
| Tool calls for an inspection, ordered | `tool_calls` (PK `inspection_id`, SK `id`) |
| Incident by id | `incidents` (PK `id`) |
| Incidents newest-first | GSI on `created_at` |

The one real difficulty is **`next_sequence()`**. Today it is
`SELECT COALESCE(MAX(sequence), 0) + 1`, which is safe because SQLite serialises
writers. DynamoDB has no equivalent, and two concurrent uploads to the same
inspection would collide. The options are a conditional `UpdateItem` on a counter
attribute of the inspection item, or accepting collisions and sorting on
`created_at` instead. A conditional write is the correct choice and is the first
thing that would have to change.

The second is the **embedded `AnalysisResult`**. It is stored as a serialised
JSON document and can exceed DynamoDB's 400 KB item limit for a large panel with
many regions. It would either become its own item per observation, or move to S3
alongside the evidence with the key stored in the item.

### 2.3 `BedrockProvider` — an alternative reasoning backend

Implements `ModelProvider` alongside `NebiusProvider`, using the Bedrock
Converse API. The interface is deliberately narrow — `generate(messages, tools)`
returning a `ModelResponse` with `ToolCall`s and `Usage`, plus `describe_image`
for multimodal interpretation — so the adapter is a translation layer, not a
redesign.

What must be preserved, because the agent depends on it:

- Tool schemas must be passed through in the provider's own format; the agent
  hands `tool_schemas()` from `app/agent/tools.py`.
- A tool call must come back with a name and a parsed argument dict.
  `NebiusProvider` already handles the string-vs-object argument difference; any
  new provider must too.
- Models that cannot call tools must be rejected rather than silently degraded,
  because the agent has no other way to act.
- Timeouts and retries must stay in the provider, not the loop. The loop treats
  a `ProviderError` as a degraded step and falls back to the deterministic
  policy; a provider that blocks forever would defeat the loop's own
  `agent_step_timeout_seconds`.

### 2.4 `LambdaInspectionHandler` — event-driven actions

Not designed in detail, and deliberately so: the current system is
request-driven, and there is no event that needs to trigger work after a
response completes. The plausible shape is a Lambda invoked by an S3
`ObjectCreated` event to pre-compute a thumbnail and a blur score for a new
evidence object, or a scheduled Lambda that expires evidence past a retention
window. Neither is needed to run SightOps.

---

## 3. Planned compute: Graviton and COOL

The single VM process would become an EC2 instance on Graviton (arm64) running
the same FastAPI application, with the Cloud-Optimized OpenCV Library in place of
the stock `opencv-python` wheel.

What that requires that does not exist today:

- A **multi-architecture container image**. The current `python:3.12-slim`
  base is amd64-only in the local build. A Graviton deployment needs an arm64
  image, which means either a buildx cross-build or a native arm64 builder.
- A **COOL-optimised OpenCV build**. `opencv-python==5.0.0.93` is a PyPI wheel
  built for x86_64 with generic flags; COOL is a different distribution with
  different build flags. `app/vision/engine.py::version_report()` reports
  `cv2.__version__`, so the deployed major and minor version would still be
  verifiable — but the *build* would differ, which is exactly why
  `docs/benchmarks/cool-methodology.md` requires build flags to be recorded.
- No code change. That is the point of the abstraction: the vision engine calls
  `cv2` operations, and nothing in it branches on architecture.

### Cost and eligibility

Facts, not estimates: no instance type has been chosen, no price has been
looked up, and no run has happened. Any cost figure in this repository would be
invented. Competition eligibility is likewise subject to the organisers'
requirements, which are outside the control of this codebase. See
`docs/competition/submission.md` for the position stated to the judges.

---

## 4. Planned observability: CloudWatch

Today, observability is structured logs to stdout plus the persisted timeline and
tool-call tables. The request-ID middleware in `app/main.py` already emits
`method path -> status (ms) request_id=`, and `X-Request-ID` is returned to the
browser, so a user can quote an id.

CloudWatch would receive:

- **Logs** — the existing lines, unchanged, shipped by the CloudWatch agent or
  the ECS log driver.
- **Metrics** — the numeric quantities the evaluation already measures:
  vision analysis latency, `duration_ms` per tool call from `tool_calls`, upload
  rejections, provider failures by type, and the reinspection rate.
- **Traces** — the agent's step sequence is already an explicit trace in the
  timeline table; an X-Ray segment per analysis and per provider call would make
  it externally visible.

None of this is required to run SightOps, and none of it would replace the local
timeline, which is the artefact a human actually reads.

---

## 5. What would concretely have to change

The unglamorous list, in dependency order:

1. **Make `EvidenceStorage` async.** `put`/`get` are synchronous and called from
   async handlers. S3 has no synchronous client worth using in a request path.
   Three call sites plus the interface.
2. **Give `next_sequence()` a conditional-write implementation** before any
   DynamoDB adapter is attempted, or concurrent uploads will produce duplicate
   sequence numbers and unordered observations.
3. **Bound the serialised `AnalysisResult`.** Decide whether it becomes its own
   item or moves to object storage, and enforce the bound.
4. **Replace the in-process upload guard with a streaming path.** Today the
   whole body is read into memory and checked against `max_upload_bytes`
   (12 MiB). That is fine for one VM serving a handful of uploads; it is not fine
   for concurrent large uploads. The check would move to a content-length limit
   plus a streaming decode with an abort, and the 40 M pixel cap would stay as
   the second line of defence against decompression bombs.
5. **IAM and KMS.** An instance role scoped to one bucket prefix and two tables;
   SSE-KMS with a customer-managed key for evidence at rest, since the evidence
   is photographs of customers' homes and equipment.
6. **A per-request cost model.** Provider tokens, S3 PUT/GET, DynamoDB WCU/RCU
   and Lambda invocations per inspection. Without it there is no way to know
   whether the architecture is sensible, and it cannot be produced without
   measurements.
7. **A way to run the evaluation against the deployed stack.** The harness in
   `backend/scripts/evaluate.py` measures latency, throughput, CPU and memory
   locally. Pointing it at a remote deployment is a different problem, and any
   claimed AWS performance figure has to come from it rather than from an
   expectation.

---

## 6. Summary

| Component | Status |
|---|---|
| AWS account | None. Not created, not required. |
| AWS resources provisioned | **None.** |
| AWS integration in code | **None.** No `boto3`, no AWS SDK, no AWS-specific branch anywhere in `backend/`. |
| COOL | Not installed, not measured. |
| Graviton | Not used, not benchmarked. |
| Provider interfaces | Present and in use by the local implementations, and shaped so the adapters above are additions. |
| SightOps running without AWS | Complete. Verified. |
