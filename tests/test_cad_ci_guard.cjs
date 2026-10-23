/** @file CI 授权策略故障注入；只使用合成 REST 快照，不启动 Runner。 */
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { evaluatePolicy, readSnapshot, TRUSTED_REPOSITORY, TRUSTED_REPOSITORY_ID } = require('../scripts/ci/cad_ci_guard.cjs');
/** @brief 构造满足准入条件的离线输入，不代表 GitHub 已配置。 */
function valid() {
  return { context: { repository: TRUSTED_REPOSITORY, repository_id: TRUSTED_REPOSITORY_ID, event_name: 'workflow_dispatch', ref_type: 'branch',
    ref: 'refs/heads/main', ref_protected: true, sha: 'a'.repeat(40), actor: 'owner', triggering_actor: 'maintainer' },
    branch: { protected: true, commit: { sha: 'a'.repeat(40) } },
    rules: [{ type: 'pull_request', parameters: { required_approving_review_count: 1 } },
      { type: 'required_status_checks', parameters: { required_status_checks: [{ context: 'test-and-build' }] } }],
    permissions: { owner: 'admin', maintainer: 'maintain' },
    environment: { id: 1, name: 'cad-validation', protection_rules: [{ type: 'required_reviewers',
      prevent_self_review: true, reviewers: [{ type: 'User', reviewer: { id: 2 } }] }],
      deployment_branch_policy: { protected_branches: true, custom_branch_policies: false } },
    runners: [{ status: 'online', busy: false, labels: ['self-hosted', 'Windows', 'CAD'].map(name => ({ name })) }] };
}
test('main 及其它受保护分支可准入，但不谎称完成整体安全验收', () => {
  const snapshot = valid();
  assert.equal(evaluatePolicy(snapshot).status, 'authorized');
  snapshot.context.ref = 'refs/heads/release/approved-cad';
  assert.equal(evaluatePolicy(snapshot).status, 'authorized');
  assert.equal(evaluatePolicy(snapshot).safety_acceptance_complete, false);
});
const faults = {
  fork: s => { s.context.repository = 'outsider/fork'; },
  replaced_repository: s => { s.context.repository_id = 'unknown'; },
  malformed_sha: s => { s.context.sha = s.branch.commit.sha = 'unknown'; },
  pull_request: s => { s.context.event_name = 'pull_request'; },
  pull_request_target: s => { s.context.event_name = 'pull_request_target'; },
  tag: s => { s.context.ref_type = 'tag'; },
  unprotected: s => { s.context.ref_protected = false; },
  api_unprotected: s => { s.branch.protected = false; },
  moved_branch: s => { s.branch.commit.sha = 'b'.repeat(40); },
  weak_rules: s => { s.rules[0].parameters.required_approving_review_count = 0; },
  missing_checks: s => { s.rules.pop(); },
  unauthorized_actor: s => { s.permissions.owner = 'write'; },
  unauthorized_rerunner: s => { s.permissions.maintainer = 'read'; },
  unknown_actor: s => { delete s.context.actor; },
  missing_environment: s => { s.environment = null; },
  no_reviewers: s => { s.environment.protection_rules[0].reviewers = []; },
  self_review: s => { s.environment.protection_rules[0].prevent_self_review = false; },
  any_branch: s => { s.environment.deployment_branch_policy = null; },
  custom_branch_policy: s => { s.environment.deployment_branch_policy.custom_branch_policies = true; },
  no_runner: s => { s.runners = []; },
  offline_runner: s => { s.runners[0].status = 'offline'; },
  busy_runner: s => { s.runners[0].busy = true; },
  wrong_runner: s => { s.runners[0].labels.pop(); },
};
for (const [name, mutate] of Object.entries(faults)) test(`拒绝 ${name}`, () => {
  const snapshot = valid(); mutate(snapshot);
  assert.equal(evaluatePolicy(snapshot).status, 'blocked');
});
test('不可信上下文不发 API 请求', async () => {
  const snapshot = await readSnapshot({ GITHUB_REPOSITORY: 'outsider/fork' });
  assert.equal(evaluatePolicy(snapshot).status, 'blocked');
});
test('缺少只读审计凭据时阻断，不以 GITHUB_TOKEN 假定具备 Runner 管理读取权限', async () => {
  await assert.rejects(() => readSnapshot({ GITHUB_REPOSITORY: TRUSTED_REPOSITORY,
    GITHUB_REPOSITORY_ID: TRUSTED_REPOSITORY_ID, GITHUB_EVENT_NAME: 'workflow_dispatch',
    GITHUB_REF_TYPE: 'branch', GITHUB_REF_PROTECTED: 'true' }), /CAD_CI_AUDIT_TOKEN missing/);
});
