/** @file 真机 Runner 分配前的只读授权核验；缺配置、未知或 API 错误均阻断。 */
const fs = require('node:fs');
const TRUSTED_REPOSITORY = 'wzyn20051216/solidworks-automation-skill';
const TRUSTED_REPOSITORY_ID = '1184045765';
const ENVIRONMENT = 'cad-validation';

/** @brief 对 GitHub 实际状态做纯策略判断；供在线读取和离线故障注入共用。 */
function evaluatePolicy(snapshot) {
  const { context = {}, branch = {}, rules = [], permissions = {}, environment = {}, runners = [] } = snapshot;
  const reviewers = environment?.protection_rules?.find(r => r.type === 'required_reviewers');
  const branchPolicy = environment?.deployment_branch_policy;
  const roles = [context.actor, context.triggering_actor].filter(Boolean);
  const checks = {
    trusted_repository: context.repository === TRUSTED_REPOSITORY && context.repository_id === TRUSTED_REPOSITORY_ID,
    manual_branch_only: context.event_name === 'workflow_dispatch' && context.ref_type === 'branch'
      && context.ref?.startsWith('refs/heads/') && context.ref_protected === true,
    protected_immutable_source: branch.protected === true && /^[a-f0-9]{40}$/.test(context.sha || '') && branch.commit?.sha === context.sha,
    reviewed_ruleset: rules.some(r => r.type === 'pull_request' && r.parameters?.required_approving_review_count >= 1)
      && rules.some(r => r.type === 'required_status_checks' && r.parameters?.required_status_checks?.length > 0),
    authorized_actor_and_rerunner: roles.length === 2 && roles.every(actor => ['admin', 'maintain'].includes(permissions[actor])),
    protected_environment_exists: environment?.name === ENVIRONMENT && Number.isInteger(environment?.id),
    independent_human_review: Boolean(reviewers?.prevent_self_review === true && reviewers?.reviewers?.length > 0),
    protected_deployment_branches: Boolean(branchPolicy?.protected_branches === true && branchPolicy?.custom_branch_policies === false),
    idle_windows_cad_runner: runners.some(r => r.status === 'online' && r.busy === false
      && ['self-hosted', 'windows', 'cad'].every(label => r.labels?.some(v => v.name?.toLowerCase() === label))),
  };
  return { status: Object.values(checks).every(Boolean) ? 'authorized' : 'blocked', checks,
    blocking_reasons: Object.keys(checks).filter(k => !checks[k]),
    // Environment 管理员绕过及跨工作流 Runner 隔离不由这份 REST 快照证明。
    scope: 'workflow_admission_only', safety_acceptance_complete: false,
    manual_conditions: ['禁止管理员绕过 Environment 审批', 'Runner 只允许可信工作流访问并与日常桌面隔离'] };
}

/** @brief 固定 GitHub API 域名，只读请求；凭据不写入报告。 */
async function readSnapshot(env = process.env) {
  const context = { repository: env.GITHUB_REPOSITORY, repository_id: env.GITHUB_REPOSITORY_ID, event_name: env.GITHUB_EVENT_NAME, ref: env.GITHUB_REF,
    ref_type: env.GITHUB_REF_TYPE, ref_protected: env.GITHUB_REF_PROTECTED === 'true', sha: env.GITHUB_SHA,
    actor: env.GITHUB_ACTOR, triggering_actor: env.GITHUB_TRIGGERING_ACTOR };
  if (context.repository !== TRUSTED_REPOSITORY || context.repository_id !== TRUSTED_REPOSITORY_ID || context.event_name !== 'workflow_dispatch'
      || context.ref_type !== 'branch' || !context.ref_protected) {
    return { context }; // 不为不可信上下文发起权限请求。
  }
  if (!env.GH_TOKEN) throw new Error('BLOCKED: CAD_CI_AUDIT_TOKEN missing (selected repository, Administration/Actions/Metadata read only)');
  const get = async path => {
    const response = await fetch(`https://api.github.com${path}`, { headers: {
      Authorization: `Bearer ${env.GH_TOKEN}`, Accept: 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28' } });
    if (!response.ok) throw new Error(`GitHub read failed: HTTP ${response.status} ${path}`);
    return response.json();
  };
  const base = `/repos/${TRUSTED_REPOSITORY}`;
  const branchName = encodeURIComponent(context.ref.slice('refs/heads/'.length));
  const [branch, rules, environment, runnerResponse] = await Promise.all([
    get(`${base}/branches/${branchName}`), get(`${base}/rules/branches/${branchName}`),
    get(`${base}/environments/${ENVIRONMENT}`), get(`${base}/actions/runners?per_page=100`),
  ]);
  // 分页不完整则不假定已经检查了全部候选 Runner。
  if (runnerResponse.total_count > runnerResponse.runners.length) throw new Error('Runner snapshot requires pagination; blocked');
  const permissions = {};
  for (const actor of new Set([context.actor, context.triggering_actor])) {
    const value = await get(`${base}/collaborators/${encodeURIComponent(actor)}/permission`);
    permissions[actor] = value.role_name || value.permission;
  }
  return { context, branch, rules, environment, runners: runnerResponse.runners, permissions };
}

/** @brief CLI 仅在线读取，不提供可绕过核验的本地快照输入开关。 */
async function main() {
  let report;
  try { const snapshot = await readSnapshot(); report = { ...evaluatePolicy(snapshot), context: snapshot.context }; }
  catch (error) { report = { status: 'blocked', safety_acceptance_complete: false, error: error.message }; }
  fs.writeFileSync('cad-ci-admission.json', JSON.stringify(report, null, 2));
  if (process.env.GITHUB_OUTPUT) fs.appendFileSync(process.env.GITHUB_OUTPUT, `authorized=${report.status === 'authorized'}\n`);
  console.log(JSON.stringify(report, null, 2));
  return report.status === 'authorized' ? 0 : 1;
}
module.exports = { evaluatePolicy, readSnapshot, TRUSTED_REPOSITORY, TRUSTED_REPOSITORY_ID, ENVIRONMENT };
if (require.main === module) main().then(code => { process.exitCode = code; });
