/**
 * @file 治理敏感文件的漂移检测。
 *
 * 诚实定位（不得表述为防篡改）：本脚本只能把"guard / 工作流 / 信任根 / 证明被修改"这件事
 * 变成一次**显式、可阻断的差异**，不能阻止有合并权的人同时修改本脚本、清单与目标文件。
 * 真正的可信执行需要由基线工作流（pull_request_target 且不检出 PR 代码）或外部审批链承担，
 * 当前仓库不具备该条件，故 guard 报告长期披露 `trusted_baseline_workflow_not_established`。
 *
 * 用法：
 *   node scripts/ci/check_governance_drift.cjs            校验（有差异则退出码 1）
 *   node scripts/ci/check_governance_drift.cjs --list     打印当前清单与摘要
 *   node scripts/ci/check_governance_drift.cjs --update   重新生成清单（须随变更一并提交）
 */
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');

const REPO_ROOT = path.join(__dirname, '..', '..');
const MANIFEST_PATH = path.join('.github', 'governance-sensitive-manifest.json');
const MANIFEST_SCHEMA = 'governance-sensitive-manifest/v1';

/**
 * @brief 安全敏感文件集合；任何改动都必须显式更新清单。
 * @note 清单文件本身**不纳入**摘要：文件包含自身哈希会形成无法收敛的自引用。
 *       它仍由 `.github/CODEOWNERS` 覆盖，且清单内容变化本身就是一次可见 diff。
 */
const SENSITIVE_FILES = Object.freeze([
  '.github/CODEOWNERS',
  '.github/workflows/windows-cad-regression.yml',
  '.github/workflows/windows-release.yml',
  '.github/workflows/skill-mcp-release.yml',
  'docs/architecture/evidence/governance-ruleset-attestation.json',
  'scripts/ci/cad_ci_guard.cjs',
  'scripts/ci/capture_governance_attestation.cjs',
  'scripts/ci/check_governance_drift.cjs',
  'scripts/ci/governance_attestation.cjs',
  'scripts/ci/governance_trust_root.cjs',
  'tests/test_cad_ci_guard.cjs',
]);

/**
 * @brief 对文件内容取 SHA-256，**先做行尾归一化**。
 *
 * @note 为什么必须归一化：Windows 上 `core.autocrlf=true` 会把工作树写成 CRLF，
 *       而 Linux 检出为 LF。若直接对原始字节取摘要，同一个提交在不同平台会得到不同哈希，
 *       表现为**假漂移**并误阻断 `test-and-build`。归一化只抹平 CRLF/LF 差异，
 *       任何实际内容改动仍会产生新摘要，检测能力不降低。
 *       十个敏感文件均为文本，`toString('utf8')` 不会损坏内容。
 */
function sha256OfFile(absolutePath) {
  const text = fs.readFileSync(absolutePath).toString('utf8').replace(/\r\n/g, '\n');
  return crypto.createHash('sha256').update(Buffer.from(text, 'utf8')).digest('hex');
}

/** @brief 按固定顺序收集摘要；文件缺失记为 null，缺失本身也构成漂移。 */
function computeManifest(root = REPO_ROOT) {
  const files = {};
  for (const relative of SENSITIVE_FILES) {
    const absolute = path.join(root, relative.split('/').join(path.sep));
    files[relative] = fs.existsSync(absolute) ? sha256OfFile(absolute) : null;
  }
  return { schema: MANIFEST_SCHEMA, files };
}

/** @brief 逐文件比对，返回 { changed, added, removed } 三类差异。 */
function diffManifest(actual, expected) {
  const changed = [];
  const added = [];
  const removed = [];
  const expectedFiles = expected?.files || {};
  for (const [relative, digest] of Object.entries(actual.files)) {
    if (!Object.prototype.hasOwnProperty.call(expectedFiles, relative)) { added.push(relative); continue; }
    if (expectedFiles[relative] !== digest) changed.push(relative);
  }
  for (const relative of Object.keys(expectedFiles)) {
    if (!Object.prototype.hasOwnProperty.call(actual.files, relative)) removed.push(relative);
  }
  return { changed, added, removed };
}

function readManifest(root = REPO_ROOT) {
  const absolute = path.join(root, MANIFEST_PATH);
  if (!fs.existsSync(absolute)) return { manifest: null, error: `清单缺失: ${MANIFEST_PATH}` };
  try {
    const parsed = JSON.parse(fs.readFileSync(absolute, 'utf8'));
    if (parsed?.schema !== MANIFEST_SCHEMA || !parsed.files) return { manifest: null, error: `清单格式不符: ${MANIFEST_SCHEMA}` };
    return { manifest: parsed, error: null };
  } catch (error) { return { manifest: null, error: `清单不可解析: ${error.message}` }; }
}

function main(argv) {
  const update = argv.includes('--update');
  const list = argv.includes('--list');
  if (update) {
    const manifest = computeManifest();
    const absolute = path.join(REPO_ROOT, MANIFEST_PATH);
    fs.mkdirSync(path.dirname(absolute), { recursive: true });
    fs.writeFileSync(absolute, `${JSON.stringify(manifest, null, 2)}\n`);
    console.log(`已更新治理敏感文件清单: ${MANIFEST_PATH}（${SENSITIVE_FILES.length} 项）`);
    return 0;
  }
  const actual = computeManifest();
  if (list) { console.log(JSON.stringify(actual, null, 2)); return 0; }
  const { manifest, error } = readManifest();
  if (error) { console.error(`BLOCKED: ${error}`); return 1; }
  const { changed, added, removed } = diffManifest(actual, manifest);
  if (changed.length === 0 && added.length === 0 && removed.length === 0) {
    console.log(`治理敏感文件一致（${SENSITIVE_FILES.length} 项）。注意：本检查仅检测漂移，不阻止有权限者一并修改。`);
    return 0;
  }
  console.error('BLOCKED: 治理敏感文件发生未登记的变更');
  for (const file of changed) console.error(`  CHANGED  ${file}`);
  for (const file of added) console.error(`  ADDED    ${file}`);
  for (const file of removed) console.error(`  REMOVED  ${file}`);
  console.error('如为有意变更，请运行 --update 并随同一 PR 提交清单，使变更在评审中可见。');
  return 1;
}

module.exports = { SENSITIVE_FILES, MANIFEST_SCHEMA, MANIFEST_PATH, computeManifest, diffManifest, readManifest, sha256OfFile };
if (require.main === module) process.exitCode = main(process.argv.slice(2));
