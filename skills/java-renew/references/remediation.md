# Default EOL and vulnerability remediation

Use this policy during dependency selection and every execution/validation phase.
Defaults replace EOL components and fix known vulnerabilities at all severities,
including missing or conflicting severity ratings. Advisory identifiers include
CVE, GHSA and ecosystem-specific IDs; deduplicate aliases without dropping the
affected component/version occurrences.

## Select and implement fixes

1. Inventory effective runtime/test graphs, build launchers/plugins and their
   transitives, annotation processors, embedded/shaded code, agents, the selected
   JDK, and project-owned deployment/container inputs. Follow the existing file
   scope into resolved artifacts; a lexical exclusion is not a security exemption.
   Do not update unrelated host software or skill-development tools merely because
   they are installed. Record absent component categories explicitly.
2. Establish current lifecycle status from the exact vendor/project release line.
   Maintenance-only does not automatically mean EOL. Record support dates and
   applicable distributions; commercial backports need verified entitlement and
   advisory evidence. Unknown support remains incomplete, never assumed supported.
3. Compare resolved versions against current advisory data. Prefer the least
   disruptive supported secure combination, starting with compatible patches.
   Fix the owning BOM/platform/plugin/distribution before forcing a transitive
   version; inspect shaded/embedded copies and actual execution classpaths.
4. Necessary major upgrades and API/test/packaging changes are in scope by default
   during execute. Preserve the requested Java/runtime and consumer release,
   explicit pins, framework preservation and repository constraints. If these
   prevent remediation, report the conflict and concrete alternatives. Do not
   switch Java targets, weaken security, delete test assertions or perform
   destructive production/data changes to obtain a passing result.
   `allow_major_upgrades: false` prevents automatic major changes; `preserve`
   prevents changing the framework line. Report the resulting conflict rather
   than treating either constraint as a security waiver.
   Versions selected by the agent or written into a generated target file are
   implementation decisions, not new user constraints; revise them when rescans
   require it. Never manufacture pins to avoid fixing a finding.
5. After each coherent change, run focused checks. Validate the final clean build,
   original tests, behavior/API contracts and affected packaging/startup. Resolve
   graphs and rescan final artifacts/images; a build pass or version edit alone
   does not close a finding. Preserve pre-change scan results and failed attempts.
6. Stop when all applicable findings are fixed or each remaining issue has a
   concrete blocker (no supported fix, incompatible pin/major, unavailable evidence
   or environment). Do not repeat unchanged scans or speculative upgrades. Give
   the affected version, owning component, attempted route and next action.

## Evidence and acceptance

The `evidence-template` includes `remediation.reviews` and `remediation.findings`.
Keep full scanner/advisory/lifecycle records in linked artifacts rather than
copying them into every handoff.

- Reviews `support` and `vulnerabilities` each record `status` (`not_run`,
  `incomplete`, `complete`), `checked_on` (UTC date), summary, artifact hashes and
  coverage of `runtime`, `test`, `build`, `processors`, `agents`, `containers`.
  Coverage maps each category to `complete`, `incomplete` or `not_applicable`;
  justify gaps/absence in the summary and linked component matrix.
  Build covers the launcher/JDK/plugins and transitives; runtime covers application
  dependencies, JDK and server. An absent image/category requires evidence of its
  absence; missing deployment inputs cannot be marked not applicable by assumption.
- `checked_on` means current sources were checked. For online advisory queries use
  the query date; for an offline database use its snapshot date, not today's report
  date. Defaults allow at most one UTC calendar day of age; override
  `max_review_age_days` for organization policy. Future dates are invalid.
- Each finding records `id`, `kind` (`eol`, `vulnerability`), `component`, affected
  `version`, `status` (`open`, `fixed`, `not_affected`), `replacement`, summary and
  artifact hashes. `replacement` identifies the actual fixed component/version
  or removal; it may be empty for open/not-affected findings. A fixed finding needs
  post-change resolved/version/test/rescan evidence. Retain unresolved occurrences
  rather than deleting them from a report.
- `not_affected` needs applicable vendor/advisory or organization-approved
  applicability evidence. Test scope, an unexecuted plugin, a low score or a
  speculative reachability claim alone does not dismiss an advisory. Preserve
  raw findings and explain alias/distribution/backport/range differences.
- Unknown/stale support or incomplete advisory coverage blocks acceptance.
  EOL findings block `dependencies`; vulnerability findings block `security`.
  The helper rejects declared passes with missing/incomplete reviews or open
  findings. It checks the ledger and hashes, not the truth or completeness of a
  scanner/vendor assertion; trusted CI and semantic review remain necessary.
- `report` overrides change automatic implementation behavior, not acceptance.
  A gate can be waived only through an explicit owned/expiring policy waiver and
  a matching `waived` check. Findings remain visible; waived is not fixed.

In each phase summarize findings found/fixed/remaining, affected scopes, concrete
blocked fixes and next actions. Assessment and planning do not edit product files.
