/**
 * @file 治理准入、离线证明与漂移检测的单元测试。
 *
 * 分层说明（不得混为一谈）：
 *   - 本文件全部为**本地合成快照**测试，不代表真实远端验证；
 *   - 真实 API 采集与远程 CI 执行属于另外的验收层，不在此文件断言。
 */
const { test } = require('node:test');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const lib = require('../scripts/ci/governance_attestation.cjs');
const captureTool = require('../scripts/ci/capture_governance_attestation.cjs');
const drift = require('../scripts/ci/check_governance_drift.cjs');
const { evaluatePolicy, readSnapshot, readAttestation, TRUSTED_REPOSITORY, TRUSTED_REPOSITORY_ID } =
  require('../scripts/ci/cad_ci_guard.cjs');

const NOW = new Date('2026-10-27T06:00:00.000Z');
const UPDATED_AT = '2026-10-22T10:42:30.335Z';
const CREATED_AT = '2026-10-22T10:39:08.016Z';
const DAY_MS = 24 * 60 * 60 * 1000;
const RULESET_ID = 25631760;
const REPO = { id: TRUSTED_REPOSITORY_ID, full_name: TRUSTED_REPOSITORY };
const TMP_ROOT = fs.mkdtempSync(path.join(os.tmpdir(), 'cad-gov-test-'));

// ---------------------------------------------------------------- 夹具

/** @brief 每个测试文件用一次性密钥，避免测试依赖仓库内生产公钥。 */
function newKey() {
  const { publicKey, privateKey } = crypto.generateKeyPairSync('ed25519');
  return {
    publicPem: publicKey.export({ type: 'spki', format: 'pem' }).trim(),
    privatePem: privateKey.export({ type: 'pkcs8', format: 'pem' }),
  };
}

const KEY = newKey();
const KEY_ID = lib.keyIdOf(KEY.publicPem);

/** @brief 构造信任根；overrides 允许注入条目字段与日志内容。 */
function trustRoot(overrides = {}) {
  return {
    keys: { [KEY_ID]: { pem: KEY.publicPem, not_before: '2026-01-01T00:00:00Z', revoked_at: null, ...overrides.entry } },
    log: overrides.log || [KEY_ID],
  };
}
const TRUST_ROOT = trustRoot();
const ANCHOR = lib.trustRootAnchor(TRUST_ROOT);

/** @brief 线上快照；默认**不含** bypass_actors，模拟只读凭据的真实可见性。 */
function liveRuleset() {
  return {
    id: RULESET_ID, name: 'protect-main', target: 'branch', enforcement: 'active',
    conditions: { ref_name: { include: ['refs/heads/main'], exclude: [] } },
    updated_at: UPDATED_AT, created_at: CREATED_AT,
    rules: [
      { type: 'deletion' },
      { type: 'non_fast_forward' },
      { type: 'pull_request', parameters: { required_approving_review_count: 0, require_code_owner_review: false, required_reviewers: [] } },
      { type: 'required_status_checks', parameters: { strict_required_status_checks_policy: false,
        required_status_checks: [{ context: 'test-and-build', integration_id: 15368 }] } },
    ],
  };
}

/** @brief 构造并签名一份证明；默认合规、bypass 为空。 */
function attestationFor(live = liveRuleset(), options = {}) {
  const refName = live.conditions?.ref_name || { include: [], exclude: [] };
  const ruleset = {
    id: live.id, name: live.name, target: live.target, enforcement: live.enforcement,
    ref_name_include: [...(options.refInclude ?? refName.include ?? [])],
    ref_name_exclude: [...(options.refExclude ?? refName.exclude ?? [])],
    updated_at: options.updatedAt ?? live.updated_at, created_at: live.created_at,
    rules: structuredClone(live.rules),
    bypass_actors: options.bypass === undefined ? [] : options.bypass,
  };
  const compliance = lib.evaluateCompliance(ruleset);
  const unsigned = {
    schema: lib.SCHEMA,
    repository: options.repository || { id: REPO.id, full_name: REPO.full_name },
    ruleset,
    policy_digest_sha256: options.policyDigest ?? lib.policyDigest(ruleset),
    snapshot_digest_sha256: options.snapshotDigest ?? lib.snapshotDigest(ruleset),
    compliant: options.compliant ?? compliance.compliant,
    noncompliance_reasons: options.noncomplianceReasons ?? compliance.reasons,
    governance: {
      mode: 'single_maintainer', independent_audit: false, bypass_requirement: 'empty',
      trust_boundary: '证明由维护者自行签发，信任根在仓库内，不构成独立审计。',
      ...options.governance,
    },
    captured_at: options.capturedAt ?? NOW.toISOString(),
    expires_at: options.expiresAt ?? new Date(NOW.getTime() + 10 * DAY_MS).toISOString(),
    generator: { tool: 'test', node: process.version },
    signer: { key_id: options.keyId ?? KEY_ID, key_type: 'ed25519', signed_at: options.signedAt ?? NOW.toISOString() },
    ...(options.extra || {}),
  };
  return { ...unsigned, signature: lib.signAttestation(unsigned, options.privatePem ?? KEY.privatePem) };
}

/** @brief 修改内容后重新签名，把故障隔离到语义检查而非签名本身。 */
function resign(attestation, key = KEY) {
  const { signature, ...unsigned } = attestation;
  return { ...unsigned, signature: lib.signAttestation(unsigned, key.privatePem) };
}

/** @brief 完整快照；所有检查默认满足，便于单点注入。 */
function valid(options = {}) {
  const live = options.live || liveRuleset();
  const sha = 'a'.repeat(40);
  return {
    context: {
      repository: TRUSTED_REPOSITORY, repository_id: TRUSTED_REPOSITORY_ID, event_name: 'workflow_dispatch',
      ref: 'refs/heads/main', ref_type: 'branch', ref_protected: true, sha,
      actor: 'wzyn20051216', triggering_actor: 'wzyn20051216',
    },
    branch: { protected: true, commit: { sha } },
    rules: structuredClone(live.rules),
    rulesets: [live],
    permissions: { wzyn20051216: 'admin' },
    environment: { id: 1, name: 'cad-validation', protection_rules: [],
      deployment_branch_policy: { protected_branches: true, custom_branch_policies: false } },
    runners: [{ status: 'online', busy: false, labels: ['self-hosted', 'Windows', 'CAD'].map(name => ({ name })) }],
    attestation: options.attestation === undefined ? attestationFor(live, options.attestationOptions) : options.attestation,
    trustRoot: options.trustRoot === undefined ? TRUST_ROOT : options.trustRoot,
    trustRootAnchor: options.trustRootAnchor === undefined ? ANCHOR : options.trustRootAnchor,
    attestationSource: options.attestationSource === undefined ? null : options.attestationSource,
    now: options.now || NOW,
    ...(options.snapshot || {}),
  };
}

/** @brief 断言被阻断且指定检查项为 false。 */
function assertBlocked(report, checkKey, reasonHint) {
  assert.equal(report.status, 'blocked', `期望 blocked，实际 ${report.status}: ${JSON.stringify(report.blocking_reasons)}`);
  if (checkKey) assert.equal(report.checks[checkKey], false, `期望 ${checkKey} 为 false`);
  if (reasonHint) assert.ok(report.attestation_reasons.some(r => r.includes(reasonHint)),
    `期望 reasons 含 ${reasonHint}，实际 ${report.attestation_reasons.join(',')}`);
}

// ---------------------------------------------------------------- 正向准入

test('只读凭据读不到 bypass 时，配置合规且证明有效即可准入', () => {
  const snapshot = valid();
  assert.equal('bypass_actors' in snapshot.rulesets[0], false);
  const report = evaluatePolicy(snapshot);
  assert.equal(report.status, 'authorized', JSON.stringify(report.blocking_reasons));
  assert.equal(report.checks.no_bypass_actors, true);
  assert.equal(report.governance.bypass_visible, false);
  assert.equal(report.governance.bypass_proof, 'offline_signed_attestation');
  assert.deepEqual(report.governance.bypass_actors, []);
});

test('单人维护配置可准入，但不谎称完成整体安全验收', () => {
  const report = evaluatePolicy(valid());
  assert.equal(report.scope, 'workflow_admission_only');
  assert.equal(report.safety_acceptance_complete, false);
  assert.equal(report.governance.mode, 'single_maintainer');
  assert.equal(report.governance.independent_audit, false);
});

test('审批数为 0 不构成治理失败，且不因缺少独立审查人误报', () => {
  const report = evaluatePolicy(valid());
  assert.equal(report.checks.pull_request_required, true);
  assert.equal(report.status, 'authorized');
  assert.ok(report.governance.remaining_risks.includes('no_independent_human_reviewer'));
});

test('单人维护不得被表述为独立审批或独立审计', () => {
  const report = evaluatePolicy(valid());
  assert.match(report.governance.note, /未提供独立审批/);
  assert.ok(report.manual_conditions.some(text => text.includes('不得表述为独立审计')));
});

test('存在独立审查人时同样可准入，是否具备只作风险披露', () => {
  const report = evaluatePolicy(valid({ snapshot: { environment: { id: 1, name: 'cad-validation',
    protection_rules: [{ type: 'required_reviewers', prevent_self_review: true, reviewers: [{ id: 1 }] }],
    deployment_branch_policy: { protected_branches: true, custom_branch_policies: false } } } }));
  assert.equal(report.status, 'authorized', JSON.stringify(report.blocking_reasons));
  assert.equal(report.governance.independent_human_review, true);
  assert.ok(!report.governance.remaining_risks.includes('no_independent_human_reviewer'));
});

test('Environment 配置了审查人却允许自审时记录风险', () => {
  const report = evaluatePolicy(valid({ snapshot: { environment: { id: 1, name: 'cad-validation',
    protection_rules: [{ type: 'required_reviewers', prevent_self_review: false, reviewers: [{ id: 1 }] }],
    deployment_branch_policy: { protected_branches: true, custom_branch_policies: false } } } }));
  assert.equal(report.governance.independent_human_review, false);
  assert.ok(report.governance.remaining_risks.includes('environment_allows_self_review'));
});

test('治理风险披露必须包含 CODEOWNERS 未强制与可信基线缺失', () => {
  const report = evaluatePolicy(valid());
  for (const risk of ['code_owner_review_not_enforced', 'trusted_baseline_workflow_not_established',
    'trust_root_stored_in_repository', 'attestation_self_issued_by_maintainer', 'bypass_list_not_readable']) {
    assert.ok(report.governance.remaining_risks.includes(risk), `应披露 ${risk}`);
  }
});

// ---------------------------------------------------------------- 分支与来源

test('非 main 的受保护分支不得通过：凭据链路只允许 main', () => {
  const report = evaluatePolicy(valid({ snapshot: { context: {
    repository: TRUSTED_REPOSITORY, repository_id: TRUSTED_REPOSITORY_ID, event_name: 'workflow_dispatch',
    ref: 'refs/heads/release', ref_type: 'branch', ref_protected: true, sha: 'a'.repeat(40),
    actor: 'wzyn20051216', triggering_actor: 'wzyn20051216' } } }));
  assertBlocked(report, 'protected_ref_is_main');
});

test('非受保护分支不得通过', () => {
  const report = evaluatePolicy(valid({ snapshot: { context: {
    repository: TRUSTED_REPOSITORY, repository_id: TRUSTED_REPOSITORY_ID, event_name: 'workflow_dispatch',
    ref: 'refs/heads/main', ref_type: 'branch', ref_protected: false, sha: 'a'.repeat(40),
    actor: 'wzyn20051216', triggering_actor: 'wzyn20051216' } } }));
  assertBlocked(report, 'manual_branch_only');
});

test('仓库身份不符时不发起权限请求也不准入', () => {
  const report = evaluatePolicy(valid({ snapshot: { context: {
    repository: 'someone/fork', repository_id: '1', event_name: 'workflow_dispatch',
    ref: 'refs/heads/main', ref_type: 'branch', ref_protected: true, sha: 'a'.repeat(40),
    actor: 'x', triggering_actor: 'x' } } }));
  assertBlocked(report, 'trusted_repository');
});

test('提交 SHA 与分支 HEAD 不一致时阻断', () => {
  const report = evaluatePolicy(valid({ snapshot: { branch: { protected: true, commit: { sha: 'b'.repeat(40) } } } }));
  assertBlocked(report, 'protected_immutable_source');
});

// ---------------------------------------------------------------- 证明缺失与格式

test('证明缺失时阻断，且不把缺失当成空 bypass', () => {
  const report = evaluatePolicy(valid({ attestation: null }));
  assertBlocked(report, 'attestation_present', 'attestation_missing');
  assert.equal(report.governance.bypass_actors, null);
});

test('旧 schema（v1）证明不被接受', () => {
  const attestation = attestationFor();
  attestation.schema = 'cad-governance-attestation/v1';
  assertBlocked(evaluatePolicy(valid({ attestation: resign(attestation) })), 'attestation_schema',
    'attestation_schema_unsupported');
});

test('证明不可解析时阻断并给出明确错误', () => {
  const broken = path.join(TMP_ROOT, 'broken.json');
  fs.writeFileSync(broken, '{ not json');
  const { attestation, error, source } = readAttestation({ NODE_ENV: 'test', GOVERNANCE_ATTESTATION_PATH: broken });
  assert.equal(attestation, null);
  assert.match(error, /unreadable/);
  assert.equal(source.test_override, true);
});

test('证明文件不存在时给出明确错误', () => {
  const { attestation, error } = readAttestation({ NODE_ENV: 'test',
    GOVERNANCE_ATTESTATION_PATH: path.join(TMP_ROOT, 'nope.json') });
  assert.equal(attestation, null);
  assert.match(error, /missing/);
});

// ---------------------------------------------------------------- 签名与密钥

test('签名被篡改时阻断', () => {
  const attestation = attestationFor();
  attestation.signature = Buffer.from('tampered').toString('base64');
  assertBlocked(evaluatePolicy(valid({ attestation })), 'attestation_signature', 'attestation_signature_invalid');
});

test('内容被改动而签名未更新时阻断', () => {
  const attestation = attestationFor();
  attestation.captured_at = new Date(NOW.getTime() - DAY_MS).toISOString();
  assertBlocked(evaluatePolicy(valid({ attestation })), 'attestation_signature');
});

test('未知 key ID 时阻断', () => {
  const other = newKey();
  const attestation = attestationFor(liveRuleset(), { privatePem: other.privatePem, keyId: lib.keyIdOf(other.publicPem) });
  assertBlocked(evaluatePolicy(valid({ attestation })), 'attestation_signature', 'attestation_key_unknown');
});

test('签名 key 指纹与登记条目不符时阻断', () => {
  const attestation = attestationFor();
  const root = { keys: { [KEY_ID]: { pem: newKey().publicPem, not_before: null, revoked_at: null } }, log: [KEY_ID] };
  const report = evaluatePolicy(valid({ attestation, trustRoot: root, trustRootAnchor: lib.trustRootAnchor(root) }));
  assertBlocked(report, 'attestation_signature', 'attestation_key_fingerprint_mismatch');
});

test('已吊销的签名密钥不被接受', () => {
  const attestation = attestationFor();
  const root = trustRoot({ entry: { revoked_at: new Date(NOW.getTime() - DAY_MS).toISOString() } });
  const report = evaluatePolicy(valid({ attestation, trustRoot: root, trustRootAnchor: lib.trustRootAnchor(root) }));
  assertBlocked(report, 'attestation_signature', 'attestation_key_revoked');
});

test('密钥尚未生效时阻断', () => {
  const attestation = attestationFor();
  const root = trustRoot({ entry: { not_before: new Date(NOW.getTime() + DAY_MS).toISOString() } });
  const report = evaluatePolicy(valid({ attestation, trustRoot: root, trustRootAnchor: lib.trustRootAnchor(root) }));
  assertBlocked(report, 'attestation_signature', 'attestation_key_not_yet_valid');
});

// ---------------------------------------------------------------- 时间窗口

test('证明过期或被超长 TTL 签发时阻断', () => {
  const expired = attestationFor(liveRuleset(), { capturedAt: new Date(NOW.getTime() - 40 * DAY_MS).toISOString(),
    expiresAt: new Date(NOW.getTime() - DAY_MS).toISOString() });
  assertBlocked(evaluatePolicy(valid({ attestation: expired })), 'attestation_fresh');
  const longTtl = attestationFor(liveRuleset(), { expiresAt: new Date(NOW.getTime() + 90 * DAY_MS).toISOString() });
  assertBlocked(evaluatePolicy(valid({ attestation: longTtl })), 'attestation_fresh');
});

test('证明时间在未来（超出时钟偏移）时阻断', () => {
  const future = attestationFor(liveRuleset(), { capturedAt: new Date(NOW.getTime() + 30 * 60 * 1000).toISOString() });
  assertBlocked(evaluatePolicy(valid({ attestation: future })), 'attestation_fresh');
});

// ---------------------------------------------------------------- 身份与范围

test('仓库 ID 或全名不匹配时阻断', () => {
  const wrongId = attestationFor(liveRuleset(), { repository: { id: '999', full_name: REPO.full_name } });
  assertBlocked(evaluatePolicy(valid({ attestation: wrongId })), 'attestation_repository');
  const wrongName = attestationFor(liveRuleset(), { repository: { id: REPO.id, full_name: 'a/b' } });
  assertBlocked(evaluatePolicy(valid({ attestation: wrongName })), 'attestation_repository');
});

test('规则集 ID 不匹配时阻断', () => {
  // 证明针对原规则集签发，线上 ID 被替换
  const attestation = attestationFor(liveRuleset());
  const live = liveRuleset();
  live.id = 1;
  assertBlocked(evaluatePolicy(valid({ live, attestation })), 'attestation_ruleset_identity');
});

test('规则集 enforcement 非 active 时阻断', () => {
  const live = liveRuleset();
  live.enforcement = 'evaluate';
  const report = evaluatePolicy(valid({ live, snapshot: { rulesets: [live] } }));
  assertBlocked(report, 'ruleset_active');
});

test('main 分支适用范围不匹配时阻断（证明侧）', () => {
  const attestation = attestationFor(liveRuleset(), { refInclude: ['refs/heads/*'] });
  assertBlocked(evaluatePolicy(valid({ attestation })), 'attestation_main_scope');
});

test('main 分支适用范围不匹配时阻断（线上侧）', () => {
  const attestation = attestationFor(liveRuleset());
  const live = liveRuleset();
  live.conditions.ref_name.include = ['refs/heads/main', 'refs/heads/release'];
  assertBlocked(evaluatePolicy(valid({ live, attestation })), 'attestation_main_scope');
});

// ---------------------------------------------------------------- 双摘要

test('policy_digest 不匹配时阻断：规则内容变化使旧证明失效', () => {
  const attestation = attestationFor(liveRuleset());
  const live = liveRuleset();
  live.rules.find(r => r.type === 'pull_request').parameters.required_approving_review_count = 2;
  assertBlocked(evaluatePolicy(valid({ live, attestation })), 'attestation_policy_digest', 'policy_digest_mismatch');
});

test('policy_digest 不覆盖 bypass：改 bypass 只影响 snapshot_digest', () => {
  const base = attestationFor();
  const withBypass = attestationFor(liveRuleset(), { bypass: [{ actor_id: 1, actor_type: 'User', bypass_mode: 'always' }] });
  assert.equal(base.policy_digest_sha256, withBypass.policy_digest_sha256, 'policy_digest 不应随 bypass 变化');
  assert.notEqual(base.snapshot_digest_sha256, withBypass.snapshot_digest_sha256, 'snapshot_digest 必须覆盖 bypass');
});

test('snapshot_digest 被篡改时阻断', () => {
  const attestation = attestationFor(liveRuleset(), { snapshotDigest: 'f'.repeat(64) });
  assertBlocked(evaluatePolicy(valid({ attestation })), 'attestation_snapshot_digest');
});

test('updated_at 变化时阻断：任何配置变更都使旧证明失效', () => {
  const attestation = attestationFor(liveRuleset());
  const live = liveRuleset();
  live.updated_at = '2026-10-26T00:00:00.000Z';
  assertBlocked(evaluatePolicy(valid({ live, attestation })), 'attestation_updated_at', 'updated_at_mismatch');
});

test('线上可见完整快照时 snapshot_digest 需与线上一致', () => {
  const visible = liveRuleset();
  visible.bypass_actors = [];
  assert.equal(evaluatePolicy(valid({ live: visible })).status, 'authorized');
  const attestedBypass = attestationFor(liveRuleset(), { bypass: [{ actor_id: 1, actor_type: 'User', bypass_mode: 'always' }] });
  const liveOther = liveRuleset();
  liveOther.bypass_actors = [{ actor_id: 2, actor_type: 'Team', bypass_mode: 'always' }];
  assertBlocked(evaluatePolicy(valid({ live: liveOther, attestation: attestedBypass })), 'attestation_snapshot_digest');
});

// ---------------------------------------------------------------- bypass 语义

test('bypass 非空时阻断，不得判为合规', () => {
  const attestation = attestationFor(liveRuleset(), { bypass: [{ actor_id: 199356225, actor_type: 'User', bypass_mode: 'always' }] });
  const report = evaluatePolicy(valid({ attestation }));
  assertBlocked(report, 'no_bypass_actors', 'attestation_bypass_not_empty');
  assert.equal(report.checks.attestation_compliant, false);
});

test('证明缺少 bypass_actors 字段时阻断，不得解释为空', () => {
  const attestation = attestationFor();
  delete attestation.ruleset.bypass_actors;
  const report = evaluatePolicy(valid({ attestation: resign(attestation) }));
  assertBlocked(report, 'no_bypass_actors');
  assert.equal(report.governance.bypass_actors, null);
});

test('bypass_actors 字段类型错误时阻断', () => {
  const attestation = attestationFor();
  attestation.ruleset.bypass_actors = 'none';
  assertBlocked(evaluatePolicy(valid({ attestation: resign(attestation) })), 'no_bypass_actors');
});

test('线上能看见 bypass 且非空时阻断（纵深检查）', () => {
  const live = liveRuleset();
  live.bypass_actors = [{ actor_id: 199356225, actor_type: 'User', bypass_mode: 'always' }];
  assertBlocked(evaluatePolicy(valid({ live })), 'live_bypass_consistent');
});

// ---------------------------------------------------------------- 合规字段

test('compliant 为 false 的证明不可用于准入', () => {
  const attestation = attestationFor(liveRuleset(), { compliant: false, noncomplianceReasons: ['bypass_not_empty'] });
  assertBlocked(evaluatePolicy(valid({ attestation })), 'attestation_compliant', 'attestation_not_compliant');
});

test('compliant 声称 true 但带 noncompliance_reasons 时阻断', () => {
  const attestation = attestationFor(liveRuleset(), { compliant: true, noncomplianceReasons: ['something'] });
  assertBlocked(evaluatePolicy(valid({ attestation })), 'attestation_compliant', 'compliance_inconsistent');
});

test('compliant 声称 true 但按内容重算不合规时阻断', () => {
  const live = liveRuleset();
  live.rules = [{ type: 'deletion' }, { type: 'pull_request', parameters: { required_approving_review_count: 0 } }];
  const attestation = attestationFor(live, { compliant: true, noncomplianceReasons: [] });
  assertBlocked(evaluatePolicy(valid({ live, attestation })), 'attestation_compliant');
});

test('缺少必需状态检查时阻断', () => {
  const live = liveRuleset();
  live.rules = live.rules.filter(r => r.type !== 'required_status_checks');
  const report = evaluatePolicy(valid({ live }));
  assertBlocked(report, 'required_status_checks_present');
});

test('缺少 Pull Request 保护时阻断', () => {
  const report = evaluatePolicy(valid({ snapshot: { rules: [
    { type: 'required_status_checks', parameters: { required_status_checks: [{ context: 'test-and-build' }] } }] } }));
  assertBlocked(report, 'pull_request_required');
});

test('没有活跃 ruleset 时阻断', () => {
  assertBlocked(evaluatePolicy(valid({ snapshot: { rulesets: [] } })), 'ruleset_active');
});

// ---------------------------------------------------------------- 信任根与轮换日志

test('信任根缺失时阻断', () => {
  const report = evaluatePolicy(valid({ trustRoot: null }));
  assertBlocked(report, 'trust_root_integrity');
  assertBlocked(report, 'trust_root_anchor', 'trust_root_anchor_uncomputable');
});

test('信任根结构错误时阻断', () => {
  const report = evaluatePolicy(valid({ trustRoot: { keys: {}, log: 'not-array' }, trustRootAnchor: ANCHOR }));
  assertBlocked(report, 'trust_root_integrity');
});

test('轮换日志引用不存在的密钥时阻断（日志断裂）', () => {
  const root = { keys: { [KEY_ID]: { pem: KEY.publicPem, not_before: null, revoked_at: null } }, log: [KEY_ID, 'ed25519:dead'] };
  const report = evaluatePolicy(valid({ trustRoot: root, trustRootAnchor: lib.trustRootAnchor(root) }));
  assertBlocked(report, 'trust_root_rotation_log', 'rotation_log_unknown_key');
});

test('存在未登记到轮换日志的密钥时阻断', () => {
  const other = newKey();
  const otherId = lib.keyIdOf(other.publicPem);
  const root = { keys: { [KEY_ID]: { pem: KEY.publicPem, not_before: null, revoked_at: null },
    [otherId]: { pem: other.publicPem, not_before: null, revoked_at: null } }, log: [KEY_ID] };
  const report = evaluatePolicy(valid({ trustRoot: root, trustRootAnchor: lib.trustRootAnchor(root) }));
  assertBlocked(report, 'trust_root_rotation_log', 'rotation_log_untracked_key');
});

test('退役密钥未设置 revoked_at 时阻断，缺失不被默认为已撤销', () => {
  const old = newKey();
  const oldId = lib.keyIdOf(old.publicPem);
  const root = { keys: {
    [oldId]: { pem: old.publicPem, not_before: null, revoked_at: null },
    [KEY_ID]: { pem: KEY.publicPem, not_before: null, revoked_at: null },
  }, log: [oldId, KEY_ID] };
  const report = evaluatePolicy(valid({ trustRoot: root, trustRootAnchor: lib.trustRootAnchor(root) }));
  assertBlocked(report, 'trust_root_rotation_log', 'rotation_log_retired_key_not_revoked');
});

test('退役密钥已撤销时轮换日志通过，旧证明因 key 被吊销而失效', () => {
  const old = newKey();
  const oldId = lib.keyIdOf(old.publicPem);
  const root = { keys: {
    [oldId]: { pem: old.publicPem, not_before: null, revoked_at: '2026-10-01T00:00:00Z' },
    [KEY_ID]: { pem: KEY.publicPem, not_before: null, revoked_at: null },
  }, log: [oldId, KEY_ID] };
  const anchor = lib.trustRootAnchor(root);
  assert.equal(evaluatePolicy(valid({ trustRoot: root, trustRootAnchor: anchor })).status, 'authorized');
  const oldAttestation = attestationFor(liveRuleset(), { privatePem: old.privatePem, keyId: oldId });
  assertBlocked(evaluatePolicy(valid({ attestation: oldAttestation, trustRoot: root, trustRootAnchor: anchor })),
    'attestation_signature', 'attestation_key_revoked');
});

test('当前活跃密钥被撤销时阻断（无人可签）', () => {
  const root = trustRoot({ entry: { revoked_at: '2026-10-26T00:00:00Z' } });
  const report = evaluatePolicy(valid({ trustRoot: root, trustRootAnchor: lib.trustRootAnchor(root) }));
  assertBlocked(report, 'trust_root_rotation_log', 'rotation_log_active_key_revoked');
});

test('轮换日志重复条目时阻断', () => {
  const root = { keys: { [KEY_ID]: { pem: KEY.publicPem, not_before: null, revoked_at: null } }, log: [KEY_ID, KEY_ID] };
  const report = evaluatePolicy(valid({ trustRoot: root, trustRootAnchor: lib.trustRootAnchor(root) }));
  assertBlocked(report, 'trust_root_rotation_log', 'rotation_log_duplicate_key');
});

// ---------------------------------------------------------------- 信任锚点（仓库变量）

test('信任锚点缺失时阻断：仓库变量未配置不得放行', () => {
  assertBlocked(evaluatePolicy(valid({ trustRootAnchor: null })), 'trust_root_anchor', 'trust_root_anchor_missing');
});

test('信任锚点格式非法时阻断', () => {
  assertBlocked(evaluatePolicy(valid({ trustRootAnchor: 'not-a-digest' })), 'trust_root_anchor', 'trust_root_anchor_invalid_format');
});

test('信任根被整体替换（公钥+日志+重签）时因锚点不符而阻断', () => {
  const attacker = newKey();
  const attackerId = lib.keyIdOf(attacker.publicPem);
  const forgedRoot = { keys: { [attackerId]: { pem: attacker.publicPem, not_before: null, revoked_at: null } }, log: [attackerId] };
  const forgedAttestation = attestationFor(liveRuleset(), { privatePem: attacker.privatePem, keyId: attackerId });
  // 攻击者可以做到自洽：签名有效、日志一致、摘要正确、锚点与其自身信任根匹配。
  assert.equal(evaluatePolicy(valid({ attestation: forgedAttestation, trustRoot: forgedRoot,
    trustRootAnchor: lib.trustRootAnchor(forgedRoot) })).status, 'authorized');
  // 但仓库变量锚点仍指向原信任根，因此真实部署会阻断。
  const report = evaluatePolicy(valid({ attestation: forgedAttestation, trustRoot: forgedRoot, trustRootAnchor: ANCHOR }));
  assertBlocked(report, 'trust_root_anchor', 'trust_root_anchor_mismatch');
  assert.equal(report.governance.trust_root_anchor.matched, false);
});

test('锚点与实际信任根一致时才通过', () => {
  const report = evaluatePolicy(valid());
  assert.equal(report.checks.trust_root_anchor, true);
  assert.equal(report.governance.trust_root_anchor.expected, ANCHOR);
  assert.equal(report.governance.trust_root_anchor.actual, ANCHOR);
});

test('锚点忽略 PEM 的换行风格与首尾空白差异', () => {
  const crlfRoot = { keys: { [KEY_ID]: { pem: `${KEY.publicPem.replace(/\n/g, '\r\n')}\r\n\r\n`,
    not_before: '2026-01-01T00:00:00Z', revoked_at: null } }, log: [KEY_ID] };
  assert.equal(lib.trustRootAnchor(crlfRoot), ANCHOR);
});

// ---------------------------------------------------------------- 路径注入

test('生产环境不得接受 GOVERNANCE_ATTESTATION_PATH 注入', () => {
  const fake = path.join(TMP_ROOT, 'injected.json');
  fs.writeFileSync(fake, JSON.stringify({ hello: 'injected' }));
  for (const nodeEnv of [undefined, 'production', 'development']) {
    const { source, attestation } = readAttestation({ NODE_ENV: nodeEnv, GOVERNANCE_ATTESTATION_PATH: fake });
    assert.equal(source.test_override, false, `NODE_ENV=${nodeEnv} 不应接受路径注入`);
    assert.equal(source.path, 'docs/architecture/evidence/governance-ruleset-attestation.json');
    assert.equal(source.ignored_env_path, true);
    // 读到的必须是固定路径的内容，而不是被注入的文件
    assert.notEqual(attestation?.hello, 'injected', '不得回退读取被注入的文件');
  }
});

test('仅在 NODE_ENV=test 时才允许路径覆盖', () => {
  const fake = path.join(TMP_ROOT, 'test-only.json');
  fs.writeFileSync(fake, JSON.stringify({ hello: 'world' }));
  const enabled = readAttestation({ NODE_ENV: 'test', GOVERNANCE_ATTESTATION_PATH: fake });
  assert.equal(enabled.source.test_override, true);
  assert.deepEqual(enabled.attestation, { hello: 'world' });
  const disabled = readAttestation({ NODE_ENV: 'test', GOVERNANCE_ATTESTATION_PATH: '' });
  assert.equal(disabled.source.test_override, false);
});

test('路径被测试环境覆盖时在治理风险中记录', () => {
  const report = evaluatePolicy(valid({ attestationSource: {
    path: 'docs/architecture/evidence/governance-ruleset-attestation.json', test_override: true, ignored_env_path: false } }));
  assert.ok(report.governance.remaining_risks.includes('attestation_path_overridden_by_test_env'));
});

// ---------------------------------------------------------------- 只读快照

test('不可信上下文不发 API 请求', async () => {
  const snapshot = await readSnapshot({ GITHUB_REPOSITORY: 'someone/fork', GITHUB_REPOSITORY_ID: '1',
    GITHUB_EVENT_NAME: 'workflow_dispatch', GITHUB_REF: 'refs/heads/main', GITHUB_REF_TYPE: 'branch',
    GITHUB_REF_PROTECTED: 'true', NODE_ENV: 'production' });
  assert.equal(snapshot.context.repository, 'someone/fork');
  assert.equal(snapshot.branch, undefined);
  assert.ok(snapshot.attestationSource);
});

test('缺少只读审计凭据时阻断', async () => {
  await assert.rejects(() => readSnapshot({ GITHUB_REPOSITORY: TRUSTED_REPOSITORY,
    GITHUB_REPOSITORY_ID: TRUSTED_REPOSITORY_ID, GITHUB_EVENT_NAME: 'workflow_dispatch',
    GITHUB_REF: 'refs/heads/main', GITHUB_REF_TYPE: 'branch', GITHUB_REF_PROTECTED: 'true',
    NODE_ENV: 'production' }), /CAD_CI_AUDIT_TOKEN missing/);
});

test('缺少仓库变量锚点时准入被阻断', async () => {
  const baseEnv = { GITHUB_REPOSITORY: TRUSTED_REPOSITORY, GITHUB_REPOSITORY_ID: TRUSTED_REPOSITORY_ID,
    GITHUB_EVENT_NAME: 'workflow_dispatch', GITHUB_REF: 'refs/heads/main', GITHUB_REF_TYPE: 'branch',
    GITHUB_REF_PROTECTED: 'true', NODE_ENV: 'production' };
  // 未配置锚点：readSnapshot 不会伪造锚点，且因缺少只读凭据而阻断
  await assert.rejects(() => readSnapshot(baseEnv), /CAD_CI_AUDIT_TOKEN missing/);
  const snapshot = await readSnapshot({ ...baseEnv, GITHUB_REPOSITORY: 'someone/fork' });
  assert.equal(snapshot.trustRootAnchor, undefined);
  // valid() 的 undefined 表示"用默认锚点"，因此这里显式传 null 表达"未配置"
  assertBlocked(evaluatePolicy(valid({ trustRootAnchor: snapshot.trustRootAnchor ?? null })),
    'trust_root_anchor', 'trust_root_anchor_missing');
});

test('Runner 或 Environment 缺失时阻断（B-01 前提）', () => {
  assertBlocked(evaluatePolicy(valid({ snapshot: { runners: [] } })), 'idle_windows_cad_runner');
  assertBlocked(evaluatePolicy(valid({ snapshot: { environment: null } })), 'protected_environment_exists');
  assertBlocked(evaluatePolicy(valid({ snapshot: { environment: { id: 1, name: 'cad-validation',
    deployment_branch_policy: { protected_branches: false, custom_branch_policies: true } } } })),
  'protected_deployment_branches');
});

test('Environment 名称不符时阻断', () => {
  assertBlocked(evaluatePolicy(valid({ snapshot: { environment: { id: 1, name: 'production',
    deployment_branch_policy: { protected_branches: true, custom_branch_policies: false } } } })),
  'protected_environment_exists');
});

test('Runner 在线但被占用时阻断', () => {
  assertBlocked(evaluatePolicy(valid({ snapshot: { runners: [{ status: 'online', busy: true,
    labels: [{ name: 'self-hosted' }, { name: 'Windows' }, { name: 'CAD' }] }] } })), 'idle_windows_cad_runner');
});

test('Runner 缺少必需标签时阻断', () => {
  assertBlocked(evaluatePolicy(valid({ snapshot: { runners: [{ status: 'online', busy: false,
    labels: [{ name: 'self-hosted' }, { name: 'Linux' }] }] } })), 'idle_windows_cad_runner');
});

test('触发者与重跑者都必须是 admin 或 maintain', () => {
  assertBlocked(evaluatePolicy(valid({ snapshot: { permissions: { wzyn20051216: 'read' } } })),
    'authorized_actor_and_rerunner');
});

// ---------------------------------------------------------------- 故障注入矩阵

const faults = {
  'actor 权限降级': s => { s.permissions = { wzyn20051216: 'read' }; },
  'Environment 缺失': s => { s.environment = null; },
  'Runner 离线': s => { s.runners = [{ status: 'offline', busy: false, labels: [] }]; },
  '仓库被替换': s => { s.context.repository = 'evil/fork'; },
  'SHA 非 40 位': s => { s.context.sha = 'abc'; },
  '分支 HEAD 与 SHA 不符': s => { s.branch = { protected: true, commit: { sha: 'c'.repeat(40) } }; },
  '必需检查被改名': s => { s.rules = [{ type: 'pull_request', parameters: {} },
    { type: 'required_status_checks', parameters: { required_status_checks: [{ context: 'build' }] } }]; },
  '没有活跃 ruleset': s => { s.rulesets = []; },
  '环境分支策略放开': s => { s.environment.deployment_branch_policy = { protected_branches: false, custom_branch_policies: false }; },
  '证明被清空': s => { s.attestation = null; },
  '锚点被清空': s => { s.trustRootAnchor = ''; },
};

for (const [name, mutate] of Object.entries(faults)) {
  test(`拒绝故障注入：${name}`, () => {
    const snapshot = valid();
    mutate(snapshot);
    const report = evaluatePolicy(snapshot);
    assert.equal(report.status, 'blocked', `${name} 应阻断，实际 ${report.status}`);
    assert.ok(report.blocking_reasons.length > 0);
  });
}

// ---------------------------------------------------------------- 采集工具

const SECRET = 'ghp_thisMustNeverAppearInAnyOutput0123456789';

/** @brief 合成 GitHub API；detail 中删掉 bypass 可模拟只读凭据。 */
function fakeApi(detail) {
  return async (token, route) => {
    if (token !== SECRET) throw new Error('bad token');
    if (route === `/repos/${TRUSTED_REPOSITORY}`) return { id: Number(TRUSTED_REPOSITORY_ID), full_name: TRUSTED_REPOSITORY };
    if (route.includes('?per_page')) return [{ id: RULESET_ID, name: 'protect-main' }];
    if (route.endsWith(`/rulesets/${RULESET_ID}`)) return detail;
    throw new Error(`unexpected route ${route}`);
  };
}

function compliantDetail() { return { ...liveRuleset(), bypass_actors: [] }; }

test('采集工具在看不到 bypass_actors 时拒绝生成证明', async () => {
  const detail = compliantDetail();
  delete detail.bypass_actors;
  await assert.rejects(() => captureTool.capture({ token: SECRET, privateKeyPem: KEY.privatePem, now: NOW,
    fetchJson: fakeApi(detail) }), /看不到 bypass_actors/);
});

test('采集工具拒绝与固定仓库身份不符的响应', async () => {
  const api = async () => ({ id: 1, full_name: 'a/b' });
  await assert.rejects(() => captureTool.capture({ token: SECRET, privateKeyPem: KEY.privatePem, now: NOW,
    fetchJson: api }), /仓库身份不符/);
});

test('采集工具在合规状态下签发 compliant=true，且产物不含凭据', async () => {
  const { attestation, compliance } = await captureTool.capture({ token: SECRET, privateKeyPem: KEY.privatePem,
    now: NOW, fetchJson: fakeApi(compliantDetail()) });
  assert.equal(compliance.compliant, true);
  assert.equal(attestation.compliant, true);
  assert.deepEqual(attestation.noncompliance_reasons, []);
  const serialized = JSON.stringify(attestation);
  assert.ok(!serialized.includes(SECRET), '产物不得包含令牌');
  assert.ok(!serialized.includes('PRIVATE KEY'), '产物不得包含私钥');
  assert.equal(attestation.policy_digest_sha256.length, 64);
  assert.equal(attestation.snapshot_digest_sha256.length, 64);
  assert.equal(attestation.schema, lib.SCHEMA);
});

test('采集产物可通过只读校验（合规 + 锚点匹配）', async () => {
  const { attestation } = await captureTool.capture({ token: SECRET, privateKeyPem: KEY.privatePem,
    now: NOW, fetchJson: fakeApi(compliantDetail()) });
  const report = evaluatePolicy(valid({ attestation }));
  assert.equal(report.status, 'authorized', JSON.stringify(report.blocking_reasons));
});

test('远端 bypass 非空时默认拒签：抛错且不产生文件', async () => {
  const out = path.join(TMP_ROOT, 'refused.json');
  const detail = { ...liveRuleset(), bypass_actors: [{ actor_id: 199356225, actor_type: 'User', bypass_mode: 'always' }] };
  await assert.rejects(() => captureTool.runCapture({
    ttlDays: 10, out, key: 'unused', printOnly: false, allowNoncompliant: false,
  }, { env: { GOVERNANCE_SIGNING_KEY: KEY.privatePem, GH_TOKEN: SECRET }, fetchJson: fakeApi(detail) }),
  error => { assert.equal(error.compliance.compliant, false); return true; });
  assert.equal(fs.existsSync(out), false, '拒签时不得留下任何证明文件');
});

test('显式 --allow-noncompliant 时留证，但标记 compliant=false 且不可准入', async () => {
  const out = path.join(TMP_ROOT, 'allowed-noncompliant.json');
  const detail = { ...liveRuleset(), bypass_actors: [{ actor_id: 199356225, actor_type: 'User', bypass_mode: 'always' }] };
  const { attestation, compliance } = await captureTool.runCapture({
    ttlDays: 10, out, key: 'unused', printOnly: false, allowNoncompliant: true,
  }, { env: { GOVERNANCE_SIGNING_KEY: KEY.privatePem, GH_TOKEN: SECRET }, fetchJson: fakeApi(detail) });
  assert.equal(compliance.compliant, false);
  assert.equal(attestation.compliant, false);
  assert.ok(attestation.noncompliance_reasons.includes('bypass_not_empty'));
  assert.ok(fs.existsSync(out));
  const saved = JSON.parse(fs.readFileSync(out, 'utf8'));
  const report = evaluatePolicy(valid({ attestation: saved }));
  assert.equal(report.status, 'blocked');
  assert.equal(report.checks.attestation_compliant, false);
});

test('采集参数校验：TTL 越界与未知参数被拒绝', () => {
  assert.throws(() => captureTool.parseArgs(['--ttl-days', '0']), /1\.\.30/);
  assert.throws(() => captureTool.parseArgs(['--ttl-days', '31']), /1\.\.30/);
  assert.throws(() => captureTool.parseArgs(['--nope']), /未知参数/);
  assert.equal(captureTool.parseArgs(['--ttl-days', '7']).ttlDays, 7);
  assert.equal(captureTool.parseArgs(['--allow-noncompliant']).allowNoncompliant, true);
  assert.equal(captureTool.parseArgs(['--verify']).verify, true);
});

// ---------------------------------------------------------------- 漂移检测

test('治理敏感文件清单覆盖准入代码、工作流与测试', () => {
  for (const file of ['scripts/ci/cad_ci_guard.cjs', 'scripts/ci/governance_attestation.cjs',
    'scripts/ci/governance_trust_root.cjs', 'scripts/ci/capture_governance_attestation.cjs',
    'scripts/ci/check_governance_drift.cjs', 'tests/test_cad_ci_guard.cjs',
    '.github/workflows/windows-cad-regression.yml', '.github/workflows/windows-release.yml',
    '.github/workflows/skill-mcp-release.yml',
    '.github/CODEOWNERS', 'docs/architecture/evidence/governance-ruleset-attestation.json']) {
    assert.ok(drift.SENSITIVE_FILES.includes(file), `清单应包含 ${file}`);
  }
});

test('同时修改 guard、工作流与测试会产生三项可见差异', () => {
  const actual = { schema: drift.MANIFEST_SCHEMA, files: {
    'scripts/ci/cad_ci_guard.cjs': 'a', '.github/workflows/windows-cad-regression.yml': 'b',
    'tests/test_cad_ci_guard.cjs': 'c' } };
  const expected = { schema: drift.MANIFEST_SCHEMA, files: {
    'scripts/ci/cad_ci_guard.cjs': '1', '.github/workflows/windows-cad-regression.yml': '2',
    'tests/test_cad_ci_guard.cjs': '3' } };
  const diff = drift.diffManifest(actual, expected);
  assert.equal(diff.changed.length, 3);
  assert.equal(diff.added.length, 0);
  assert.equal(diff.removed.length, 0);
});

test('漂移检测能识别新增与删除的文件', () => {
  const actual = { schema: drift.MANIFEST_SCHEMA, files: { 'a.js': '1', 'b.js': '2' } };
  const expected = { schema: drift.MANIFEST_SCHEMA, files: { 'a.js': '1', 'c.js': '3' } };
  const diff = drift.diffManifest(actual, expected);
  assert.deepEqual(diff.added, ['b.js']);
  assert.deepEqual(diff.removed, ['c.js']);
});

test('仓库当前治理敏感文件与清单一致（真实文件系统）', () => {
  const { manifest, error } = drift.readManifest();
  assert.equal(error, null);
  const diff = drift.diffManifest(drift.computeManifest(), manifest);
  assert.deepEqual(diff.changed, [], `发生漂移: ${diff.changed.join(', ')}（若为有意变更请运行 --update）`);
  assert.deepEqual(diff.added, []);
  assert.deepEqual(diff.removed, []);
});

test('清单缺失或格式不符时阻断', () => {
  const dir = fs.mkdtempSync(path.join(TMP_ROOT, 'drift-'));
  assert.match(drift.readManifest(dir).error, /清单缺失/);
  fs.mkdirSync(path.join(dir, '.github'), { recursive: true });
  fs.writeFileSync(path.join(dir, '.github', 'governance-sensitive-manifest.json'), '{"schema":"other"}');
  assert.match(drift.readManifest(dir).error, /清单格式不符/);
});

test('computeManifest 把缺失的敏感文件记为 null 而不是跳过', () => {
  const manifest = drift.computeManifest(fs.mkdtempSync(path.join(TMP_ROOT, 'drift-empty-')));
  assert.equal(manifest.files['scripts/ci/cad_ci_guard.cjs'], null);
  assert.equal(Object.keys(manifest.files).length, drift.SENSITIVE_FILES.length);
});

test('漂移摘要在 CRLF 与 LF 检出下一致（跨平台不产生假漂移）', () => {
  const dir = fs.mkdtempSync(path.join(TMP_ROOT, 'drift-eol-'));
  const lf = path.join(dir, 'lf.cjs');
  const crlf = path.join(dir, 'crlf.cjs');
  fs.writeFileSync(lf, 'const a = 1;\nconst b = 2;\n');
  fs.writeFileSync(crlf, 'const a = 1;\r\nconst b = 2;\r\n');
  assert.equal(drift.sha256OfFile(lf), drift.sha256OfFile(crlf), '行尾差异不应改变摘要');
});

test('漂移摘要仍能检测真实内容变化', () => {
  const dir = fs.mkdtempSync(path.join(TMP_ROOT, 'drift-content-'));
  const first = path.join(dir, 'a.cjs');
  const second = path.join(dir, 'b.cjs');
  fs.writeFileSync(first, 'const a = 1;\n');
  fs.writeFileSync(second, 'const a = 2;\n');
  assert.notEqual(drift.sha256OfFile(first), drift.sha256OfFile(second), '内容变化必须改变摘要');
});
