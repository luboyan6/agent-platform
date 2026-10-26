# Observed DOM and evidence

These are observations from particular sessions, not stable locator guarantees. Re-inspect the current page before acting. Configuration controls have been observed in specific page variants; selecting, saving, complete saved-value readback and current price extraction have not passed managed-provider acceptance.

Repository evidence sources (paths are relative to the project root):

- `.trellis/tasks/10-23-cnc-part-config-auto-quote/research/site-skill-live-observations-2026-10-23.md`, **Xometry current configuration observation**: this continuation's historical test-route controls and material popup, without selection/save.
- `.trellis/tasks/10-23-cnc-part-config-auto-quote/research/provider-live-evidence-2026-10-23.md`, **Current public Xometry demo DOM**, **Current official no-order semantics**, and **Current real entry DOM**: earlier same-date research for public uploader, open shadow roots, sample controls and the official guide re-read. These were read from the repository for this skill update; they were not repeated live by the skill implementer.
- `.trellis/tasks/10-23-cnc-part-config-auto-quote/research/xometry-upload-evidence.json`: prior frozen-buffer upload and unresolved durable intent, detailed below.
- `.trellis/tasks/10-23-cnc-part-config-auto-quote/research/xometry-live-quote-reconciliation-2026-10-23.md`: read-only historical quote comparison and the quantity-5 versus target-quantity-1 mismatch; no exact-byte reconciliation or new quote.

## Evidence levels and page variants

| Scope | What it establishes | What it does not establish |
| --- | --- | --- |
| Prior managed upload below | One exact frozen-buffer upload action and a subsequent declaration screen | Confirmed remote receipt, resolved uncertain intent or a completed quote |
| Historical quote route, observed 2026-10-23 around 23:50–23:55 Asia/Shanghai | Configuration DOM candidates and an opened material search popup on quote `Q59-6980-1120` with `?initialTab=Configure&vercel_part_config=test` | Normal-route applicability, managed-account control behavior, option selection/save/recalculation or exact target quote |
| Public `/testdrive/` research on 2026-10-23 | Public sample controls and uploader declaration, in open shadow DOM | Real uploaded-file identity, authenticated React control bindings or usable business prices |
| Completed skill documentation | Reusable evidence-based procedure | Enabled backend adapter, live workflow acceptance or a verified quote |

## Prior controlled upload

Source: `.trellis/tasks/10-23-cnc-part-config-auto-quote/research/xometry-upload-evidence.json`, run `e8dea2c1-3430-4279-832e-1e655ced79b8`.

| Observed state | Grounded DOM evidence |
| --- | --- |
| Authenticated dashboard | `#dashboard-get-instant-quote-primary`, text “Get an Instant Quote” |
| File selection | Exactly one `input[type="file"]`; empty `accept`, `multiple=true`. Upload only the one authorized payload; empty `accept` is not a validation policy. |
| One actual upload | Playwright `upload_step` set the exact frozen STEP payload once; staged alias was `part.step`. That alias alone does not prove source-file identity. |
| Parsing | `Classifying…` / `0 parts ready · 1 uploading`, then `1 part ready` |
| Export declaration | `[data-testid="ItarView-itar-option-confirmed-not-itar"]`, `[data-testid="ItarView-itar-option-confirmed-itar"]`, `[data-testid="ItarView-itar-continue"]` |

The declaration covered ITAR, EAR, Dual-Use, Military/Defense, Firearms and CUI; its “No” option also mentioned EAR99. These are recorded UI statements, not a classification decision. Inspect the full current wording and obtain an exact-file/scope user decision before selecting or continuing. The prior operator stopped before either selection or Continue.

That run's durable upload intent remains **uncertain** (`RESEARCH_UPLOAD_UNCONFIRMED_NO_RETRY` in the task inventory). Preserve it even though the research run was cancelled. Do not delete/reset it, rerun the research upload script or upload again under a new run. Resume only after authoritative receipt/remote-state reconciliation binds the frozen payload to that staged part. If identity cannot be established, stop and surface the unresolved operation; history or a filename match cannot settle it.

## Read-only handoff observation on 2026-10-23

The dispatching session reported that the CDP tab displayed quote `Q59-6980-1120`, a history record dated **2026-10-22**, status **Auto-Quoted**:

| Field | Observed text/value |
| --- | --- |
| Linked source filename | `D14-TO-CS-ADAPTER_LP0335_P2002B.STEP` |
| Process | CNC Machining |
| Material | Aluminum 6061-T6x |
| Finish | Standard |
| Quantity | **5** |
| Subtotal | **$243.70** (raw symbol; no ISO currency inferred) |
| Lead time in history | 8 business days |

The target configuration quantity is **1**. This quantity-5 history record is not the current exact-configuration quote; do not copy its amount, scale its price to quantity 1 or substitute a different historical quote. No new browser mutation or successful target quote was performed for this handoff. Re-read the target configuration and file hash before any future operation; these facts are context, not defaults for later requests.

## Historical quote configuration DOM observed on 2026-10-23

The dispatching session inspected the authorized historical quote's configuration route at approximately 23:50–23:55 Asia/Shanghai. Its query included `initialTab=Configure&vercel_part_config=test`; these observations must stay scoped to that variant. The session opened only the material popup, inspected it and pressed Escape. No option was selected, no configuration was saved, no CAD was updated and no recalculation was requested. Material stayed `Aluminum 6061-T6x (Best Available)` and quantity stayed 5.

| Purpose | Observed element / candidate ID | Accessible label or value |
| --- | --- | --- |
| Process | `DIV[role=button]#option-select-process` | `Process: CNC` |
| Preferred subprocess | `#option-select-cnc-subprocess-select` | `No Preference` |
| Material | `DIV[role=button]#material-select-material-select` | `Material: Aluminum 6061-T6x (Best Available)` |
| Material search, after opening the popup | `input[role=combobox]#search-material-select` | `Search materials` |
| Finish | `DIV[role=button]#finish-select-finish-multiselect` | `Finish: Standard` |
| Quantity | Unique visible input with `role=spinbutton` | `Quantity`, value `5` |
| Save | `BUTTON#configure-part-header-save-and-view-quote` | `Save Configuration` |
| Tolerance | `#option-select-tolerances-radio-metal` | `±.005″ (±0.13mm)` |
| Surface roughness | `#option-select-surface-roughness-select` | `125uin/3.2um Ra` |
| Existing CAD replacement | `#configure-part-left-rail-update-cad` | Update CAD; **not** the primary new-part uploader |

Supporting-files upload is separate from primary CAD upload and CAD replacement. Locate the intended operation in the current page; do not interchange these controls because each accepts files.

The opened material popup exposed listbox/options whose generated IDs began `_r_3n_`; never persist or hardcode that prefix or its suffixes. Each option combines its material title with description, price indicators such as `$$$$$` and sometimes `Popular`. Match the exact option-title field after inspecting the current option structure, not the concatenated `innerText`. Observed distinct titles included:

- `Aluminum 6061-T6x (Best Available)`
- `Aluminum 6061-T651, Plate`
- `Aluminum 6061-T6/T6511, Bar/Rod`

These are different choices. A request for `AL6061` or a different temper/product form cannot be silently resolved to the first or popular result. Re-open and inspect current options after any dependency change; never treat this short observed list as a complete material catalog. Finish option contents and saved effective-value parsing were not inspected in this observation.

## Public entry and test-drive evidence

Current public real entry `https://www.xometry.com/quoting/home/` displayed **Upload 3D Files** and exactly one native file input with no ID/name and accept including `.step,.stp`. The earlier authenticated dashboard's **Get an Instant Quote** button and this public uploader are different entry observations. Reconcile authentication and page variant before choosing either.

The public test drive displayed `Max Size of 150MB per file` beside primary CAD formats. This is a UI declaration; the byte convention and upload boundary were not tested. A 150,000,000-byte cap would be a conservative engineering choice, not a verified provider boundary. A supporting-files size label alone cannot establish a primary CAD limit.

The test drive uses `HTML-LOFT` and nested open shadow roots. Official Playwright Locators pierce open shadow roots; plain `document.querySelectorAll` misses many controls. Sample candidate IDs include `quantity-input`, `process-combobox`, `cnc-subprocess-select-combobox`, `FilterableSelectSub1-combobox`, `finish-multiselect-combobox` and `surface-roughness-select-combobox`. Do not substitute these for authenticated quote controls. Sample defaults, prices, offer locations and generated `css-*` classes are not target-quote evidence or stable price selectors.

The official [How to Use the Xometry Instant Quoting Engine](https://www.xometry.com/how-xometry-works/) was re-read on 2026-10-23: editing material/finish/quantity and **Save Configuration** precede separate checkout/**Place Order** steps. This supports the quote-only workflow shape. It does not establish the current button implementation, save receipt, currency or same-run freshness. Inspect current semantics and remain before purchase actions.

## Remaining acceptance evidence

Before enabling an adapter or reporting a target quote, verify the normal managed quote route, exact-file upload reconciliation, complete parameter mappings/dependencies, save receipt plus saved-value readback, positive linked geometry, same-run recalculation, amount/currency/price scope and lead time. A historical **Auto-Quoted** label or current DOM snapshot alone passes none of those missing gates. Price-extraction selectors are still unverified.

## Tool use and fresh observations

- **Playwright MCP:** use `browser_snapshot`/`browser_find` for fresh accessible controls, then actions using that snapshot's references. Use `browser_file_upload` for a verified file chooser; an official file-input helper must send the same frozen payload. Do not navigate an unrelated fresh browser into the flow or assume it shares the authorized account.
- **Official Chrome DevTools MCP:** use `list_pages` to identify the authorized current `pageId`, then `take_snapshot` for fresh control `uid` values. Use `click`/`fill` against those current controls and `upload_file` only for the confirmed file input, supplying a protected immutable local copy whose bytes, size and SHA-256 match the frozen authorized payload. Recheck the protected copy before use; do not pass a mutable source path. Take a fresh snapshot after each transition and never reuse stale `uid` values. If the default profile is occupied, reuse an available owned isolated session or stop; never kill an unrelated browser. Local daemon paths/session IDs are environment details, not reusable defaults.
- **CDP bridge:** identify the authorized tab, call `browser_observe`, and pass its current `tab_id`, `page_revision` and control reference to `browser_act`. References are single-use and expire; observe again after every action or stale response. Use the official CDP file-input mechanism only after current DOM confirms the intended input and its uniqueness; no arbitrary upload endpoint or signed-URL replay.
- For start/upload/classification/declaration/configuration/save/result transitions, retain a sanitized before/after observation with event order, current control labels/values, masked identity match and receipt identifiers. Use short bounded read-only waits while parsing/recalculating. Record fresh state even when the page changes asynchronously; never repeat a mutation because a response is late.
- Capture relevant visible text and values without raw auth responses, storage/cookie dumps, sensitive inputs, signed URL attributes or credential-bearing network logs. Leave unrelated tabs and user work intact. These browser observations do not validate the backend adapter or permit changes to production registration.
