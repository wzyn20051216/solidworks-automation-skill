/**
 * @file 离线规则集证明的规范化、摘要与签名校验；纯函数，不发网络请求、不读凭据。
 *
 * 摘要分两层，语义不同，不得混用（见 docs/architecture/governance-attestation.md）：
 *   policy_digest   —— 只看规则内容与适用范围，刻意排除 bypass 与易变元数据。
 *                      用途：证明"修改 bypass 前后规则没有被误改"。
 *   snapshot_digest —— 覆盖完整快照，含 bypass、updated_at、created_at。
 *                      用途：绑定"采集那一刻的完整治理状态"，任何字段变动都会改变它。
 * 不能用 policy_digest 未变来声称"完整配置没有变化"。
 */
const crypto = require('node:crypto');

const SCHEMA = 'cad-governance-attestation/v2';
/** 证明最长有效期；超过即视为过期，避免长期沿用旧证明。 */
const MAX_TTL_DAYS = 30;
/** 允许的时钟偏移，防止本机与 CI 时钟轻微不一致导致误判。 */
const CLOCK_SKEW_MS = 5 * 60 * 1000;
/** 被审计的分支范围；单人维护模式下只有 main 允许运行真机 CAD。 */
const GOVERNED_REF = 'refs/heads/main';
/** 合并前必须通过的既有状态检查；改名需同步 ruleset 与 skill-mcp-release.yml。 */
const REQUIRED_CHECK = 'test-and-build';
/** 采样合规判定时必须存在的规则类型。 */
const REQUIRED_RULE_TYPES = Object.freeze(['pull_request', 'required_status_checks']);
/** 信任锚点环境变量名（GitHub Actions 仓库变量注入）；缺失即阻断。 */
const TRUST_ROOT_ANCHOR_ENV = 'GOVERNANCE_TRUST_ROOT_ANCHOR';

/** @brief 稳定序列化：键排序、丢弃 undefined，确保同一配置在任何机器上摘要一致。 */
function canonical(value) {
  if (value === null || value === undefined) return 'null';
  if (typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  const keys = Object.keys(value).filter(key => value[key] !== undefined).sort();
  return `{${keys.map(key => `${JSON.stringify(key)}:${canonical(value[key])}`).join(',')}}`;
}

function sha256Hex(text) { return crypto.createHash('sha256').update(text, 'utf8').digest('hex'); }

/** @brief 只保留 type 与 parameters；剔除随端点变化的来源字段，避免无意义摘要漂移。 */
function normalizeRule(rule) {
  if (!rule || !rule.type) return null;
  return rule.parameters === undefined ? { type: rule.type } : { type: rule.type, parameters: rule.parameters };
}

/** @brief 归一化 PEM，消除 CRLF 与首尾空白对摘要的影响。 */
function normalizePem(pem) { return String(pem).replace(/\r\n/g, '\n').trim(); }

/** @brief 兼容两种形态：线上 API 的 conditions.ref_name，与证明文件的扁平 ref_name_include/exclude。 */
function refNameOf(ruleset) {
  const nested = ruleset?.conditions?.ref_name;
  if (nested) return { include: [...(nested.include || [])], exclude: [...(nested.exclude || [])] };
  return { include: [...(ruleset?.ref_name_include || [])], exclude: [...(ruleset?.ref_name_exclude || [])] };
}

/**
 * @brief policy_digest 的输入视图：只含规则内容与适用范围。
 * @note 刻意**排除 bypass_actors 与 updated_at**。只读凭据读不到 bypass，若纳入则该摘要永远无法
 *       与线上比对；bypass 的完整绑定由 snapshot_digest 与签名证明承担。
 */
function policyView(ruleset) {
  if (!ruleset || !Array.isArray(ruleset.rules)) return null;
  const refName = refNameOf(ruleset);
  const rules = ruleset.rules.map(normalizeRule).filter(Boolean)
    .sort((left, right) => (left.type < right.type ? -1 : left.type > right.type ? 1 : 0));
  return {
    id: ruleset.id, name: ruleset.name, target: ruleset.target, enforcement: ruleset.enforcement,
    include: [...refName.include].sort(), exclude: [...refName.exclude].sort(), rules,
  };
}

/** @brief policy_digest；无法构造视图时返回 null（由调用方按未知阻断）。 */
function policyDigest(ruleset) {
  const view = policyView(ruleset);
  return view ? sha256Hex(canonical(view)) : null;
}

/** @brief bypass 条目只保留治理相关字段并稳定排序，避免 actor 顺序影响摘要。 */
function normalizeBypass(actors) {
  return actors.map(actor => ({
    actor_id: actor?.actor_id ?? null, actor_type: actor?.actor_type ?? null, bypass_mode: actor?.bypass_mode ?? null,
  })).sort((left, right) => canonical(left) < canonical(right) ? -1 : canonical(left) > canonical(right) ? 1 : 0);
}

/**
 * @brief snapshot_digest 的输入视图：policy 视图 + 完整治理状态。
 * @note bypass 必须是数组（可以为空）；字段缺失一律返回 null，绝不按"空"处理。
 */
function snapshotView(ruleset) {
  const policy = policyView(ruleset);
  if (!policy) return null;
  if (!Array.isArray(ruleset.bypass_actors)) return null;
  if (typeof ruleset.updated_at !== 'string' || ruleset.updated_at.length === 0) return null;
  return {
    policy, bypass_actors: normalizeBypass(ruleset.bypass_actors),
    updated_at: ruleset.updated_at, created_at: typeof ruleset.created_at === 'string' ? ruleset.created_at : null,
  };
}

/** @brief snapshot_digest；无法构造视图时返回 null。 */
function snapshotDigest(ruleset) {
  const view = snapshotView(ruleset);
  return view ? sha256Hex(canonical(view)) : null;
}

/** @brief SPKI DER 的 sha256，作为公钥指纹（key id）的稳定来源。 */
function publicKeyFingerprint(publicKeyPem) {
  const der = crypto.createPublicKey(publicKeyPem).export({ type: 'spki', format: 'der' });
  return sha256Hex(der.toString('hex'));
}

function keyIdOf(publicKeyPem) { return `ed25519:${publicKeyFingerprint(publicKeyPem)}`; }

/** @brief 被签名的字节：除 signature 外的全部字段的规范形式。 */
function signingPayload(attestation) {
  const { signature, ...rest } = attestation || {};
  return Buffer.from(canonical(rest), 'utf8');
}

/** @brief 仅离线采集工具使用；私钥不得进入 CI。 */
function signAttestation(attestation, privateKeyPem) {
  const key = crypto.createPrivateKey(privateKeyPem);
  return crypto.sign(null, signingPayload(attestation), key).toString('base64');
}

function verifySignature(attestation, publicKeyPem) {
  try {
    const signature = Buffer.from(String(attestation?.signature || ''), 'base64');
    if (signature.length === 0) return false;
    return crypto.verify(null, signingPayload(attestation), crypto.createPublicKey(publicKeyPem), signature);
  } catch { return false; }
}

function parseTime(value) {
  const time = Date.parse(value);
  return Number.isFinite(time) ? time : null;
}

/**
 * @brief 信任根锚点：对 keys（含 pem / not_before / revoked_at）与完整轮换日志取稳定摘要。
 * @note 该值应与 GitHub 仓库变量 `GOVERNANCE_TRUST_ROOT_ANCHOR` 一致。变量在仓库文件之外，
 *       因此"同时改公钥 + 改日志 + 重签证明"这一整组操作会与锚点不符而被拒。
 *       它不阻止有仓库管理权限的人连变量一起改，故仍属防篡改留痕而非独立可信根。
 */
function trustRootAnchor(trustRoot) {
  const keys = trustRoot?.keys;
  const log = trustRoot?.log;
  if (!keys || typeof keys !== 'object' || Array.isArray(keys)) return null;
  if (!Array.isArray(log) || log.length === 0) return null;
  if (!log.every(id => typeof id === 'string' && id.length > 0)) return null;
  const view = {};
  for (const id of Object.keys(keys).sort()) {
    const entry = keys[id];
    if (!entry || typeof entry.pem !== 'string') return null;
    view[id] = {
      pem: normalizePem(entry.pem),
      not_before: entry.not_before ?? null,
      revoked_at: entry.revoked_at ?? null,
    };
  }
  return `sha256:${sha256Hex(canonical({ keys: view, log }))}`;
}

/**
 * @brief 轮换日志独立一致性检查。
 * @note 与 `trustRootIntact` 的区别：本函数要求**退役密钥有显式撤销记录**，缺失字段不被默认为已撤销；
 *       同时要求 KEYS 与 ROTATION_LOG 双向一致，避免新增密钥绕过日志留痕。
 */
function rotationLogCheck(trustRoot) {
  const keys = trustRoot?.keys;
  const log = trustRoot?.log;
  if (!keys || typeof keys !== 'object' || Array.isArray(keys)) return { ok: false, reasons: ['rotation_log_keys_malformed'] };
  if (!Array.isArray(log) || log.length === 0) return { ok: false, reasons: ['rotation_log_malformed'] };
  if (!log.every(id => typeof id === 'string' && id.length > 0)) return { ok: false, reasons: ['rotation_log_malformed'] };
  const reasons = [];
  if (new Set(log).size !== log.length) reasons.push('rotation_log_duplicate_key');
  for (const id of log) if (!Object.prototype.hasOwnProperty.call(keys, id)) reasons.push(`rotation_log_unknown_key:${id}`);
  for (const id of Object.keys(keys)) if (!log.includes(id)) reasons.push(`rotation_log_untracked_key:${id}`);
  const lastIndex = log.length - 1;
  log.forEach((id, index) => {
    const entry = keys[id];
    if (!entry) return;
    const revoked = entry.revoked_at;
    const revokedMissing = revoked === null || revoked === undefined || revoked === '';
    if (index < lastIndex) {
      // 已被后续密钥取代 = 退役；必须有可解析的撤销时间，缺失不视为已撤销。
      if (revokedMissing) reasons.push(`rotation_log_retired_key_not_revoked:${id}`);
      else if (parseTime(revoked) === null) reasons.push(`rotation_log_revoked_at_unparseable:${id}`);
    } else if (!revokedMissing) reasons.push(`rotation_log_active_key_revoked:${id}`);
  });
  return { ok: reasons.length === 0, reasons };
}

/** @brief 祖先兼容：轮换日志中记录的每个 key 必须仍在册。 */
function trustRootIntact(trustRoot) {
  const keys = trustRoot?.keys;
  const log = trustRoot?.log;
  if (!keys || typeof keys !== 'object' || !Array.isArray(log)) return false;
  return log.every(id => Object.prototype.hasOwnProperty.call(keys, id));
}

/**
 * @brief 合规判定：这份规则集能否支撑"单人维护 + 强制 PR + 强制 CI + 无绕过"的准入前提。
 * @note 采集工具与校验侧共用同一实现，避免两处判据漂移。
 */
function evaluateCompliance(ruleset, { requiredCheck = REQUIRED_CHECK } = {}) {
  const reasons = [];
  if (!ruleset || typeof ruleset !== 'object') return { compliant: false, reasons: ['ruleset_missing'] };
  if (ruleset.enforcement !== 'active') reasons.push('ruleset_not_active');
  if (ruleset.target !== 'branch') reasons.push('ruleset_target_not_branch');
  const refName = refNameOf(ruleset);
  const mainOnly = refName.include.length === 1 && refName.include[0] === GOVERNED_REF
    && refName.exclude.length === 0;
  if (!mainOnly) reasons.push('ruleset_scope_not_main_only');
  const rules = Array.isArray(ruleset.rules) ? ruleset.rules : [];
  for (const type of REQUIRED_RULE_TYPES) if (!rules.some(rule => rule?.type === type)) reasons.push(`rule_missing:${type}`);
  const statusRule = rules.find(rule => rule?.type === 'required_status_checks');
  const contexts = (statusRule?.parameters?.required_status_checks || []).map(item => item?.context);
  if (statusRule && !contexts.includes(requiredCheck)) reasons.push(`required_check_missing:${requiredCheck}`);
  if (!Array.isArray(ruleset.bypass_actors)) reasons.push('bypass_unreadable');
  else if (ruleset.bypass_actors.length > 0) reasons.push('bypass_not_empty');
  return { compliant: reasons.length === 0, reasons };
}

/** @brief 选出对 signed_at 有效的 key；已吊销或未生效的 key 不参与验签。 */
function resolveKey(trustRoot, keyId, signedAtMs) {
  const entry = trustRoot?.keys?.[keyId];
  if (!entry || typeof entry.pem !== 'string') return { ok: false, reason: 'attestation_key_unknown' };
  if (keyIdOf(entry.pem) !== keyId) return { ok: false, reason: 'attestation_key_fingerprint_mismatch' };
  const revokedAt = entry.revoked_at ? parseTime(entry.revoked_at) : null;
  if (revokedAt !== null && signedAtMs !== null && signedAtMs >= revokedAt) return { ok: false, reason: 'attestation_key_revoked' };
  const notBefore = entry.not_before ? parseTime(entry.not_before) : null;
  if (notBefore !== null && signedAtMs !== null && signedAtMs < notBefore) return { ok: false, reason: 'attestation_key_not_yet_valid' };
  return { ok: true, pem: entry.pem };
}

const CHECK_KEYS = Object.freeze(['schema_supported', 'declaration_valid', 'repository_matches',
  'ruleset_identity_matches', 'main_scope_matches', 'not_expired', 'signature_valid', 'policy_digest_matches',
  'snapshot_digest_matches', 'updated_at_matches', 'compliant', 'bypass_empty', 'trust_root_intact',
  'rotation_log_consistent']);

/**
 * @brief 校验离线证明是否可用于准入。
 * @param attestation 证明对象（缺失传 null）
 * @param trustRoot 固定信任根；默认由调用方注入，不得取自证明自身
 * @param live 线上只读读取到的规则集（含 rules / conditions / updated_at；bypass 通常不可见）
 * @param repository { id, full_name }
 * @param requiredCheck 必需状态检查名
 * @note 任何无法判定、字段缺失、类型不符的情况一律记入 reasons，由调用方阻断。
 */
function verifyAttestation({ attestation, trustRoot, live, repository = {}, now = new Date(),
  maxTtlDays = MAX_TTL_DAYS, requiredCheck = REQUIRED_CHECK } = {}) {
  const checks = Object.fromEntries(CHECK_KEYS.map(key => [key, false]));
  const reasons = [];
  const nowMs = now instanceof Date ? now.getTime() : parseTime(now);
  const emptyFacts = { key_id: null, captured_at: null, expires_at: null, updated_at: null,
    policy_digest_sha256: null, snapshot_digest_sha256: null, bypass_actors: null, compliant: false };
  if (!attestation || typeof attestation !== 'object' || Array.isArray(attestation)) {
    // 证明缺失时 facts 也要给出显式的 null，避免调用方把 undefined 误当成"空"。
    return { ok: false, checks, reasons: ['attestation_missing'], facts: emptyFacts };
  }
  const fail = reason => { reasons.push(reason); };

  checks.trust_root_intact = trustRootIntact(trustRoot);
  if (!checks.trust_root_intact) fail('trust_root_intact');

  const rotation = rotationLogCheck(trustRoot);
  checks.rotation_log_consistent = rotation.ok;
  for (const reason of rotation.reasons) fail(reason);

  checks.schema_supported = attestation.schema === SCHEMA;
  if (!checks.schema_supported) fail('attestation_schema_unsupported');

  // 声明必须诚实：单人维护、非独立审计。任何试图声称独立审计的证明都不接受。
  const declaration = attestation.governance || {};
  checks.declaration_valid = declaration.mode === 'single_maintainer' && declaration.independent_audit === false
    && typeof declaration.trust_boundary === 'string' && declaration.trust_boundary.length > 0;
  if (!checks.declaration_valid) fail('attestation_declaration_invalid');

  const attestedRepo = attestation.repository || {};
  checks.repository_matches = String(attestedRepo.id) === String(repository.id)
    && typeof attestedRepo.full_name === 'string' && attestedRepo.full_name === repository.full_name;
  if (!checks.repository_matches) fail('attestation_repository_mismatch');

  const attested = attestation.ruleset || {};
  checks.ruleset_identity_matches = live && attested.id === live.id && attested.name === live.name
    && attested.target === live.target && attested.enforcement === live.enforcement
    && live.target === 'branch' && live.enforcement === 'active';
  if (!checks.ruleset_identity_matches) fail('attestation_ruleset_identity_mismatch');

  const attestedRef = refNameOf(attested);
  const liveRef = refNameOf(live);
  checks.main_scope_matches = attestedRef.include.length === 1 && attestedRef.include[0] === GOVERNED_REF
    && attestedRef.exclude.length === 0 && liveRef.include.length === 1 && liveRef.include[0] === GOVERNED_REF
    && liveRef.exclude.length === 0;
  if (!checks.main_scope_matches) fail('attestation_main_scope_mismatch');

  const capturedMs = parseTime(attestation.captured_at);
  const expiresMs = parseTime(attestation.expires_at);
  const ttlMs = capturedMs !== null && expiresMs !== null ? expiresMs - capturedMs : null;
  const ttlWithinLimit = ttlMs !== null && ttlMs > 0 && ttlMs <= maxTtlDays * 24 * 60 * 60 * 1000;
  checks.not_expired = capturedMs !== null && expiresMs !== null && ttlWithinLimit
    && nowMs !== null && nowMs <= expiresMs && nowMs >= capturedMs - CLOCK_SKEW_MS;
  if (!checks.not_expired) fail('attestation_expired_or_invalid_window');

  const signer = attestation.signer || {};
  const signedMs = parseTime(signer.signed_at);
  const resolved = resolveKey(trustRoot, signer.key_id, signedMs);
  if (!resolved.ok) fail(resolved.reason);
  checks.signature_valid = resolved.ok && verifySignature(attestation, resolved.pem);
  if (!checks.signature_valid && resolved.ok) fail('attestation_signature_invalid');

  // policy_digest 双绑定：证明自身一致 + 与线上规则一致。它**不**覆盖 bypass。
  const attestedPolicy = policyDigest(attested);
  const livePolicy = policyDigest(live);
  checks.policy_digest_matches = attestedPolicy !== null && livePolicy !== null
    && attestation.policy_digest_sha256 === attestedPolicy && attestedPolicy === livePolicy;
  if (!checks.policy_digest_matches) fail('attestation_policy_digest_mismatch');

  // snapshot_digest 覆盖 bypass 与 updated_at。线上通常读不到 bypass，故：
  //   - 证明自洽（必查）；
  //   - 若线上确实可见 bypass（管理员凭据场景），额外要求与线上完整快照一致。
  const attestedSnapshot = snapshotDigest(attested);
  const liveSnapshot = snapshotDigest(live);
  const liveSnapshotComparable = liveSnapshot !== null;
  checks.snapshot_digest_matches = attestedSnapshot !== null
    && attestation.snapshot_digest_sha256 === attestedSnapshot
    && (!liveSnapshotComparable || liveSnapshot === attestedSnapshot);
  if (!checks.snapshot_digest_matches) fail('attestation_snapshot_digest_mismatch');

  checks.updated_at_matches = typeof attested.updated_at === 'string' && typeof live?.updated_at === 'string'
    && attested.updated_at === live.updated_at;
  if (!checks.updated_at_matches) fail('attestation_updated_at_mismatch');

  // 合规字段必须为 true，且必须与按证明内容重算的结果一致：不能靠翻字段声称合规。
  const declaredCompliant = attestation.compliant === true;
  const declaredReasons = Array.isArray(attestation.noncompliance_reasons) ? attestation.noncompliance_reasons : null;
  const recomputed = evaluateCompliance(attested, { requiredCheck });
  checks.compliant = declaredCompliant && declaredReasons !== null && declaredReasons.length === 0
    && recomputed.compliant === true;
  if (!checks.compliant) fail(declaredCompliant ? 'attestation_compliance_inconsistent' : 'attestation_not_compliant');

  // 字段缺失 ≠ 为空：必须显式是空数组才算"无绕过者"。
  checks.bypass_empty = Array.isArray(attested.bypass_actors) && attested.bypass_actors.length === 0;
  if (!checks.bypass_empty) fail('attestation_bypass_not_empty');

  const facts = {
    key_id: signer.key_id || null, captured_at: attestation.captured_at || null,
    expires_at: attestation.expires_at || null, updated_at: attested.updated_at || null,
    policy_digest_sha256: typeof attestation.policy_digest_sha256 === 'string' ? attestation.policy_digest_sha256 : null,
    snapshot_digest_sha256: typeof attestation.snapshot_digest_sha256 === 'string' ? attestation.snapshot_digest_sha256 : null,
    bypass_actors: Array.isArray(attested.bypass_actors) ? attested.bypass_actors : null,
    compliant: declaredCompliant, noncompliance_reasons: declaredReasons || null,
  };
  return { ok: reasons.length === 0, checks, reasons: [...new Set(reasons)], facts };
}

module.exports = { SCHEMA, MAX_TTL_DAYS, CLOCK_SKEW_MS, GOVERNED_REF, REQUIRED_CHECK, REQUIRED_RULE_TYPES,
  TRUST_ROOT_ANCHOR_ENV, CHECK_KEYS, canonical, sha256Hex, normalizeRule, normalizePem, refNameOf,
  policyView, policyDigest, normalizeBypass, snapshotView, snapshotDigest, publicKeyFingerprint, keyIdOf,
  signAttestation, verifySignature, trustRootAnchor, rotationLogCheck, trustRootIntact, evaluateCompliance,
  verifyAttestation };
